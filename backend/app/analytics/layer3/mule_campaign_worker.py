from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.campaign.models import Campaign, CampaignEntity, CampaignEvent
from app.graph.ontology import NodeRef, make_edge, make_node, dedupe_edges, dedupe_nodes
from app.graph.projector import GraphDelta
from app.graph.repository import GraphDeltaRepository
from app.ledger.db import SessionLocal
from app.ledger.models import EventLog, SourceRegistry


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_cashout(channel: Optional[str]) -> bool:
    if not channel:
        return False
    return channel.strip().upper() in {"AGENT_CASHOUT", "CASHOUT", "AGENT"}


def _score_from_stats(distinct_senders: int, tx_count: int, cashout_delay_sec: Optional[float]) -> float:
    score = 0.4
    score += min(0.4, distinct_senders * 0.08)
    score += min(0.2, tx_count * 0.02)
    if cashout_delay_sec is not None and cashout_delay_sec <= 900:
        score += 0.1
    return min(1.0, score)


def _upsert_campaign_entity(db: Session, *, campaign_id, entity_key: str, entity_type: str, role: str, seen_at: datetime) -> None:
    stmt = insert(CampaignEntity).values(
        campaign_id=campaign_id,
        entity_key=entity_key,
        entity_type=entity_type,
        role=role,
        last_seen=seen_at,
    ).on_conflict_do_update(
        index_elements=["campaign_id", "entity_key"],
        set_={"last_seen": seen_at, "role": role},
    )
    db.execute(stmt)


def _insert_campaign_event(db: Session, *, campaign_id, event_hash: str, occurred_at: datetime) -> None:
    stmt = insert(CampaignEvent).values(
        campaign_id=campaign_id,
        event_hash=event_hash,
        occurred_at=occurred_at,
    ).on_conflict_do_nothing(
        index_elements=["campaign_id", "event_hash"],
    )
    db.execute(stmt)


