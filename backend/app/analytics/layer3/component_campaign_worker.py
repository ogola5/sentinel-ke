from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Set

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import AICampaignRiskIndicator, AIPrediction
from app.campaign.models import Campaign, CampaignEntity


COMPONENT_CAMPAIGN_TYPE = "GNN_COMPONENT"
COMPONENT_RULE_VERSION = "gnn.component.v2"
LEGAL_RISK_NOTICE = (
    "AI-discovered campaign structure is a prioritisation aid. "
    "It requires analyst review before enforcement."
)


def _severity_from_score(score: float) -> str:
    value = float(score or 0.0)
    if value >= 90.0:
        return "critical"
    if value >= 75.0:
        return "high"
    if value >= 55.0:
        return "medium"
    return "low"


def _connected_components(entity_keys: List[str], edges: List[tuple[str, str]]) -> List[List[str]]:
    adj: Dict[str, Set[str]] = {k: set() for k in entity_keys}
    for src, dst in edges:
        if src == dst or src not in adj or dst not in adj:
            continue
        adj[src].add(dst)
        adj[dst].add(src)

    out: List[List[str]] = []
    seen: Set[str] = set()
    for key in entity_keys:
        if key in seen:
            continue
        stack = [key]
        comp: List[str] = []
        seen.add(key)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in adj.get(cur, set()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                stack.append(nxt)
        out.append(sorted(comp))
    out.sort(key=lambda x: (-len(x), x[0] if x else ""))
    return out


def _component_primary_key(
    *,
    prediction_type: str,
    window_key: str,
    window_end: datetime,
    entity_keys: List[str],
) -> str:
    h = hashlib.sha256()
    h.update(str(prediction_type).encode("utf-8"))
    h.update(b"|")
    h.update(str(window_key).encode("utf-8"))
    h.update(b"|")
    h.update(window_end.isoformat().encode("utf-8"))
    for key in sorted(entity_keys):
        h.update(b"|")
        h.update(str(key).encode("utf-8"))
    return f"gnn-component:{h.hexdigest()}"


def _upsert_campaign_indicators(
    db: Session,
    *,
    model_version: str,
    prediction_type: str,
    window_key: str,
    window_end: datetime,
) -> Dict[str, int]:
    rows = db.execute(
        text(
            """
            SELECT
                c.id AS campaign_id,
                c.type AS campaign_type,
                c.primary_key AS campaign_key,
                ap.entity_key,
                ap.entity_type,
                ap.score
            FROM campaign c
            JOIN campaign_entity ce ON ce.campaign_id = c.id
            JOIN ai_prediction ap ON ap.entity_key = ce.entity_key
            WHERE ap.prediction_type = :prediction_type
              AND ap.window_key = :window_key
              AND ap.window_end = :window_end
            """
        ),
        {
            "prediction_type": prediction_type,
            "window_key": window_key,
            "window_end": window_end,
        },
    ).fetchall()

    grouped: Dict[str, Dict[str, object]] = {}
    for r in rows:
        cid = str(r[0])
        g = grouped.setdefault(
            cid,
            {
                "campaign_id": r[0],
                "campaign_type": str(r[1] or "unknown"),
                "campaign_key": str(r[2] or ""),
                "entities": [],
            },
        )
        g["entities"].append(
            {
                "entity_key": str(r[3]),
                "entity_type": str(r[4]),
                "score": float(r[5] or 0.0),
            }
        )

    created = 0
    updated = 0
    now = datetime.now(timezone.utc)

    for g in grouped.values():
        entities = list(g["entities"])
        if not entities:
            continue

        scored = sorted(entities, key=lambda x: float(x["score"]), reverse=True)
        total = len(scored)
        max_score = float(scored[0]["score"])
        avg_score = sum(float(x["score"]) for x in scored) / max(1, total)
        flagged = sum(1 for x in scored if float(x["score"]) >= 70.0)
        flagged_ratio = flagged / max(1, total)
        score = round(min(100.0, 0.45 * avg_score + 0.35 * max_score + 0.2 * (flagged_ratio * 100.0)), 4)
        severity = _severity_from_score(score)

        reason_codes = [
            "CAMPAIGN_RISK_INDICATOR",
            "DISCOVERED_FROM_GRAPH_COMPONENT",
            "RISK_INDICATOR_ONLY_NOT_FINAL_PROOF",
        ]
        details = {
            "campaign_type": g["campaign_type"],
            "campaign_key": g["campaign_key"],
            "avg_entity_score": round(avg_score, 4),
            "max_entity_score": round(max_score, 4),
            "flagged_entity_ratio": round(flagged_ratio, 4),
            "legal_notice": LEGAL_RISK_NOTICE,
        }
        evidence_keys = [str(x["entity_key"]) for x in scored[:10]]

        existing = (
            db.query(AICampaignRiskIndicator)
            .filter(AICampaignRiskIndicator.campaign_id == g["campaign_id"])
            .filter(AICampaignRiskIndicator.prediction_type == prediction_type)
            .filter(AICampaignRiskIndicator.window_key == window_key)
            .filter(AICampaignRiskIndicator.window_end == window_end)
            .first()
        )
        if existing:
            existing.model_version = model_version
            existing.score = score
            existing.severity = severity
            existing.flagged_entity_count = flagged
            existing.total_entity_count = total
            existing.reason_codes = reason_codes
            existing.details_json = details
            existing.evidence_entity_keys = evidence_keys
            existing.updated_at = now
            updated += 1
        else:
            db.add(
                AICampaignRiskIndicator(
                    campaign_id=g["campaign_id"],
                    prediction_type=prediction_type,
                    model_version=model_version,
                    window_key=window_key,
                    window_end=window_end,
                    score=score,
                    severity=severity,
                    flagged_entity_count=flagged,
                    total_entity_count=total,
                    reason_codes=reason_codes,
                    details_json=details,
                    evidence_entity_keys=evidence_keys,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1

    return {"created": created, "updated": updated}


def run_once(
    *,
    db: Session,
    prediction_type: str,
    window_key: str,
    window_end: datetime,
    min_size: int = 3,
    min_indicator_ratio: float = 0.5,
    max_entities: int = 5000,
) -> Dict[str, int]:
    preds = (
        db.query(AIPrediction)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.window_end == window_end)
        .order_by(AIPrediction.score.desc())
        .limit(max_entities)
        .all()
    )
    if not preds:
        return {
            "campaigns_created": 0,
            "campaigns_updated": 0,
            "entities_upserted": 0,
            "components_considered": 0,
            "indicators_created": 0,
            "indicators_updated": 0,
        }

    entities = [str(p.entity_key) for p in preds]
    pred_by_entity = {str(p.entity_key): p for p in preds}
    rows = db.execute(
        text(
            """
            SELECT a.entity_key AS src, b.entity_key AS dst
            FROM event_entity_index a
            JOIN event_entity_index b
              ON a.event_hash = b.event_hash
             AND a.entity_key < b.entity_key
            JOIN event_log el ON el.event_hash = a.event_hash
            WHERE el.occurred_at <= :window_end
              AND a.entity_key = ANY(:entities)
              AND b.entity_key = ANY(:entities)
            GROUP BY a.entity_key, b.entity_key
            HAVING COUNT(*) >= 1
            """
        ),
        {"window_end": window_end, "entities": entities},
    ).fetchall()
    edges = [(str(r[0]), str(r[1])) for r in rows]
    comps = _connected_components(entities, edges)

    campaigns_created = 0
    campaigns_updated = 0
    entities_upserted = 0
    components_considered = 0

    for comp in comps:
        components_considered += 1
        if len(comp) < max(2, int(min_size)):
            continue
        indicator_keys = [k for k in comp if float(pred_by_entity[k].score or 0.0) >= 70.0]
        if not indicator_keys:
            continue
        ratio = len(indicator_keys) / max(1, len(comp))
        if ratio < max(0.0, float(min_indicator_ratio)):
            continue

        primary_key = _component_primary_key(
            prediction_type=prediction_type,
            window_key=window_key,
            window_end=window_end,
            entity_keys=comp,
        )
        max_score = max(float(pred_by_entity[k].score or 0.0) for k in comp)
        avg_score = sum(float(pred_by_entity[k].score or 0.0) for k in comp) / max(1, len(comp))
        campaign = (
            db.query(Campaign)
            .filter(Campaign.type == COMPONENT_CAMPAIGN_TYPE)
            .filter(Campaign.primary_key == primary_key)
            .first()
        )
        stats = {
            "discovery": "graph_connected_component",
            "window_key": window_key,
            "window_end": window_end.isoformat(),
            "component_size": len(comp),
            "indicator_count": len(indicator_keys),
            "indicator_ratio": round(ratio, 4),
            "avg_entity_score": round(avg_score, 4),
            "max_entity_score": round(max_score, 4),
            "legal_notice": LEGAL_RISK_NOTICE,
        }
        if campaign:
            campaign.last_seen = window_end
            campaign.event_count = max(int(campaign.event_count or 0), len(comp))
            campaign.score = max(float(campaign.score or 0.0), max_score / 100.0)
            campaign.status = "active"
            campaign.stats = stats
            campaigns_updated += 1
        else:
            campaign = Campaign(
                type=COMPONENT_CAMPAIGN_TYPE,
                primary_key=primary_key,
                status="active",
                rule_version=COMPONENT_RULE_VERSION,
                first_seen=window_end,
                last_seen=window_end,
                event_count=len(comp),
                score=round(max_score / 100.0, 6),
                stats=stats,
            )
            db.add(campaign)
            db.flush()
            campaigns_created += 1

        for entity_key in comp:
            pred = pred_by_entity[entity_key]
            role = "indicator" if entity_key in indicator_keys else "member"
            stmt = insert(CampaignEntity).values(
                campaign_id=campaign.id,
                entity_key=entity_key,
                entity_type=str(pred.entity_type or "unknown"),
                role=role,
                last_seen=window_end,
            ).on_conflict_do_update(
                index_elements=["campaign_id", "entity_key"],
                set_={
                    "entity_type": str(pred.entity_type or "unknown"),
                    "role": role,
                    "last_seen": window_end,
                },
            )
            db.execute(stmt)
            entities_upserted += 1

    indicator_stats = _upsert_campaign_indicators(
        db,
        model_version=str(preds[0].model_version or "unknown"),
        prediction_type=prediction_type,
        window_key=window_key,
        window_end=window_end,
    )
    db.commit()
    return {
        "campaigns_created": campaigns_created,
        "campaigns_updated": campaigns_updated,
        "entities_upserted": entities_upserted,
        "components_considered": components_considered,
        "indicators_created": indicator_stats["created"],
        "indicators_updated": indicator_stats["updated"],
    }
