"""
Sentinel-KE — Large-Scale GNN Seed (5,000+ nodes)
====================================================
Generates multiple independent "community batches" of cyber and corruption
entities, each batch using a unique run_id prefix so all entities are distinct.
All snapshots share the same window_end so load_dataset() sees every node.

Usage (inside backend container):
    python -m app.demo.seed_large_scale
    python -m app.demo.seed_large_scale --cyber-runs 10 --corruption-runs 8

After seeding, trigger retraining:
    POST /v1/ai/gnn/train  {"domain":"cyber","epochs":60,"model_version":"cyber-large-v1"}
    POST /v1/ai/gnn/train  {"domain":"corruption","epochs":60,"model_version":"corruption-large-v1"}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set

from sqlalchemy.dialects.postgresql import insert as pg_insert

import app.db.registry  # noqa: F401
from app.analytics.ai_models import GraphFeatureSnapshot
from app.ledger.db import SessionLocal, engine
from app.ledger.models import Base, EventEntityIndex, EventLog, SourceRegistry

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("sentinel.seed_large_scale")

CYBER_SOURCE_ID      = "synthetic-gnn-seed"
CORRUPTION_SOURCE_ID = "synthetic-corruption-seed"
CYBER_WINDOW_KEY     = "Wmid"
CORRUPTION_WINDOW_KEY = "Wcorruption"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _ehash(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return f"lsc:{h[:48]}"


def _ensure_source(db, source_id: str, source_type: str = "synthetic") -> None:
    stmt = pg_insert(SourceRegistry).values(
        source_id=source_id,
        source_type=source_type,
        classification_level="RESTRICTED",
        api_key_hash=hashlib.sha256(source_id.encode()).hexdigest(),
        is_active=True,
    ).on_conflict_do_nothing(index_elements=["source_id"])
    db.execute(stmt)
    db.flush()


def _insert_event(db, *, source_id: str, event_type: str, entity_keys: List[str],
                  occurred_at: datetime, idx: int = 0) -> None:
    h = _ehash(source_id, event_type, *sorted(entity_keys), occurred_at.isoformat(), str(idx))
    stmt = pg_insert(EventLog).values(
        event_hash=h, event_type=event_type, source_id=source_id,
        classification="RESTRICTED", occurred_at=occurred_at, received_at=occurred_at,
        anchors_json={ek.split(":")[0]: ek.split(":", 1)[1] for ek in entity_keys if ":" in ek},
        payload_json={},
    ).on_conflict_do_nothing(index_elements=["event_hash"])
    db.execute(stmt)
    for ek in entity_keys:
        stmt2 = pg_insert(EventEntityIndex).values(
            event_hash=h, entity_key=ek,
        ).on_conflict_do_nothing(index_elements=["event_hash", "entity_key"])
        db.execute(stmt2)


def _shared_events(db, *, source_id: str, entities: List[str], event_type: str,
                   count: int, window_start: datetime, window_end: datetime,
                   rng: random.Random, group_size: int = 3) -> None:
    span = max(1, int((window_end - window_start).total_seconds()))
    for i in range(count):
        participants = rng.sample(entities, min(group_size, len(entities)))
        ts = window_start + timedelta(seconds=rng.randint(0, span))
        _insert_event(db, source_id=source_id, event_type=event_type,
                      entity_keys=participants, occurred_at=ts, idx=i)


def _snap(*, entity_key: str, entity_type: str, window_key: str,
          window_start: datetime, window_end: datetime,
          event_count: int, degree: int, weighted_degree: int,
          risk_flags: List[str], features: dict, rng: random.Random) -> dict:
    age = rng.randint(30, 3600)
    return dict(
        id=uuid.uuid4(),
        entity_key=entity_key, entity_type=entity_type,
        window_key=window_key, window_start=window_start, window_end=window_end,
        degree=degree, weighted_degree=weighted_degree, event_count=event_count,
        first_seen=window_start + timedelta(seconds=rng.randint(0, 7200)),
        last_seen=window_end - timedelta(seconds=age),
        risk_flags=risk_flags, features=features,
    )


def _upsert(db, row: dict) -> None:
    stmt = pg_insert(GraphFeatureSnapshot).values(**row).on_conflict_do_update(
        index_elements=["entity_key", "window_key", "window_end"],
        set_={"risk_flags": row["risk_flags"], "features": row["features"],
              "event_count": row["event_count"], "degree": row["degree"],
              "weighted_degree": row["weighted_degree"]},
    )
    db.execute(stmt)


# ---------------------------------------------------------------------------
# CYBER family generators — each accepts a prefix for unique entity keys
# ---------------------------------------------------------------------------

def _cyber_mule_network(db, *, prefix: str, window_start: datetime, window_end: datetime,
                        rng: random.Random) -> List[str]:
    accounts = [f"account_h:{prefix}mule_{i:03d}" for i in range(20)]
    ips      = [f"ip:{prefix}{rng.randint(41,196)}.{rng.randint(1,254)}.{rng.randint(1,254)}.{rng.randint(1,254)}" for i in range(12)]
    phones   = [f"phone_h:{prefix}mule_phone_{i:02d}" for i in range(8)]
    all_e    = accounts + ips + phones
    _shared_events(db, source_id=CYBER_SOURCE_ID, entities=all_e,
                   event_type="TRANSACTION_EVENT", count=50,
                   window_start=window_start, window_end=window_end, rng=rng, group_size=3)
    _shared_events(db, source_id=CYBER_SOURCE_ID, entities=accounts + phones,
                   event_type="LOGIN_EVENT", count=20,
                   window_start=window_start, window_end=window_end, rng=rng, group_size=2)
    for ek in accounts:
        c = rng.randint(12, 45)
        _upsert(db, _snap(entity_key=ek, entity_type="account_h", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(4, 12), weighted_degree=rng.randint(8, 30),
                          risk_flags=["CAMPAIGN_ENTITY"],
                          features={"source_count": rng.randint(3, 8), "event_types": {"TRANSACTION_EVENT": c}},
                          rng=rng))
    for ek in ips:
        c = rng.randint(5, 25)
        _upsert(db, _snap(entity_key=ek, entity_type="ip", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(3, 10), weighted_degree=rng.randint(5, 20),
                          risk_flags=["CAMPAIGN_ENTITY"],
                          features={"source_count": rng.randint(2, 5), "event_types": {"TRANSACTION_EVENT": c}},
                          rng=rng))
    for ek in phones:
        c = rng.randint(3, 15)
        _upsert(db, _snap(entity_key=ek, entity_type="phone_h", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(2, 8), weighted_degree=rng.randint(3, 15),
                          risk_flags=["CAMPAIGN_ENTITY"],
                          features={"source_count": rng.randint(2, 5), "event_types": {"TRANSACTION_EVENT": c}},
                          rng=rng))
    return all_e


def _cyber_ddos_botnet(db, *, prefix: str, window_start: datetime, window_end: datetime,
                       rng: random.Random) -> List[str]:
    targets  = [f"service_id:{prefix}target_{t}" for t in ["kplc", "kra", "safaricom", "equity", "kcb"]]
    bots     = [f"ip:{prefix}bot_{rng.randint(100,254)}.{rng.randint(1,254)}.{rng.randint(1,254)}.{rng.randint(1,254)}" for i in range(30)]
    all_e    = targets + bots
    _shared_events(db, source_id=CYBER_SOURCE_ID, entities=all_e,
                   event_type="DDOS_SIGNAL_EVENT", count=80,
                   window_start=window_start, window_end=window_end, rng=rng, group_size=5)
    for ek in targets:
        c = rng.randint(50, 200)
        _upsert(db, _snap(entity_key=ek, entity_type="service_id", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(20, 50), weighted_degree=rng.randint(30, 80),
                          risk_flags=["DDOS_ALERT_SERVICE"],
                          features={"source_count": rng.randint(10, 30), "event_types": {"DDOS_SIGNAL_EVENT": c}},
                          rng=rng))
    for ek in bots:
        c = rng.randint(15, 80)
        _upsert(db, _snap(entity_key=ek, entity_type="ip", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(3, 8), weighted_degree=rng.randint(5, 25),
                          risk_flags=["DDOS_CLUSTER_MEMBER"],
                          features={"source_count": rng.randint(1, 3), "event_types": {"DDOS_SIGNAL_EVENT": c}},
                          rng=rng))
    return all_e


def _cyber_phishing(db, *, prefix: str, window_start: datetime, window_end: datetime,
                    rng: random.Random) -> List[str]:
    domains = [f"domain:{prefix}phish_{i:02d}.co.ke" for i in range(8)]
    phones  = [f"phone_h:{prefix}victim_{i:03d}" for i in range(20)]
    urls    = [f"url:{prefix}http-phish-{i:02d}" for i in range(4)]
    all_e   = domains + phones + urls
    _shared_events(db, source_id=CYBER_SOURCE_ID, entities=domains + phones,
                   event_type="PHISHING_MESSAGE_EVENT", count=40,
                   window_start=window_start, window_end=window_end, rng=rng, group_size=3)
    for ek in domains + urls:
        c = rng.randint(10, 40)
        _upsert(db, _snap(entity_key=ek, entity_type="domain", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(8, 25), weighted_degree=rng.randint(10, 40),
                          risk_flags=["CAMPAIGN_ENTITY"],
                          features={"source_count": rng.randint(5, 15), "event_types": {"PHISHING_MESSAGE_EVENT": c}},
                          rng=rng))
    for ek in phones:
        c = rng.randint(1, 5)
        _upsert(db, _snap(entity_key=ek, entity_type="phone_h", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(1, 5), weighted_degree=rng.randint(1, 8),
                          risk_flags=["CAMPAIGN_ENTITY"],
                          features={"source_count": rng.randint(1, 3), "event_types": {"PHISHING_MESSAGE_EVENT": c}},
                          rng=rng))
    return all_e


def _cyber_sim_swap(db, *, prefix: str, window_start: datetime, window_end: datetime,
                    rng: random.Random) -> List[str]:
    phones   = [f"phone_h:{prefix}sim_{i:03d}" for i in range(15)]
    accounts = [f"account_h:{prefix}simacct_{i:03d}" for i in range(10)]
    all_e    = phones + accounts
    _shared_events(db, source_id=CYBER_SOURCE_ID, entities=all_e,
                   event_type="SIM_SWAP_EVENT", count=25,
                   window_start=window_start, window_end=window_end, rng=rng, group_size=2)
    for ek in phones:
        c = rng.randint(2, 8)
        _upsert(db, _snap(entity_key=ek, entity_type="phone_h", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(2, 7), weighted_degree=rng.randint(3, 12),
                          risk_flags=["CAMPAIGN_ENTITY"],
                          features={"source_count": rng.randint(2, 4), "event_types": {"SIM_SWAP_EVENT": c}},
                          rng=rng))
    for ek in accounts:
        c = rng.randint(3, 12)
        _upsert(db, _snap(entity_key=ek, entity_type="account_h", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(2, 6), weighted_degree=rng.randint(2, 10),
                          risk_flags=["CAMPAIGN_ENTITY"],
                          features={"source_count": rng.randint(1, 4), "event_types": {"SIM_SWAP_EVENT": c}},
                          rng=rng))
    return all_e


def _cyber_airtime_siphon(db, *, prefix: str, window_start: datetime, window_end: datetime,
                          rng: random.Random) -> List[str]:
    victims   = [f"phone_h:{prefix}air_victim_{i:03d}" for i in range(15)]
    receivers = [f"account_h:{prefix}air_recv_{i:03d}" for i in range(10)]
    gateway   = [f"service_id:{prefix}air_gw"]
    all_e     = victims + receivers + gateway
    _shared_events(db, source_id=CYBER_SOURCE_ID, entities=victims + gateway,
                   event_type="AIRTIME_TRANSFER_EVENT", count=45,
                   window_start=window_start, window_end=window_end, rng=rng, group_size=3)
    for ek in victims:
        c = rng.randint(8, 30)
        _upsert(db, _snap(entity_key=ek, entity_type="phone_h", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(3, 8), weighted_degree=rng.randint(4, 15),
                          risk_flags=["AIRTIME_SIPHON_MEMBER"],
                          features={"source_count": rng.randint(2, 4), "event_types": {"AIRTIME_TRANSFER_EVENT": c}},
                          rng=rng))
    for ek in receivers:
        c = rng.randint(10, 35)
        _upsert(db, _snap(entity_key=ek, entity_type="account_h", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(5, 15), weighted_degree=rng.randint(8, 25),
                          risk_flags=["CAMPAIGN_ENTITY", "AIRTIME_SIPHON_MEMBER"],
                          features={"source_count": rng.randint(3, 7), "event_types": {"TRANSACTION_EVENT": c}},
                          rng=rng))
    for ek in gateway:
        c = rng.randint(50, 150)
        _upsert(db, _snap(entity_key=ek, entity_type="service_id", window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(20, 50), weighted_degree=rng.randint(30, 80),
                          risk_flags=["CAMPAIGN_ENTITY", "AIRTIME_SIPHON_MEMBER"],
                          features={"source_count": rng.randint(8, 20), "event_types": {"AIRTIME_TRANSFER_EVENT": c}},
                          rng=rng))
    return all_e


def _cyber_benign(db, *, prefix: str, window_start: datetime, window_end: datetime,
                  rng: random.Random, count: int, existing: Set[str]) -> List[str]:
    etypes  = ["ip", "domain", "account_h", "phone_h", "service_id"]
    evtypes = ["LOGIN_EVENT", "SERVICE_HEALTH_EVENT", "DNS_RESOLUTION_EVENT"]
    created: List[str] = []
    i = 0
    while len(created) < count:
        et  = rng.choice(etypes)
        ek  = f"{et}:{prefix}benign_{i:04d}"
        i  += 1
        if ek in existing:
            continue
        c = rng.randint(1, 8)
        _upsert(db, _snap(entity_key=ek, entity_type=et, window_key=CYBER_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=c, degree=rng.randint(0, 3), weighted_degree=rng.randint(0, 5),
                          risk_flags=[],
                          features={"source_count": 1, "event_types": {rng.choice(evtypes): c}},
                          rng=rng))
        created.append(ek)
        existing.add(ek)
    return created


# ---------------------------------------------------------------------------
# CORRUPTION family generators
# ---------------------------------------------------------------------------

def _corr_tender_cartel(db, *, prefix: str, window_start: datetime, window_end: datetime,
                        rng: random.Random) -> List[str]:
    companies = [f"company:{prefix}cartel_co_{i:02d}" for i in range(5)]
    directors = [f"director:{prefix}cartel_dir_{i:02d}" for i in range(4)]
    tenders   = [f"tender:{prefix}cartel_tend_{i:02d}" for i in range(6)]
    official  = [f"official:{prefix}cartel_off"]
    all_e     = companies + directors + tenders + official
    _shared_events(db, source_id=CORRUPTION_SOURCE_ID, entities=companies + tenders,
                   event_type="TENDER_AWARD", count=25,
                   window_start=window_start, window_end=window_end, rng=rng, group_size=3)
    _shared_events(db, source_id=CORRUPTION_SOURCE_ID, entities=all_e,
                   event_type="PAYMENT_DISBURSEMENT", count=30,
                   window_start=window_start, window_end=window_end, rng=rng, group_size=3)
    for ek in companies:
        val = rng.uniform(5e6, 80e6)
        _upsert(db, _snap(entity_key=ek, entity_type="company", window_key=CORRUPTION_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=rng.randint(15, 40), degree=rng.randint(5, 12), weighted_degree=rng.randint(10, 25),
                          risk_flags=["DIRECTOR_CONFLICT", "PRICE_INFLATION"],
                          features={"transaction_count": rng.randint(15, 40), "total_value_ksh": val,
                                    "counterparty_count": rng.randint(3, 8), "related_party_ratio": rng.uniform(0.6, 0.95),
                                    "corruption_events": {"TENDER_AWARD": rng.randint(3, 8)},
                                    "fy_end_event_fraction": 0.0, "amendment_ratio": rng.uniform(0.2, 0.5),
                                    "execution_rate": rng.uniform(0.3, 0.7), "concentration_ratio": rng.uniform(0.5, 0.9),
                                    "threshold_splitting": 0.0, "single_source": True,
                                    "last_seen_age_sec": rng.randint(60, 3600)},
                          rng=rng))
    for ek in directors + tenders + official:
        _upsert(db, _snap(entity_key=ek, entity_type=ek.split(":")[0], window_key=CORRUPTION_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=rng.randint(5, 20), degree=rng.randint(2, 8), weighted_degree=rng.randint(3, 12),
                          risk_flags=["DIRECTOR_CONFLICT", "AUDIT_FINDING"],
                          features={"transaction_count": rng.randint(5, 20), "total_value_ksh": rng.uniform(1e6, 20e6),
                                    "counterparty_count": rng.randint(2, 6), "related_party_ratio": rng.uniform(0.4, 0.9),
                                    "corruption_events": {"TENDER_AWARD": rng.randint(1, 4)},
                                    "fy_end_event_fraction": 0.0, "amendment_ratio": 0.0,
                                    "execution_rate": rng.uniform(0.5, 1.0), "concentration_ratio": 0.0,
                                    "threshold_splitting": 0.0, "single_source": False,
                                    "last_seen_age_sec": rng.randint(60, 3600)},
                          rng=rng))
    return all_e


def _corr_ghost_workers(db, *, prefix: str, window_start: datetime, window_end: datetime,
                        rng: random.Random) -> List[str]:
    dept     = [f"department:{prefix}ghost_dept"]
    accounts = [f"account:{prefix}ghost_{i:03d}" for i in range(25)]
    official = [f"official:{prefix}ghost_off_{i:02d}" for i in range(2)]
    all_e    = dept + accounts + official
    _shared_events(db, source_id=CORRUPTION_SOURCE_ID, entities=dept + accounts,
                   event_type="PAYMENT_DISBURSEMENT", count=60,
                   window_start=window_start, window_end=window_end, rng=rng, group_size=4)
    for ek in accounts:
        val = rng.uniform(50_000, 500_000)
        _upsert(db, _snap(entity_key=ek, entity_type="account", window_key=CORRUPTION_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=rng.randint(3, 12), degree=rng.randint(1, 4), weighted_degree=rng.randint(2, 8),
                          risk_flags=["GHOST_WORKER"],
                          features={"transaction_count": rng.randint(3, 12), "total_value_ksh": val,
                                    "counterparty_count": 1, "related_party_ratio": 0.0,
                                    "corruption_events": {"PAYMENT_DISBURSEMENT": rng.randint(3, 10)},
                                    "fy_end_event_fraction": 0.0, "amendment_ratio": 0.0,
                                    "execution_rate": 1.0, "concentration_ratio": 1.0,
                                    "threshold_splitting": 0.0, "single_source": False,
                                    "last_seen_age_sec": rng.randint(60, 3600)},
                          rng=rng))
    for ek in dept + official:
        _upsert(db, _snap(entity_key=ek, entity_type=ek.split(":")[0], window_key=CORRUPTION_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=rng.randint(30, 80), degree=rng.randint(15, 30), weighted_degree=rng.randint(20, 50),
                          risk_flags=["GHOST_WORKER", "AUDIT_FINDING"],
                          features={"transaction_count": rng.randint(30, 80), "total_value_ksh": rng.uniform(50e6, 200e6),
                                    "counterparty_count": rng.randint(15, 25), "related_party_ratio": 0.0,
                                    "corruption_events": {"PAYMENT_DISBURSEMENT": rng.randint(30, 60),
                                                          "AUDIT_FINDING_EVENT": rng.randint(2, 5)},
                                    "fy_end_event_fraction": 0.0, "amendment_ratio": 0.0,
                                    "execution_rate": 1.0, "concentration_ratio": rng.uniform(0.05, 0.2),
                                    "threshold_splitting": 0.0, "single_source": False,
                                    "last_seen_age_sec": rng.randint(60, 3600)},
                          rng=rng))
    return all_e


def _corr_shell_network(db, *, prefix: str, window_start: datetime, window_end: datetime,
                        rng: random.Random) -> List[str]:
    official  = [f"official:{prefix}shell_off"]
    companies = [f"company:{prefix}shell_co_{i:02d}" for i in range(6)]
    contracts = [f"contract:{prefix}shell_ct_{i:02d}" for i in range(7)]
    all_e     = official + companies + contracts
    _shared_events(db, source_id=CORRUPTION_SOURCE_ID, entities=companies + contracts,
                   event_type="TENDER_AWARD", count=15,
                   window_start=window_start, window_end=window_end, rng=rng, group_size=2)
    for ek in companies:
        val = rng.uniform(5e6, 50e6)
        _upsert(db, _snap(entity_key=ek, entity_type="company", window_key=CORRUPTION_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=rng.randint(5, 15), degree=rng.randint(2, 6), weighted_degree=rng.randint(3, 10),
                          risk_flags=["SHELL_COMPANY", "DIRECTOR_CONFLICT"],
                          features={"transaction_count": rng.randint(5, 15), "total_value_ksh": val,
                                    "counterparty_count": rng.randint(1, 3), "related_party_ratio": rng.uniform(0.9, 1.0),
                                    "corruption_events": {"TENDER_AWARD": rng.randint(1, 4)},
                                    "fy_end_event_fraction": 0.0, "amendment_ratio": 0.0,
                                    "execution_rate": rng.uniform(0.1, 0.4), "concentration_ratio": rng.uniform(0.7, 1.0),
                                    "threshold_splitting": 0.0, "single_source": True,
                                    "last_seen_age_sec": rng.randint(60, 3600)},
                          rng=rng))
    for ek in official + contracts:
        _upsert(db, _snap(entity_key=ek, entity_type=ek.split(":")[0], window_key=CORRUPTION_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=rng.randint(5, 20), degree=rng.randint(3, 10), weighted_degree=rng.randint(5, 15),
                          risk_flags=["SHELL_COMPANY", "AUDIT_FINDING"],
                          features={"transaction_count": rng.randint(5, 20), "total_value_ksh": rng.uniform(2e6, 30e6),
                                    "counterparty_count": rng.randint(2, 8), "related_party_ratio": rng.uniform(0.7, 1.0),
                                    "corruption_events": {"TENDER_AWARD": rng.randint(2, 6)},
                                    "fy_end_event_fraction": 0.0, "amendment_ratio": rng.uniform(0.3, 0.7),
                                    "execution_rate": rng.uniform(0.1, 0.5), "concentration_ratio": 0.0,
                                    "threshold_splitting": 0.0, "single_source": False,
                                    "last_seen_age_sec": rng.randint(60, 3600)},
                          rng=rng))
    return all_e


def _corr_benign(db, *, prefix: str, window_start: datetime, window_end: datetime,
                 rng: random.Random, count: int, existing: Set[str]) -> List[str]:
    etypes = ["official", "company", "contract", "payment", "department", "supplier"]
    created: List[str] = []
    i = 0
    while len(created) < count:
        et = rng.choice(etypes)
        ek = f"{et}:{prefix}clean_{i:04d}"
        i += 1
        if ek in existing:
            continue
        val = rng.uniform(100_000, 5e6)
        _upsert(db, _snap(entity_key=ek, entity_type=et, window_key=CORRUPTION_WINDOW_KEY,
                          window_start=window_start, window_end=window_end,
                          event_count=rng.randint(1, 10), degree=rng.randint(1, 4), weighted_degree=rng.randint(1, 6),
                          risk_flags=[],
                          features={"transaction_count": rng.randint(1, 10), "total_value_ksh": val,
                                    "counterparty_count": rng.randint(1, 3), "related_party_ratio": rng.uniform(0.0, 0.1),
                                    "corruption_events": {"PAYMENT_DISBURSEMENT": rng.randint(1, 8)},
                                    "fy_end_event_fraction": rng.uniform(0.0, 0.15), "amendment_ratio": 0.0,
                                    "execution_rate": rng.uniform(0.8, 1.0), "concentration_ratio": 0.0,
                                    "threshold_splitting": 0.0, "single_source": False,
                                    "last_seen_age_sec": rng.randint(60, 3600)},
                          rng=rng))
        created.append(ek)
        existing.add(ek)
    return created


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

def seed_cyber(*, n_runs: int = 10, benign_per_run: int = 100,
               base_seed: int = 100) -> Dict:
    """Seed n_runs × 5 cyber families into CYBER_WINDOW_KEY. Returns summary."""
    Base.metadata.create_all(bind=engine)
    window_end   = _utcnow()
    window_start = window_end - timedelta(hours=6)

    db = SessionLocal()
    try:
        _ensure_source(db, CYBER_SOURCE_ID)
        db.flush()

        all_positive: List[str] = []
        all_entities: Set[str]  = set()

        for run in range(n_runs):
            prefix = f"r{run:02d}_"
            rng    = random.Random(base_seed + run)
            log.info("cyber run=%d prefix=%s", run, prefix)

            batch: List[str] = []
            batch += _cyber_mule_network(db, prefix=prefix, window_start=window_start,
                                         window_end=window_end, rng=rng)
            batch += _cyber_ddos_botnet(db, prefix=prefix, window_start=window_start,
                                        window_end=window_end, rng=rng)
            batch += _cyber_phishing(db, prefix=prefix, window_start=window_start,
                                     window_end=window_end, rng=rng)
            batch += _cyber_sim_swap(db, prefix=prefix, window_start=window_start,
                                     window_end=window_end, rng=rng)
            batch += _cyber_airtime_siphon(db, prefix=prefix, window_start=window_start,
                                           window_end=window_end, rng=rng)

            all_entities.update(batch)
            all_positive.extend(batch)

            _cyber_benign(db, prefix=prefix, window_start=window_start, window_end=window_end,
                          rng=rng, count=benign_per_run, existing=all_entities)

        db.commit()

        total    = len(all_entities)
        positive = len(all_positive)
        log.info("cyber_seed_complete runs=%d total=%d positive=%d benign=%d window_key=%s",
                 n_runs, total, positive, total - positive, CYBER_WINDOW_KEY)
        return {"domain": "cyber", "runs": n_runs, "total_nodes": total,
                "positive_nodes": positive, "benign_nodes": total - positive,
                "window_key": CYBER_WINDOW_KEY, "window_end": window_end.isoformat()}

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def seed_corruption(*, n_runs: int = 10, benign_per_run: int = 100,
                    base_seed: int = 200) -> Dict:
    """Seed n_runs × 3 corruption families into CORRUPTION_WINDOW_KEY."""
    Base.metadata.create_all(bind=engine)
    window_end   = _utcnow()
    window_start = window_end - timedelta(hours=720)

    db = SessionLocal()
    try:
        _ensure_source(db, CORRUPTION_SOURCE_ID)
        db.flush()

        all_positive: List[str] = []
        all_entities: Set[str]  = set()

        for run in range(n_runs):
            prefix = f"r{run:02d}_"
            rng    = random.Random(base_seed + run)
            log.info("corruption run=%d prefix=%s", run, prefix)

            batch: List[str] = []
            batch += _corr_tender_cartel(db, prefix=prefix, window_start=window_start,
                                         window_end=window_end, rng=rng)
            batch += _corr_ghost_workers(db, prefix=prefix, window_start=window_start,
                                         window_end=window_end, rng=rng)
            batch += _corr_shell_network(db, prefix=prefix, window_start=window_start,
                                         window_end=window_end, rng=rng)

            all_entities.update(batch)
            all_positive.extend(batch)

            _corr_benign(db, prefix=prefix, window_start=window_start, window_end=window_end,
                         rng=rng, count=benign_per_run, existing=all_entities)

        db.commit()

        total    = len(all_entities)
        positive = len(all_positive)
        log.info("corruption_seed_complete runs=%d total=%d positive=%d benign=%d window_key=%s",
                 n_runs, total, positive, total - positive, CORRUPTION_WINDOW_KEY)
        return {"domain": "corruption", "runs": n_runs, "total_nodes": total,
                "positive_nodes": positive, "benign_nodes": total - positive,
                "window_key": CORRUPTION_WINDOW_KEY, "window_end": window_end.isoformat()}

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Seed large-scale GNN training data")
    p.add_argument("--cyber-runs",       type=int, default=10,
                   help="Number of cyber community batches (default 10 → ~4,000 nodes)")
    p.add_argument("--corruption-runs",  type=int, default=10,
                   help="Number of corruption community batches (default 10 → ~3,500 nodes)")
    p.add_argument("--benign-per-run",   type=int, default=100,
                   help="Benign nodes added per run (default 100)")
    p.add_argument("--domain",           choices=["cyber", "corruption", "both"], default="both")
    p.add_argument("--base-seed",        type=int, default=100)
    args = p.parse_args()

    results = {}
    if args.domain in ("cyber", "both"):
        results["cyber"] = seed_cyber(
            n_runs=args.cyber_runs,
            benign_per_run=args.benign_per_run,
            base_seed=args.base_seed,
        )
        print("\nCyber result:")
        print(json.dumps(results["cyber"], indent=2))

    if args.domain in ("corruption", "both"):
        results["corruption"] = seed_corruption(
            n_runs=args.corruption_runs,
            benign_per_run=args.benign_per_run,
            base_seed=args.base_seed + 100,
        )
        print("\nCorruption result:")
        print(json.dumps(results["corruption"], indent=2))

    print("\n✓ Large-scale seed complete. Now retrain:")
    print('  POST /v1/ai/gnn/train  {"domain":"cyber","epochs":60,"model_version":"cyber-large-v1"}')
    print('  POST /v1/ai/gnn/train  {"domain":"corruption","epochs":60,"model_version":"corruption-large-v1"}')


if __name__ == "__main__":
    main()
