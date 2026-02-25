"""
Sentinel-KE — Synthetic GNN Training Data Generator
=====================================================

Inserts realistic Kenyan fraud scenario data directly into:
  - source_registry     (one synthetic source)
  - event_log           (shared events that create co-occurrence edges)
  - event_entity_index  (maps events → entity keys)
  - graph_feature_snapshot  (per-entity feature vectors for GNN training)

Five fraud families modelled on East-African patterns:
  1. M-Pesa Mule Network   — accounts laundering mobile money
  2. SIM-Swap Cluster      — phone numbers used in account takeovers
  3. VPN Fraud Ring        — IPs masked via VPN to commit financial fraud
  4. DDoS Botnet           — IPs attacking Kenyan critical services
  5. Phishing Campaign     — domains/phones in a smishing network

Usage (inside the running backend container or local venv):
  python -m app.demo.synthetic_ke_gnn_data
  python -m app.demo.synthetic_ke_gnn_data --window-hours 4 --benign 150 --seed 42
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.dialects.postgresql import insert as pg_insert

import app.db.registry  # noqa: F401 — register all models
from app.analytics.ai_models import GraphFeatureSnapshot
from app.ledger.db import SessionLocal, engine
from app.ledger.models import Base, EventEntityIndex, EventLog, SourceRegistry

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("sentinel.synthetic")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYNTH_SOURCE_ID = "synthetic-gnn-seed"
WINDOW_KEY = "Wmid"
MODEL_CLASSIFICATION = "RESTRICTED"

ENTITY_TYPES = ["ip", "domain", "url", "service_id", "endpoint",
                "provider_id", "device_id", "account_h", "phone_h", "person_h"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event_hash(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return f"synth:{h[:48]}"


def _snap_exists(db, entity_key: str, window_key: str, window_end: datetime) -> bool:
    return (
        db.query(GraphFeatureSnapshot)
        .filter(
            GraphFeatureSnapshot.entity_key == entity_key,
            GraphFeatureSnapshot.window_key == window_key,
            GraphFeatureSnapshot.window_end == window_end,
        )
        .first()
    ) is not None


# ---------------------------------------------------------------------------
# Step 1: ensure synthetic source exists
# ---------------------------------------------------------------------------

def _ensure_source(db) -> None:
    stmt = pg_insert(SourceRegistry).values(
        source_id=SYNTH_SOURCE_ID,
        source_type="synthetic",
        section_code="SYNTH",
        classification_level=MODEL_CLASSIFICATION,
        api_key_hash=hashlib.sha256(b"synthetic-gnn-seed-key").hexdigest(),
        is_active=True,
    ).on_conflict_do_nothing(index_elements=["source_id"])
    db.execute(stmt)
    db.flush()


# ---------------------------------------------------------------------------
# Step 2: insert shared events (creates co-occurrence edges)
# ---------------------------------------------------------------------------

def _insert_shared_event(
    db,
    *,
    event_type: str,
    entity_keys: List[str],
    occurred_at: datetime,
    payload: Optional[Dict] = None,
    idx: int = 0,
) -> str:
    """Insert one event_log row + one event_entity_index row per entity."""
    h = _event_hash(event_type, *sorted(entity_keys), str(occurred_at.isoformat()), str(idx))

    # Insert event_log (ignore duplicate)
    stmt = pg_insert(EventLog).values(
        event_hash=h,
        event_type=event_type,
        source_id=SYNTH_SOURCE_ID,
        classification=MODEL_CLASSIFICATION,
        occurred_at=occurred_at,
        received_at=occurred_at,
        anchors_json={ek.split(":")[0]: ek.split(":", 1)[1] for ek in entity_keys if ":" in ek},
        payload_json=payload or {},
    ).on_conflict_do_nothing(index_elements=["event_hash"])
    db.execute(stmt)

    # Insert index rows
    for ek in entity_keys:
        stmt2 = pg_insert(EventEntityIndex).values(
            event_hash=h,
            entity_key=ek,
        ).on_conflict_do_nothing(index_elements=["event_hash", "entity_key"])
        db.execute(stmt2)

    return h


def _make_shared_events(
    db,
    *,
    family_entities: List[str],
    event_type: str,
    count: int,
    window_start: datetime,
    window_end: datetime,
    rng: random.Random,
    group_size: int = 3,
) -> None:
    """
    Create `count` co-occurrence events for this family.
    Each event connects `group_size` randomly sampled entities.
    """
    span_sec = max(1, int((window_end - window_start).total_seconds()))
    for i in range(count):
        participants = rng.sample(family_entities, min(group_size, len(family_entities)))
        ts = window_start + timedelta(seconds=rng.randint(0, span_sec))
        _insert_shared_event(
            db,
            event_type=event_type,
            entity_keys=participants,
            occurred_at=ts,
            idx=i,
        )


# ---------------------------------------------------------------------------
# Step 3: insert GraphFeatureSnapshot rows
# ---------------------------------------------------------------------------

def _upsert_snapshot(db, snap_kwargs: dict) -> None:
    stmt = pg_insert(GraphFeatureSnapshot).values(**snap_kwargs).on_conflict_do_update(
        index_elements=["entity_key", "window_key", "window_end"],
        set_={
            "risk_flags": snap_kwargs["risk_flags"],
            "features": snap_kwargs["features"],
            "event_count": snap_kwargs["event_count"],
            "degree": snap_kwargs["degree"],
            "weighted_degree": snap_kwargs["weighted_degree"],
        },
    )
    db.execute(stmt)


def _make_snapshot(
    *,
    entity_key: str,
    entity_type: str,
    window_key: str,
    window_start: datetime,
    window_end: datetime,
    event_count: int,
    source_count: int,
    degree: int,
    weighted_degree: int,
    risk_flags: List[str],
    event_types: Dict[str, int],
    rng: random.Random,
) -> dict:
    age_sec = rng.randint(30, 600)
    last_seen = window_end - timedelta(seconds=age_sec)
    first_seen = window_start + timedelta(seconds=rng.randint(0, 3600))

    return dict(
        id=uuid.uuid4(),
        entity_key=entity_key,
        entity_type=entity_type,
        window_key=window_key,
        window_start=window_start,
        window_end=window_end,
        degree=degree,
        weighted_degree=weighted_degree,
        event_count=event_count,
        first_seen=first_seen,
        last_seen=last_seen,
        risk_flags=risk_flags,
        features={
            "source_count": source_count,
            "event_types": event_types,
            "last_seen_age_sec": age_sec,
        },
    )


# ---------------------------------------------------------------------------
# Family generators
# ---------------------------------------------------------------------------

def _family_mule_network(
    db, *, window_start: datetime, window_end: datetime, rng: random.Random
) -> List[str]:
    """
    M-Pesa mule network: 15 accounts + 8 IPs + 5 phones sharing transactions.
    All labelled via CAMPAIGN_ENTITY risk flag.
    """
    accounts = [f"account_h:ke_mule_{i:03d}" for i in range(15)]
    ips = [f"ip:41.{rng.randint(200,250)}.{rng.randint(1,254)}.{rng.randint(1,254)}" for i in range(8)]
    phones = [f"phone_h:ke_phone_mule_{i:02d}" for i in range(5)]
    all_ents = accounts + ips + phones

    # Co-occurrence: accounts share TRANSACTION_EVENTs with IPs
    _make_shared_events(db, family_entities=all_ents, event_type="TRANSACTION_EVENT",
                        count=40, window_start=window_start, window_end=window_end, rng=rng, group_size=3)
    _make_shared_events(db, family_entities=accounts + phones, event_type="LOGIN_EVENT",
                        count=15, window_start=window_start, window_end=window_end, rng=rng, group_size=2)

    for ek in accounts:
        txn = rng.randint(12, 45)
        login = rng.randint(1, 5)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="account_h",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=txn + login, source_count=rng.randint(3, 8),
            degree=rng.randint(4, 12), weighted_degree=rng.randint(8, 30),
            risk_flags=["CAMPAIGN_ENTITY"],
            event_types={"TRANSACTION_EVENT": txn, "LOGIN_EVENT": login}, rng=rng,
        ))
    for ek in ips:
        txn = rng.randint(5, 25)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="ip",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=txn, source_count=rng.randint(2, 5),
            degree=rng.randint(3, 10), weighted_degree=rng.randint(5, 20),
            risk_flags=["CAMPAIGN_ENTITY"],
            event_types={"TRANSACTION_EVENT": txn}, rng=rng,
        ))
    for ek in phones:
        sim = rng.randint(0, 3)
        txn = rng.randint(3, 15)
        login = rng.randint(1, 4)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="phone_h",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=sim + txn + login, source_count=rng.randint(2, 5),
            degree=rng.randint(2, 8), weighted_degree=rng.randint(3, 15),
            risk_flags=["CAMPAIGN_ENTITY"],
            event_types={"SIM_SWAP_EVENT": sim, "TRANSACTION_EVENT": txn, "LOGIN_EVENT": login}, rng=rng,
        ))

    log.info("family=mule_network nodes=%d", len(all_ents))
    return all_ents


def _family_sim_swap_cluster(
    db, *, window_start: datetime, window_end: datetime, rng: random.Random
) -> List[str]:
    """
    SIM-swap attack cluster: phone numbers attacked + account takeovers.
    """
    phones = [f"phone_h:ke_sim_{i:03d}" for i in range(12)]
    accounts = [f"account_h:ke_simacct_{i:03d}" for i in range(8)]
    ips = [f"ip:196.{rng.randint(200,254)}.{rng.randint(1,254)}.{rng.randint(1,254)}" for i in range(3)]
    all_ents = phones + accounts + ips

    _make_shared_events(db, family_entities=phones + accounts, event_type="SIM_SWAP_EVENT",
                        count=20, window_start=window_start, window_end=window_end, rng=rng, group_size=2)
    _make_shared_events(db, family_entities=all_ents, event_type="LOGIN_EVENT",
                        count=15, window_start=window_start, window_end=window_end, rng=rng, group_size=3)

    for ek in phones:
        sim = rng.randint(2, 8)
        login = rng.randint(1, 6)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="phone_h",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=sim + login, source_count=rng.randint(2, 4),
            degree=rng.randint(2, 7), weighted_degree=rng.randint(3, 12),
            risk_flags=["CAMPAIGN_ENTITY"],
            event_types={"SIM_SWAP_EVENT": sim, "LOGIN_EVENT": login}, rng=rng,
        ))
    for ek in accounts:
        sim = rng.randint(1, 3)
        txn = rng.randint(2, 10)
        login = rng.randint(1, 3)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="account_h",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=sim + txn + login, source_count=rng.randint(1, 4),
            degree=rng.randint(2, 6), weighted_degree=rng.randint(2, 10),
            risk_flags=["CAMPAIGN_ENTITY"],
            event_types={"SIM_SWAP_EVENT": sim, "TRANSACTION_EVENT": txn, "LOGIN_EVENT": login}, rng=rng,
        ))
    for ek in ips:
        login = rng.randint(3, 12)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="ip",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=login, source_count=rng.randint(1, 3),
            degree=rng.randint(2, 6), weighted_degree=rng.randint(2, 8),
            risk_flags=["CAMPAIGN_ENTITY"],
            event_types={"LOGIN_EVENT": login}, rng=rng,
        ))

    log.info("family=sim_swap_cluster nodes=%d", len(all_ents))
    return all_ents


def _family_vpn_fraud_ring(
    db, *, window_start: datetime, window_end: datetime, rng: random.Random
) -> List[str]:
    """
    VPN-masked fraud ring: IPs sharing a VPN cluster + fraud domains.
    """
    ips = [f"ip:10.vpn.{i:03d}" if i < 5
           else f"ip:185.{rng.randint(100,200)}.{rng.randint(1,254)}.{rng.randint(1,254)}"
           for i in range(14)]
    domains = [f"domain:fraud-ke-{i:02d}.net" for i in range(4)]
    all_ents = ips + domains

    _make_shared_events(db, family_entities=all_ents, event_type="DNS_RESOLUTION_EVENT",
                        count=30, window_start=window_start, window_end=window_end, rng=rng, group_size=3)
    _make_shared_events(db, family_entities=ips, event_type="TRANSACTION_EVENT",
                        count=15, window_start=window_start, window_end=window_end, rng=rng, group_size=2)

    for ek in ips:
        dns = rng.randint(5, 20)
        txn = rng.randint(2, 12)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="ip",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=dns + txn, source_count=rng.randint(2, 6),
            degree=rng.randint(3, 10), weighted_degree=rng.randint(4, 18),
            risk_flags=["VPN_CLUSTER_MEMBER"],
            event_types={"DNS_RESOLUTION_EVENT": dns, "TRANSACTION_EVENT": txn}, rng=rng,
        ))
    for ek in domains:
        dns = rng.randint(8, 30)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="domain",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=dns, source_count=rng.randint(3, 8),
            degree=rng.randint(4, 12), weighted_degree=rng.randint(5, 20),
            risk_flags=["VPN_CLUSTER_MEMBER"],
            event_types={"DNS_RESOLUTION_EVENT": dns}, rng=rng,
        ))

    log.info("family=vpn_fraud_ring nodes=%d", len(all_ents))
    return all_ents


def _family_ddos_botnet(
    db, *, window_start: datetime, window_end: datetime, rng: random.Random
) -> List[str]:
    """
    DDoS botnet targeting Kenyan critical infrastructure (KPLC, Safaricom, Equity).
    """
    bot_ips = [f"ip:203.0.{rng.randint(100,150)}.{rng.randint(1,254)}" for i in range(22)]
    services = ["service_id:kplc", "service_id:safaricom", "service_id:equity-bank"]
    endpoints = ["endpoint:kplc:/login:POST", "endpoint:safaricom:/api/v1/auth:POST"]
    all_ents = bot_ips + services + endpoints

    _make_shared_events(db, family_entities=bot_ips + services, event_type="DDOS_SIGNAL_EVENT",
                        count=60, window_start=window_start, window_end=window_end, rng=rng, group_size=4)
    _make_shared_events(db, family_entities=bot_ips + endpoints, event_type="DDOS_SIGNAL_EVENT",
                        count=30, window_start=window_start, window_end=window_end, rng=rng, group_size=3)

    for ek in bot_ips:
        ddos = rng.randint(15, 80)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="ip",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=ddos, source_count=rng.randint(1, 3),
            degree=rng.randint(3, 8), weighted_degree=rng.randint(5, 25),
            risk_flags=["DDOS_CLUSTER_MEMBER"],
            event_types={"DDOS_SIGNAL_EVENT": ddos}, rng=rng,
        ))
    for ek in services:
        ddos = rng.randint(50, 200)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="service_id",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=ddos, source_count=rng.randint(10, 30),
            degree=rng.randint(15, 40), weighted_degree=rng.randint(20, 80),
            risk_flags=["DDOS_ALERT_SERVICE"],
            event_types={"DDOS_SIGNAL_EVENT": ddos, "SERVICE_HEALTH_EVENT": rng.randint(2, 10)}, rng=rng,
        ))
    for ek in endpoints:
        ddos = rng.randint(30, 120)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="endpoint",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=ddos, source_count=rng.randint(8, 25),
            degree=rng.randint(10, 30), weighted_degree=rng.randint(15, 60),
            risk_flags=["DDOS_ALERT_ENDPOINT", "DDOS_CLUSTER_MEMBER"],
            event_types={"DDOS_SIGNAL_EVENT": ddos}, rng=rng,
        ))

    log.info("family=ddos_botnet nodes=%d", len(all_ents))
    return all_ents


def _family_phishing_campaign(
    db, *, window_start: datetime, window_end: datetime, rng: random.Random
) -> List[str]:
    """
    SMS phishing campaign targeting Kenyan mobile users.
    """
    domains = [f"domain:sms-phish-ke-{i:02d}.com" for i in range(5)]
    urls = [f"url:http://sms-phish-ke-0{i}.com/claim" for i in range(3)]
    phones = [f"phone_h:ke_victim_{i:03d}" for i in range(15)]
    all_ents = domains + urls + phones

    _make_shared_events(db, family_entities=domains + phones, event_type="PHISHING_MESSAGE_EVENT",
                        count=35, window_start=window_start, window_end=window_end, rng=rng, group_size=3)
    _make_shared_events(db, family_entities=domains + urls, event_type="DNS_RESOLUTION_EVENT",
                        count=15, window_start=window_start, window_end=window_end, rng=rng, group_size=2)

    for ek in domains:
        phish = rng.randint(10, 40)
        dns = rng.randint(5, 20)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="domain",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=phish + dns, source_count=rng.randint(5, 15),
            degree=rng.randint(8, 25), weighted_degree=rng.randint(10, 40),
            risk_flags=["CAMPAIGN_ENTITY"],
            event_types={"PHISHING_MESSAGE_EVENT": phish, "DNS_RESOLUTION_EVENT": dns}, rng=rng,
        ))
    for ek in urls:
        phish = rng.randint(5, 20)
        dns = rng.randint(3, 12)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="url",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=phish + dns, source_count=rng.randint(3, 10),
            degree=rng.randint(4, 15), weighted_degree=rng.randint(5, 25),
            risk_flags=["CAMPAIGN_ENTITY"],
            event_types={"PHISHING_MESSAGE_EVENT": phish, "DNS_RESOLUTION_EVENT": dns}, rng=rng,
        ))
    for ek in phones:
        phish = rng.randint(1, 5)
        login = rng.randint(0, 2)
        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type="phone_h",
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=phish + login, source_count=rng.randint(1, 3),
            degree=rng.randint(1, 5), weighted_degree=rng.randint(1, 8),
            risk_flags=["CAMPAIGN_ENTITY"],
            event_types={"PHISHING_MESSAGE_EVENT": phish, "LOGIN_EVENT": login}, rng=rng,
        ))

    log.info("family=phishing_campaign nodes=%d", len(all_ents))
    return all_ents


def _benign_nodes(
    db,
    *,
    window_start: datetime,
    window_end: datetime,
    rng: random.Random,
    count: int,
    existing_keys: set,
) -> List[str]:
    """
    Clean/benign entities: low activity, no risk flags, only benign event types.
    These are the negative-class examples for training.
    """
    benign_event_types = ["LOGIN_EVENT", "SERVICE_HEALTH_EVENT", "DNS_RESOLUTION_EVENT", "DOMAIN_REG_EVENT"]
    etype_pool = ["ip", "domain", "account_h", "phone_h", "service_id", "device_id"]
    created: List[str] = []

    i = 0
    attempts = 0
    while len(created) < count and attempts < count * 5:
        attempts += 1
        etype = rng.choice(etype_pool)
        raw = f"benign_{etype}_{i:04d}"
        ek = f"{etype}:{raw}"
        if ek in existing_keys:
            i += 1
            continue

        event_count = rng.randint(1, 8)
        main_type = rng.choice(benign_event_types)

        _upsert_snapshot(db, _make_snapshot(
            entity_key=ek, entity_type=etype,
            window_key=WINDOW_KEY, window_start=window_start, window_end=window_end,
            event_count=event_count, source_count=rng.randint(1, 2),
            degree=rng.randint(0, 3), weighted_degree=rng.randint(0, 5),
            risk_flags=[],
            event_types={main_type: event_count}, rng=rng,
        ))
        created.append(ek)
        existing_keys.add(ek)
        i += 1

    log.info("benign_nodes count=%d", len(created))
    return created


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

def seed(
    *,
    window_hours: int = 4,
    benign_count: int = 150,
    seed_value: int = 42,
) -> Dict[str, int]:
    """
    Seed the database with synthetic GNN training data.
    Returns a summary dict with node/event counts.
    """
    rng = random.Random(seed_value)
    now = _utcnow().replace(microsecond=0)
    window_end = now
    window_start = now - timedelta(hours=window_hours)

    db = SessionLocal()
    try:
        # Ensure all AI tables exist
        from app.analytics.ai_models import (  # noqa: PLC0415
            GNNTrainingRun, AIPrediction, AIExplanation, GraphFeatureSnapshot as _GFS,
        )
        Base.metadata.create_all(bind=engine)

        _ensure_source(db)
        db.flush()

        all_positive: List[str] = []

        all_positive += _family_mule_network(
            db, window_start=window_start, window_end=window_end, rng=rng)
        all_positive += _family_sim_swap_cluster(
            db, window_start=window_start, window_end=window_end, rng=rng)
        all_positive += _family_vpn_fraud_ring(
            db, window_start=window_start, window_end=window_end, rng=rng)
        all_positive += _family_ddos_botnet(
            db, window_start=window_start, window_end=window_end, rng=rng)
        all_positive += _family_phishing_campaign(
            db, window_start=window_start, window_end=window_end, rng=rng)

        existing_keys = set(all_positive)
        _benign_nodes(
            db,
            window_start=window_start,
            window_end=window_end,
            rng=rng,
            count=benign_count,
            existing_keys=existing_keys,
        )

        db.commit()

        total_nodes = len(existing_keys)
        total_positive = len(all_positive)
        total_benign = total_nodes - total_positive

        log.info(
            "seed_complete total_nodes=%d positive=%d benign=%d "
            "window_key=%s window_start=%s window_end=%s",
            total_nodes, total_positive, total_benign,
            WINDOW_KEY, window_start.isoformat(), window_end.isoformat(),
        )
        return {
            "total_nodes": total_nodes,
            "positive_nodes": total_positive,
            "benign_nodes": total_benign,
            "window_key": WINDOW_KEY,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Seed synthetic GNN training data for Sentinel-KE")
    p.add_argument("--window-hours", type=int, default=4,
                   help="Window duration in hours (default: 4)")
    p.add_argument("--benign", type=int, default=150,
                   help="Number of benign (negative-class) nodes (default: 150)")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed for reproducibility (default: 42)")
    args = p.parse_args()

    result = seed(
        window_hours=args.window_hours,
        benign_count=args.benign,
        seed_value=args.seed,
    )
    print(json.dumps(result, indent=2))
    print("\nNext step: train the GNN on this data:")
    print("  python -m app.analytics.layer3.gnn_train_worker --window-key Wmid")


if __name__ == "__main__":
    main()