def run_once(
    *,
    db: Session,
    minutes: int = 180,
    min_senders: int = 2,
    min_tx: int = 4,
    max_new: int = 50,
) -> int:
    cutoff = _now_utc() - timedelta(minutes=minutes)

    rows = db.execute(
        text(
            """
            SELECT
                event_hash,
                occurred_at,
                COALESCE(payload_json->>'account_h_from', payload_json->>'account_from') AS account_from,
                COALESCE(payload_json->>'account_h_to', payload_json->>'account_to') AS account_to,
                payload_json->>'amount' AS amount,
                payload_json->>'channel' AS channel,
                COALESCE(payload_json->>'agent_id', anchors_json->>'agent_id') AS agent_id
            FROM event_log
            WHERE event_type = 'TRANSACTION_EVENT'
              AND occurred_at >= :cutoff
            """
        ),
        {"cutoff": cutoff},
    ).fetchall()

    if not rows:
        return 0

    inbound: Dict[str, List[dict]] = {}
    cashout: Dict[str, List[dict]] = {}

    for event_hash, occurred_at, account_from, account_to, amount, channel, agent_id in rows:
        if not occurred_at:
            continue
        if _is_cashout(channel):
            if not account_from:
                continue
            cashout.setdefault(str(account_from), []).append(
                {
                    "event_hash": str(event_hash),
                    "occurred_at": occurred_at,
                    "amount": float(amount) if amount else None,
                    "agent_id": str(agent_id) if agent_id else None,
                }
            )
        else:
            if not account_to or not account_from:
                continue
            inbound.setdefault(str(account_to), []).append(
                {
                    "event_hash": str(event_hash),
                    "occurred_at": occurred_at,
                    "sender": str(account_from),
                    "amount": float(amount) if amount else None,
                    "agent_id": str(agent_id) if agent_id else None,
                }
            )

    created = 0
    repo = GraphDeltaRepository(db)

    for mule_account, events in inbound.items():
        if created >= max_new:
            break
        if len(events) < min_tx:
            continue
        senders = {e["sender"] for e in events if e.get("sender")}
        if len(senders) < min_senders:
            continue

        first_seen = min(e["occurred_at"] for e in events)
        last_seen = max(e["occurred_at"] for e in events)
        total_amount = sum(e["amount"] or 0.0 for e in events)
        avg_amount = total_amount / max(1, len(events))

        cash_events = cashout.get(mule_account, [])
        cashout_delay = None
        agent_ids = sorted({e["agent_id"] for e in cash_events if e.get("agent_id")})
        if cash_events:
            cash_first = min(e["occurred_at"] for e in cash_events)
            cashout_delay = (cash_first - first_seen).total_seconds()
            last_seen = max(last_seen, max(e["occurred_at"] for e in cash_events))

        score = _score_from_stats(len(senders), len(events), cashout_delay)
        primary_key = f"account_h:{mule_account}"

        campaign = (
            db.query(Campaign)
            .filter(Campaign.type == "MULE_RING", Campaign.primary_key == primary_key)
            .first()
        )
        if not campaign:
            campaign = Campaign(
                id=uuid.uuid4(),
                type="MULE_RING",
                primary_key=primary_key,
                status="active",
                rule_version="mule.ring.v1",
                first_seen=first_seen,
                last_seen=last_seen,
                event_count=0,
                score=score,
                stats={},
            )
            db.add(campaign)
            db.flush()
            created += 1
        else:
            campaign.last_seen = max(campaign.last_seen, last_seen)
            campaign.score = max(campaign.score, score)

        # entities
        _upsert_campaign_entity(
            db,
            campaign_id=campaign.id,
            entity_key=primary_key,
            entity_type="Account",
            role="mule",
            seen_at=last_seen,
        )
        for sender in senders:
            _upsert_campaign_entity(
                db,
                campaign_id=campaign.id,
                entity_key=f"account_h:{sender}",
                entity_type="Account",
                role="victim",
                seen_at=last_seen,
            )
        for agent_id in agent_ids:
            _upsert_campaign_entity(
                db,
                campaign_id=campaign.id,
                entity_key=f"agent_id:{agent_id}",
                entity_type="Agent",
                role="cashout_agent",
                seen_at=last_seen,
            )

        # events
        for e in events:
            _insert_campaign_event(db, campaign_id=campaign.id, event_hash=e["event_hash"], occurred_at=e["occurred_at"])
            campaign.event_count += 1
        for e in cash_events:
            _insert_campaign_event(db, campaign_id=campaign.id, event_hash=e["event_hash"], occurred_at=e["occurred_at"])
            campaign.event_count += 1

        campaign.stats = {
            "distinct_senders": len(senders),
            "tx_count": len(events),
            "total_amount": round(total_amount, 2),
            "avg_amount": round(avg_amount, 2),
            "time_span_sec": int((last_seen - first_seen).total_seconds()),
            "cashout_delay_sec": int(cashout_delay) if cashout_delay is not None else None,
            "agent_ids": agent_ids,
            "window_minutes": minutes,
        }

        # Project campaign to Neo4j (use synthetic event hash with real event_log row)
        source = db.query(SourceRegistry).first()
        if not source:
            continue
        ev_hash = f"campaign:mule:{campaign.id}"
        if not db.query(EventLog).filter(EventLog.event_hash == ev_hash).first():
            db.add(
                EventLog(
                    event_hash=ev_hash,
                    event_type="CAMPAIGN_EVENT",
                    source_id=source.source_id,
                    classification=source.classification_level,
                    occurred_at=last_seen,
                    schema_version="v1",
                    signature_valid=False,
                    anchors_json={},
                    payload_json={"campaign_id": str(campaign.id), "type": campaign.type},
                )
            )
            db.flush()
        nodes = [
            make_node(
                NodeRef("Campaign", str(campaign.id)),
                type=campaign.type,
                status=campaign.status,
                score=campaign.score,
                first_seen=campaign.first_seen.isoformat(),
                last_seen=campaign.last_seen.isoformat(),
            ),
            make_node(NodeRef("Account", primary_key), kind="mule"),
        ]
        edges = [
            make_edge(
                "INVOLVES",
                NodeRef("Campaign", str(campaign.id)),
                NodeRef("Account", primary_key),
                evidence=[ev_hash],
                role="mule",
            )
        ]
        for sender in senders:
            key = f"account_h:{sender}"
            nodes.append(make_node(NodeRef("Account", key), kind="victim"))
            edges.append(
                make_edge(
                    "INVOLVES",
                    NodeRef("Campaign", str(campaign.id)),
                    NodeRef("Account", key),
                    evidence=[ev_hash],
                    role="victim",
                )
            )

        delta = GraphDelta(
            event_hash=ev_hash,
            nodes=dedupe_nodes(nodes),
            edges=dedupe_edges(edges),
        )
        repo.insert_delta(
            event_hash=delta.event_hash,
            nodes=[n.__dict__ for n in delta.nodes],
            edges=[e.__dict__ for e in delta.edges],
        )

    db.commit()
    return created


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=int, default=180)
    p.add_argument("--min-senders", type=int, default=2)
    p.add_argument("--min-tx", type=int, default=4)
    p.add_argument("--max-new", type=int, default=50)
    args = p.parse_args()

    db = SessionLocal()
    try:
        n = run_once(
            db=db,
            minutes=args.minutes,
            min_senders=args.min_senders,
            min_tx=args.min_tx,
            max_new=args.max_new,
        )
        print(f"mule_campaign_worker created={n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
