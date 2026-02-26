"""
Sentinel-KE — Synthetic Corruption GNN Training Data Generator
==============================================================

Seeds the database with realistic Kenyan public-sector corruption
patterns so the corruption GNN can be trained without waiting for
real government data ingestion.

Five fraud families modelled on documented Kenyan cases
-------------------------------------------------------
1. Tender Cartel          — companies colluding on procurement (PPRA pattern)
2. Ghost Workers Network  — payroll fraud (county govt pattern)
3. Inflated Procurement   — contracts at 3-5× market rate (KEMSA-type)
4. Shell Company Network  — officials owning shell companies via relatives
5. Budget Absorption Fraud — end-of-FY spending surge (IFMIS audit pattern)

Data inserted
-------------
  source_registry        — one synthetic corruption source
  event_log              — shared events that create co-occurrence edges
  event_entity_index     — entity ↔ event mapping
  graph_feature_snapshot — per-entity 42-dim feature vectors
                           (window_key = "Wcorruption")

Usage
-----
    python -m app.demo.synthetic_corruption_data
    python -m app.demo.synthetic_corruption_data --benign 200 --seed 99

After seeding, train the corruption GNN:
    python -m app.analytics.corruption.train_worker --window-key Wcorruption
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from sqlalchemy.dialects.postgresql import insert as pg_insert

import app.db.registry  # noqa: F401
from app.analytics.ai_models import GraphFeatureSnapshot
from app.analytics.corruption.feature_builder import CORRUPTION_WINDOW_KEY
from app.ledger.db import SessionLocal, engine
from app.ledger.models import Base, EventEntityIndex, EventLog, SourceRegistry

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("sentinel.synthetic_corruption")

SYNTH_SOURCE_ID     = "synthetic-corruption-seed"
CLASSIFICATION      = "RESTRICTED"
# Kenya financial year ends 30 June — May/June are the surge months
KE_FY_END_MONTHS    = {5, 6}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event_hash(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return f"corr:{h[:48]}"


def _ensure_source(db) -> None:
    stmt = pg_insert(SourceRegistry).values(
        source_id=SYNTH_SOURCE_ID,
        source_type="synthetic",
        classification_level=CLASSIFICATION,
        api_key_hash=hashlib.sha256(b"synthetic-corruption-key").hexdigest(),
        is_active=True,
    ).on_conflict_do_nothing(index_elements=["source_id"])
    db.execute(stmt)
    db.flush()


def _insert_shared_event(
    db,
    *,
    event_type: str,
    entity_keys: List[str],
    occurred_at: datetime,
    payload: Optional[Dict] = None,
    idx: int = 0,
) -> str:
    h = _event_hash(event_type, *sorted(entity_keys), occurred_at.isoformat(), str(idx))
    stmt = pg_insert(EventLog).values(
        event_hash   = h,
        event_type   = event_type,
        source_id    = SYNTH_SOURCE_ID,
        classification = CLASSIFICATION,
        occurred_at  = occurred_at,
        received_at  = occurred_at,
        anchors_json = {ek.split(":")[0]: ek.split(":", 1)[1] for ek in entity_keys if ":" in ek},
        payload_json = payload or {},
    ).on_conflict_do_nothing(index_elements=["event_hash"])
    db.execute(stmt)
    for ek in entity_keys:
        stmt2 = pg_insert(EventEntityIndex).values(
            event_hash=h, entity_key=ek,
        ).on_conflict_do_nothing(index_elements=["event_hash", "entity_key"])
        db.execute(stmt2)
    return h


def _shared_events(
    db, *, entities: List[str], event_type: str, count: int,
    window_start: datetime, window_end: datetime,
    rng: random.Random, group_size: int = 3,
) -> None:
    span = max(1, int((window_end - window_start).total_seconds()))
    for i in range(count):
        participants = rng.sample(entities, min(group_size, len(entities)))
        ts = window_start + timedelta(seconds=rng.randint(0, span))
        _insert_shared_event(db, event_type=event_type, entity_keys=participants,
                             occurred_at=ts, idx=i)


def _upsert_snapshot(db, row: dict) -> None:
    stmt = pg_insert(GraphFeatureSnapshot).values(**row).on_conflict_do_update(
        index_elements=["entity_key", "window_key", "window_end"],
        set_={"risk_flags": row["risk_flags"], "features": row["features"],
              "event_count": row["event_count"], "degree": row["degree"],
              "weighted_degree": row["weighted_degree"]},
    )
    db.execute(stmt)


def _snap(
    *,
    entity_key: str,
    entity_type: str,
    window_start: datetime,
    window_end: datetime,
    event_count: int,
    degree: int,
    risk_flags: List[str],
    corruption_events: Dict[str, int],
    total_value_ksh: float,
    counterparty_count: int,
    related_party_ratio: float = 0.0,
    amendment_ratio: float = 0.0,
    execution_rate: float = 1.0,
    concentration_ratio: float = 0.0,
    threshold_splitting: float = 0.0,
    fy_end_event_fraction: float = 0.0,
    single_source: bool = False,
    rng: random.Random = None,
) -> dict:
    age_sec   = rng.randint(60, 3600) if rng else 300
    last_seen = window_end - timedelta(seconds=age_sec)
    first_seen = window_start + timedelta(seconds=(rng.randint(0, 7200) if rng else 0))
    return dict(
        id             = uuid.uuid4(),
        entity_key     = entity_key,
        entity_type    = entity_type,
        window_key     = CORRUPTION_WINDOW_KEY,
        window_start   = window_start,
        window_end     = window_end,
        degree         = degree,
        weighted_degree = max(degree, int(event_count * 0.6)),
        event_count    = event_count,
        first_seen     = first_seen,
        last_seen      = last_seen,
        risk_flags     = risk_flags,
        features       = {
            "transaction_count":     event_count,
            "counterparty_count":    counterparty_count,
            "total_value_ksh":       total_value_ksh,
            "corruption_events":     corruption_events,
            "last_seen_age_sec":     age_sec,
            "fy_end_event_fraction": fy_end_event_fraction,
            "related_party_ratio":   related_party_ratio,
            "amendment_ratio":       amendment_ratio,
            "execution_rate":        execution_rate,
            "concentration_ratio":   concentration_ratio,
            "threshold_splitting":   threshold_splitting,
            "single_source":         single_source,
        },
    )


# ---------------------------------------------------------------------------
# Family 1 — Tender Cartel (PPRA-pattern)
# ---------------------------------------------------------------------------

def _family_tender_cartel(
    db, *, window_start: datetime, window_end: datetime, rng: random.Random,
) -> List[str]:
    """
    Three companies controlled by the same director network collude on tenders.
    All bids within 1–3% of each other (coordination signal).
    """
    companies = [f"company:cartel_co_{i:02d}_ltd" for i in range(4)]
    directors = [f"director:cartel_dir_{i:02d}" for i in range(3)]
    tenders   = [f"tender:ke_tender_cartel_{i:02d}" for i in range(5)]
    official  = ["official:ke_official_cartel_01"]
    all_ents  = companies + directors + tenders + official

    _shared_events(db, entities=companies + tenders, event_type="TENDER_AWARD",
                   count=20, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=3)
    _shared_events(db, entities=companies + directors, event_type="DIRECTOR_CHANGE",
                   count=8, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=3)
    _shared_events(db, entities=all_ents, event_type="PAYMENT_DISBURSEMENT",
                   count=25, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=3)

    for ek in companies:
        val = rng.uniform(5e6, 80e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="company",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(15, 40), degree=rng.randint(5, 12),
            risk_flags=["DIRECTOR_CONFLICT", "PRICE_INFLATION"],
            corruption_events={"TENDER_AWARD": rng.randint(3, 8),
                               "PAYMENT_DISBURSEMENT": rng.randint(5, 15),
                               "DIRECTOR_CHANGE": rng.randint(1, 3)},
            total_value_ksh=val, counterparty_count=rng.randint(3, 8),
            related_party_ratio=rng.uniform(0.6, 0.95),
            amendment_ratio=rng.uniform(0.2, 0.5), execution_rate=rng.uniform(0.3, 0.7),
            concentration_ratio=rng.uniform(0.5, 0.9), single_source=True, rng=rng,
        ))
    for ek in directors:
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="director",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(5, 15), degree=rng.randint(3, 8),
            risk_flags=["DIRECTOR_CONFLICT"],
            corruption_events={"DIRECTOR_CHANGE": rng.randint(2, 5),
                               "TENDER_AWARD": rng.randint(1, 4)},
            total_value_ksh=0.0, counterparty_count=rng.randint(2, 5), rng=rng,
        ))
    for ek in tenders:
        val = rng.uniform(10e6, 100e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="tender",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(3, 10), degree=rng.randint(2, 6),
            risk_flags=["PRICE_INFLATION", "AUDIT_FINDING"],
            corruption_events={"TENDER_AWARD": rng.randint(1, 3),
                               "TENDER_AMENDMENT": rng.randint(1, 4),
                               "SINGLE_SOURCE_AWARD": rng.randint(0, 2)},
            total_value_ksh=val, counterparty_count=rng.randint(1, 3),
            amendment_ratio=rng.uniform(0.3, 0.8), single_source=True, rng=rng,
        ))
    for ek in official:
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="official",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(10, 25), degree=rng.randint(5, 12),
            risk_flags=["DIRECTOR_CONFLICT", "AUDIT_FINDING"],
            corruption_events={"TENDER_AWARD": rng.randint(3, 8),
                               "WEALTH_DECLARATION": rng.randint(0, 2),
                               "AUDIT_FINDING_EVENT": rng.randint(1, 3)},
            total_value_ksh=rng.uniform(1e6, 10e6),
            counterparty_count=rng.randint(4, 10),
            related_party_ratio=rng.uniform(0.5, 0.9), rng=rng,
        ))

    log.info("family=tender_cartel nodes=%d", len(all_ents))
    return all_ents


# ---------------------------------------------------------------------------
# Family 2 — Ghost Workers Network
# ---------------------------------------------------------------------------

def _family_ghost_workers(
    db, *, window_start: datetime, window_end: datetime, rng: random.Random,
) -> List[str]:
    """
    Payroll payments to non-existent employees, common in county governments.
    """
    dept     = ["department:ke_county_dept_ghost"]
    accounts = [f"account:ghost_acct_{i:03d}" for i in range(20)]
    official = [f"official:ke_payroll_official_{i:02d}" for i in range(2)]
    all_ents = dept + accounts + official

    _shared_events(db, entities=dept + accounts, event_type="PAYMENT_DISBURSEMENT",
                   count=50, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=4)
    _shared_events(db, entities=dept + official, event_type="AUDIT_FINDING_EVENT",
                   count=5, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=2)

    for ek in dept:
        val = rng.uniform(50e6, 200e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="department",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(40, 80), degree=rng.randint(15, 30),
            risk_flags=["GHOST_WORKER", "AUDIT_FINDING"],
            corruption_events={"PAYMENT_DISBURSEMENT": rng.randint(30, 60),
                               "AUDIT_FINDING_EVENT": rng.randint(2, 5)},
            total_value_ksh=val, counterparty_count=rng.randint(15, 25),
            concentration_ratio=rng.uniform(0.05, 0.2), rng=rng,
        ))
    for ek in accounts:
        val = rng.uniform(50_000, 500_000)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="account",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(3, 12), degree=rng.randint(1, 4),
            risk_flags=["GHOST_WORKER"],
            corruption_events={"PAYMENT_DISBURSEMENT": rng.randint(3, 10)},
            total_value_ksh=val, counterparty_count=1,
            concentration_ratio=1.0, rng=rng,
        ))
    for ek in official:
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="official",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(5, 15), degree=rng.randint(3, 8),
            risk_flags=["GHOST_WORKER", "AUDIT_FINDING"],
            corruption_events={"PAYMENT_DISBURSEMENT": rng.randint(5, 15),
                               "AUDIT_FINDING_EVENT": rng.randint(1, 3)},
            total_value_ksh=rng.uniform(2e6, 8e6),
            counterparty_count=rng.randint(5, 15), rng=rng,
        ))

    log.info("family=ghost_workers nodes=%d", len(all_ents))
    return all_ents


# ---------------------------------------------------------------------------
# Family 3 — Inflated Procurement (KEMSA-type)
# ---------------------------------------------------------------------------

def _family_inflated_procurement(
    db, *, window_start: datetime, window_end: datetime, rng: random.Random,
) -> List[str]:
    """
    Contracts awarded at 3–5× market rate to politically connected suppliers.
    """
    suppliers  = [f"supplier:inflated_supplier_{i:02d}" for i in range(3)]
    contracts  = [f"contract:inflated_contract_{i:02d}" for i in range(4)]
    officials  = [f"official:ke_official_inflated_{i:02d}" for i in range(2)]
    payments   = [f"payment:inflated_pay_{i:02d}" for i in range(10)]
    all_ents   = suppliers + contracts + officials + payments

    _shared_events(db, entities=suppliers + contracts, event_type="SINGLE_SOURCE_AWARD",
                   count=10, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=2)
    _shared_events(db, entities=contracts + payments, event_type="ADVANCE_PAYMENT",
                   count=15, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=3)
    _shared_events(db, entities=all_ents, event_type="PAYMENT_DISBURSEMENT",
                   count=30, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=4)
    _shared_events(db, entities=suppliers + officials, event_type="AUDIT_FINDING_EVENT",
                   count=6, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=2)

    for ek in suppliers:
        val = rng.uniform(100e6, 500e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="supplier",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(20, 50), degree=rng.randint(5, 15),
            risk_flags=["PRICE_INFLATION", "AUDIT_FINDING", "RELATED_PARTY_TRANSACTION"],
            corruption_events={"SINGLE_SOURCE_AWARD": rng.randint(2, 5),
                               "PAYMENT_DISBURSEMENT": rng.randint(8, 20),
                               "ADVANCE_PAYMENT": rng.randint(3, 8),
                               "AUDIT_FINDING_EVENT": rng.randint(1, 3)},
            total_value_ksh=val, counterparty_count=rng.randint(2, 5),
            related_party_ratio=rng.uniform(0.7, 1.0), execution_rate=rng.uniform(0.1, 0.4),
            single_source=True, rng=rng,
        ))
    for ek in contracts:
        val = rng.uniform(50e6, 300e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="contract",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(8, 20), degree=rng.randint(3, 8),
            risk_flags=["PRICE_INFLATION", "AUDIT_FINDING"],
            corruption_events={"SINGLE_SOURCE_AWARD": 1,
                               "TENDER_AMENDMENT": rng.randint(2, 6),
                               "ADVANCE_PAYMENT": rng.randint(1, 4)},
            total_value_ksh=val, counterparty_count=rng.randint(1, 3),
            amendment_ratio=rng.uniform(0.4, 1.2), execution_rate=rng.uniform(0.1, 0.5),
            single_source=True, rng=rng,
        ))
    for ek in officials:
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="official",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(10, 25), degree=rng.randint(5, 12),
            risk_flags=["RELATED_PARTY_TRANSACTION", "AUDIT_FINDING"],
            corruption_events={"TENDER_AWARD": rng.randint(2, 6),
                               "SINGLE_SOURCE_AWARD": rng.randint(1, 3),
                               "AUDIT_FINDING_EVENT": rng.randint(1, 2),
                               "WEALTH_DECLARATION": 1},
            total_value_ksh=rng.uniform(5e6, 30e6),
            counterparty_count=rng.randint(2, 6),
            related_party_ratio=rng.uniform(0.6, 0.9), rng=rng,
        ))
    for ek in payments:
        val = rng.uniform(1e6, 30e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="payment",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(1, 5), degree=rng.randint(1, 3),
            risk_flags=["PRICE_INFLATION"],
            corruption_events={"PAYMENT_DISBURSEMENT": rng.randint(1, 4),
                               "ADVANCE_PAYMENT": rng.randint(0, 2)},
            total_value_ksh=val, counterparty_count=1,
            concentration_ratio=1.0,
            threshold_splitting=rng.uniform(0.0, 0.4), rng=rng,
        ))

    log.info("family=inflated_procurement nodes=%d", len(all_ents))
    return all_ents


# ---------------------------------------------------------------------------
# Family 4 — Shell Company Network
# ---------------------------------------------------------------------------

def _family_shell_network(
    db, *, window_start: datetime, window_end: datetime, rng: random.Random,
) -> List[str]:
    """
    Senior official owns 5 shell companies through relatives.
    Companies registered just before contracts were awarded.
    """
    official  = ["official:ke_senior_official_shell"]
    companies = [f"company:shell_co_{i:02d}_ltd" for i in range(5)]
    directors = [f"director:shell_dir_{i:02d}" for i in range(3)]  # relatives
    contracts = [f"contract:shell_contract_{i:02d}" for i in range(6)]
    all_ents  = official + companies + directors + contracts

    _shared_events(db, entities=companies + directors, event_type="COMPANY_REGISTRATION",
                   count=10, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=2)
    _shared_events(db, entities=companies + contracts, event_type="TENDER_AWARD",
                   count=15, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=2)
    _shared_events(db, entities=official + companies, event_type="PAYMENT_DISBURSEMENT",
                   count=20, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=3)

    for ek in official:
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="official",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(15, 30), degree=rng.randint(8, 18),
            risk_flags=["SHELL_COMPANY", "DIRECTOR_CONFLICT", "RELATED_PARTY_TRANSACTION"],
            corruption_events={"TENDER_AWARD": rng.randint(4, 10),
                               "PAYMENT_DISBURSEMENT": rng.randint(5, 15),
                               "WEALTH_DECLARATION": 1,
                               "AUDIT_FINDING_EVENT": rng.randint(1, 3)},
            total_value_ksh=rng.uniform(10e6, 60e6),
            counterparty_count=rng.randint(5, 12),
            related_party_ratio=rng.uniform(0.8, 1.0), rng=rng,
        ))
    for ek in companies:
        val = rng.uniform(5e6, 50e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="company",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(5, 15), degree=rng.randint(2, 6),
            risk_flags=["SHELL_COMPANY", "DIRECTOR_CONFLICT"],
            corruption_events={"COMPANY_REGISTRATION": 1,
                               "TENDER_AWARD": rng.randint(1, 4),
                               "PAYMENT_DISBURSEMENT": rng.randint(2, 8)},
            total_value_ksh=val, counterparty_count=rng.randint(1, 3),
            related_party_ratio=rng.uniform(0.9, 1.0),
            execution_rate=rng.uniform(0.1, 0.4), single_source=True,
            concentration_ratio=rng.uniform(0.7, 1.0), rng=rng,
        ))
    for ek in directors:
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="director",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(3, 10), degree=rng.randint(2, 6),
            risk_flags=["SHELL_COMPANY", "DIRECTOR_CONFLICT"],
            corruption_events={"COMPANY_REGISTRATION": rng.randint(1, 3),
                               "DIRECTOR_CHANGE": rng.randint(0, 2)},
            total_value_ksh=0.0, counterparty_count=rng.randint(1, 4), rng=rng,
        ))
    for ek in contracts:
        val = rng.uniform(5e6, 40e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="contract",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(3, 8), degree=rng.randint(1, 4),
            risk_flags=["SHELL_COMPANY", "PRICE_INFLATION"],
            corruption_events={"TENDER_AWARD": 1,
                               "TENDER_AMENDMENT": rng.randint(1, 5),
                               "SINGLE_SOURCE_AWARD": rng.randint(0, 1)},
            total_value_ksh=val, counterparty_count=1,
            amendment_ratio=rng.uniform(0.2, 0.9),
            execution_rate=rng.uniform(0.05, 0.4), single_source=True, rng=rng,
        ))

    log.info("family=shell_network nodes=%d", len(all_ents))
    return all_ents


# ---------------------------------------------------------------------------
# Family 5 — Budget Absorption Fraud (FY-end surge)
# ---------------------------------------------------------------------------

def _family_fy_end_fraud(
    db, *, window_start: datetime, window_end: datetime, rng: random.Random,
) -> List[str]:
    """
    All procurement compressed into last 2 weeks of Kenya FY (June).
    Emergency procurement used to bypass tender process.
    """
    dept      = ["department:ke_ministry_fy_fraud"]
    suppliers = [f"supplier:fy_supplier_{i:02d}" for i in range(4)]
    payments  = [f"payment:fy_pay_{i:03d}" for i in range(18)]
    projects  = [f"project:fy_project_{i:02d}" for i in range(3)]
    official  = ["official:ke_cs_fy_fraud"]
    all_ents  = dept + suppliers + payments + projects + official

    # FY-end events: cluster near end of window
    fy_end_start = window_end - timedelta(days=14)
    _shared_events(db, entities=dept + suppliers, event_type="EMERGENCY_PROCUREMENT",
                   count=15, window_start=fy_end_start, window_end=window_end,
                   rng=rng, group_size=2)
    _shared_events(db, entities=suppliers + payments, event_type="PAYMENT_DISBURSEMENT",
                   count=30, window_start=fy_end_start, window_end=window_end,
                   rng=rng, group_size=3)
    _shared_events(db, entities=dept + projects, event_type="AUDIT_FINDING_EVENT",
                   count=5, window_start=window_start, window_end=window_end,
                   rng=rng, group_size=2)

    for ek in dept:
        val = rng.uniform(200e6, 800e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="department",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(30, 60), degree=rng.randint(10, 25),
            risk_flags=["AUDIT_FINDING"],
            corruption_events={"EMERGENCY_PROCUREMENT": rng.randint(8, 15),
                               "PAYMENT_DISBURSEMENT": rng.randint(15, 30),
                               "AUDIT_FINDING_EVENT": rng.randint(2, 5)},
            total_value_ksh=val, counterparty_count=rng.randint(5, 12),
            fy_end_event_fraction=rng.uniform(0.7, 0.95), rng=rng,
        ))
    for ek in suppliers:
        val = rng.uniform(10e6, 80e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="supplier",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(10, 25), degree=rng.randint(3, 8),
            risk_flags=["AUDIT_FINDING"],
            corruption_events={"EMERGENCY_PROCUREMENT": rng.randint(3, 8),
                               "PAYMENT_DISBURSEMENT": rng.randint(5, 15)},
            total_value_ksh=val, counterparty_count=rng.randint(1, 3),
            fy_end_event_fraction=rng.uniform(0.6, 0.9),
            execution_rate=rng.uniform(0.2, 0.6), single_source=True, rng=rng,
        ))
    for ek in payments:
        val = rng.uniform(500_000, 15e6)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="payment",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(1, 4), degree=rng.randint(1, 3),
            risk_flags=[],
            corruption_events={"PAYMENT_DISBURSEMENT": rng.randint(1, 3)},
            total_value_ksh=val, counterparty_count=1,
            threshold_splitting=rng.uniform(0.0, 0.6),
            fy_end_event_fraction=rng.uniform(0.8, 1.0), rng=rng,
        ))
    for ek in projects:
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="project",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(3, 10), degree=rng.randint(2, 6),
            risk_flags=["AUDIT_FINDING"],
            corruption_events={"AUDIT_FINDING_EVENT": rng.randint(1, 3),
                               "PAYMENT_DISBURSEMENT": rng.randint(2, 6)},
            total_value_ksh=rng.uniform(20e6, 100e6),
            counterparty_count=rng.randint(1, 4),
            execution_rate=rng.uniform(0.05, 0.35), rng=rng,
        ))
    for ek in official:
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type="official",
            window_start=window_start, window_end=window_end,
            event_count=rng.randint(8, 20), degree=rng.randint(4, 10),
            risk_flags=["AUDIT_FINDING"],
            corruption_events={"EMERGENCY_PROCUREMENT": rng.randint(3, 8),
                               "TENDER_AWARD": rng.randint(2, 5),
                               "AUDIT_FINDING_EVENT": rng.randint(1, 3),
                               "WEALTH_DECLARATION": 1},
            total_value_ksh=rng.uniform(3e6, 15e6),
            counterparty_count=rng.randint(3, 8),
            fy_end_event_fraction=rng.uniform(0.5, 0.8), rng=rng,
        ))

    log.info("family=fy_end_fraud nodes=%d", len(all_ents))
    return all_ents


# ---------------------------------------------------------------------------
# Benign nodes (negative class)
# ---------------------------------------------------------------------------

def _benign_nodes(
    db, *, window_start: datetime, window_end: datetime,
    rng: random.Random, count: int, existing_keys: Set[str],
) -> List[str]:
    """
    Clean public sector entities with normal procurement patterns.
    These are the negative class — no risk flags, proper tendering.
    """
    etype_pool = ["official", "company", "contract", "payment",
                  "project", "department", "supplier"]
    benign_event_pool = ["TENDER_AWARD", "PAYMENT_DISBURSEMENT",
                         "COMPANY_REGISTRATION", "WEALTH_DECLARATION"]
    created: List[str] = []
    i = 0
    while len(created) < count:
        etype = rng.choice(etype_pool)
        ek    = f"{etype}:clean_{etype}_{i:04d}"
        i    += 1
        if ek in existing_keys:
            continue
        ec  = rng.randint(1, 10)
        val = rng.uniform(100_000, 5e6)
        evt = rng.choice(benign_event_pool)
        _upsert_snapshot(db, _snap(
            entity_key=ek, entity_type=etype,
            window_start=window_start, window_end=window_end,
            event_count=ec, degree=rng.randint(1, 4),
            risk_flags=[],
            corruption_events={evt: ec},
            total_value_ksh=val, counterparty_count=rng.randint(1, 3),
            related_party_ratio=rng.uniform(0.0, 0.1),
            execution_rate=rng.uniform(0.8, 1.0),
            fy_end_event_fraction=rng.uniform(0.0, 0.15), rng=rng,
        ))
        created.append(ek)
        existing_keys.add(ek)

    log.info("benign_nodes count=%d", len(created))
    return created


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

def seed(
    *,
    window_hours: int = 720,   # 30-day window (typical audit window)
    benign_count: int = 150,
    seed_value:   int = 42,
) -> Dict:
    rng = random.Random(seed_value)
    now = _utcnow().replace(microsecond=0)
    window_end   = now
    window_start = now - timedelta(hours=window_hours)

    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=engine)
        _ensure_source(db)
        db.flush()

        all_positive: List[str] = []
        all_positive += _family_tender_cartel(
            db, window_start=window_start, window_end=window_end, rng=rng)
        all_positive += _family_ghost_workers(
            db, window_start=window_start, window_end=window_end, rng=rng)
        all_positive += _family_inflated_procurement(
            db, window_start=window_start, window_end=window_end, rng=rng)
        all_positive += _family_shell_network(
            db, window_start=window_start, window_end=window_end, rng=rng)
        all_positive += _family_fy_end_fraud(
            db, window_start=window_start, window_end=window_end, rng=rng)

        existing = set(all_positive)
        _benign_nodes(db, window_start=window_start, window_end=window_end,
                      rng=rng, count=benign_count, existing_keys=existing)

        db.commit()

        total    = len(existing)
        positive = len(all_positive)
        log.info(
            "corruption_seed_complete total=%d positive=%d benign=%d "
            "window_key=%s window_start=%s window_end=%s",
            total, positive, total - positive,
            CORRUPTION_WINDOW_KEY, window_start.isoformat(), window_end.isoformat(),
        )
        return {
            "total_nodes":    total,
            "positive_nodes": positive,
            "benign_nodes":   total - positive,
            "window_key":     CORRUPTION_WINDOW_KEY,
            "window_start":   window_start.isoformat(),
            "window_end":     window_end.isoformat(),
        }

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description="Seed synthetic corruption GNN training data for Sentinel-KE")
    p.add_argument("--window-hours", type=int, default=720,
                   help="Audit window in hours (default: 720 = 30 days)")
    p.add_argument("--benign",       type=int, default=150,
                   help="Number of clean/benign entities (default: 150)")
    p.add_argument("--seed",         type=int, default=42,
                   help="Random seed (default: 42)")
    args = p.parse_args()

    result = seed(
        window_hours = args.window_hours,
        benign_count = args.benign,
        seed_value   = args.seed,
    )
    print(json.dumps(result, indent=2))
    print("\nNext step — train the corruption GNN:")
    print("  python -m app.analytics.corruption.train_worker --window-key Wcorruption")


if __name__ == "__main__":
    main()
