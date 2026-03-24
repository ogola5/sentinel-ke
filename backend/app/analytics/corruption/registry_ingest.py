from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert

import app.db.registry  # noqa: F401
from app.analytics.ai_models import GraphFeatureSnapshot
from app.analytics.corruption.ocds_ingest import (
    EntityAccumulator,
    _as_bool,
    _build_supplier_cluster_key,
    _entity_key,
    _iter_flat_rows,
    _parse_dt,
    _pick,
    _snapshot_row,
    _supplier_family_key,
    _touch_entity,
)
from app.analytics.corruption.feature_builder import CORRUPTION_WINDOW_KEY
from app.core.security import hash_api_key
from app.db.base import Base
from app.ledger.db import SessionLocal, engine
from app.ledger.models import EventEntityIndex, EventLog, SourceRegistry
from app.ledger.repository import _key_lookup_hash

log = logging.getLogger("sentinel.corruption.registry_ingest")

REGISTRY_SOURCE_ID = "brs_registry"
REGISTRY_API_KEY = "brs-registry-secret-key"
REGISTRY_CLASSIFICATION = "RESTRICTED"


@dataclass(frozen=True)
class RegistryRecord:
    company_id: str
    company_name: str
    occurred_at: datetime
    registered_at: Optional[datetime]
    director_id: Optional[str]
    beneficial_owner_id: Optional[str]
    tax_id: Optional[str]
    bank_account: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    supplier_cluster_key: Optional[str]
    debarred: bool
    debarred_at: Optional[datetime]
    watchlist_flag: bool
    watchlist_reason: Optional[str]


@dataclass(frozen=True)
class RegistrySignals:
    family_size: int
    cluster_shared: bool
    shell_company: bool
    debarred: bool
    watchlist_flag: bool
    risk_flags: tuple[str, ...]
    extra_event_types: tuple[str, ...]
def _ensure_source(db) -> None:
    stmt = pg_insert(SourceRegistry).values(
        source_id=REGISTRY_SOURCE_ID,
        source_type="gov",
        section_code="economy",
        classification_level=REGISTRY_CLASSIFICATION,
        api_key_hash=hash_api_key(REGISTRY_API_KEY),
        api_key_lookup=_key_lookup_hash(REGISTRY_API_KEY),
        is_active=True,
    ).on_conflict_do_nothing(index_elements=["source_id"])
    db.execute(stmt)
    db.flush()


def _event_hash(*parts: str) -> str:
    import hashlib

    return "registry:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:56]


def _upsert_event(
    db,
    *,
    event_type: str,
    entity_keys: Sequence[str],
    occurred_at: datetime,
    payload: Dict[str, Any],
    idx: int,
) -> str:
    event_hash = _event_hash(event_type, *sorted(entity_keys), occurred_at.isoformat(), str(idx))
    anchors = {
        key.split(":", 1)[0]: key.split(":", 1)[1]
        for key in entity_keys
        if ":" in key
    }
    stmt = pg_insert(EventLog).values(
        event_hash=event_hash,
        event_type=event_type,
        source_id=REGISTRY_SOURCE_ID,
        section_code="economy",
        classification=REGISTRY_CLASSIFICATION,
        occurred_at=occurred_at,
        received_at=occurred_at,
        schema_version="v1",
        signature_valid=False,
        anchors_json=anchors,
        payload_json=payload,
    ).on_conflict_do_nothing(index_elements=["event_hash"])
    db.execute(stmt)

    for entity_key in entity_keys:
        stmt2 = pg_insert(EventEntityIndex).values(
            event_hash=event_hash,
            entity_key=entity_key,
        ).on_conflict_do_nothing(index_elements=["event_hash", "entity_key"])
        db.execute(stmt2)
    return event_hash


def normalize_registry_row(row: Mapping[str, Any]) -> Optional[RegistryRecord]:
    company_id = str(
        _pick(row, "company_id", "registration_number", "supplier_id", "entity_id") or ""
    ).strip()
    company_name = str(
        _pick(row, "company_name", "supplier_name", "entity_name", "registered_name") or company_id
    ).strip()
    occurred_at = _parse_dt(
        _pick(row, "updated_at", "occured_at", "captured_at", "registered_at", "registration_date")
    )
    if not company_id or occurred_at is None:
        return None

    normalized_row = dict(row)
    normalized_row.setdefault("supplier_tax_id", _pick(row, "tax_id", "kra_pin", "pin"))
    normalized_row.setdefault("supplier_bank_account", _pick(row, "bank_account", "account_number"))
    normalized_row.setdefault("supplier_email", _pick(row, "email", "contact_email"))
    normalized_row.setdefault("supplier_phone", _pick(row, "phone", "contact_phone"))
    normalized_row.setdefault("supplier_address", _pick(row, "address", "registered_address"))

    return RegistryRecord(
        company_id=company_id,
        company_name=company_name or company_id,
        occurred_at=occurred_at,
        registered_at=_parse_dt(_pick(row, "registered_at", "registration_date")),
        director_id=str(_pick(row, "director_id", "beneficial_owner_id", "owner_id") or "").strip() or None,
        beneficial_owner_id=str(_pick(row, "beneficial_owner_id", "owner_id", "director_id") or "").strip() or None,
        tax_id=str(_pick(row, "tax_id", "kra_pin", "pin") or "").strip() or None,
        bank_account=str(_pick(row, "bank_account", "account_number") or "").strip() or None,
        email=str(_pick(row, "email", "contact_email") or "").strip() or None,
        phone=str(_pick(row, "phone", "contact_phone") or "").strip() or None,
        address=str(_pick(row, "address", "registered_address") or "").strip() or None,
        supplier_cluster_key=_build_supplier_cluster_key(normalized_row),
        debarred=_as_bool(_pick(row, "debarred", "blacklisted", "sanctioned")),
        debarred_at=_parse_dt(_pick(row, "debarred_at", "blacklisted_at", "sanctioned_at")),
        watchlist_flag=_as_bool(_pick(row, "watchlist_flag", "pep_flag", "sanctions_flag")),
        watchlist_reason=str(_pick(row, "watchlist_reason", "sanctions_reason", "flag_reason") or "").strip() or None,
    )


def load_registry_records(input_file: str) -> List[RegistryRecord]:
    out: List[RegistryRecord] = []
    for row in _iter_flat_rows(input_file):
        record = normalize_registry_row(row)
        if record is not None:
            out.append(record)
    return out


def _derive_registry_signals(
    record: RegistryRecord,
    *,
    family_size: int,
) -> RegistrySignals:
    cluster_shared = family_size > 1
    shell_company = bool(
        record.registered_at
        and (record.occurred_at - record.registered_at).days <= 180
    )

    risk_flags: set[str] = set()
    if cluster_shared:
        risk_flags.update({"DIRECTOR_CONFLICT", "RELATED_PARTY_TRANSACTION"})
    if shell_company:
        risk_flags.add("SHELL_COMPANY")
    if record.debarred:
        risk_flags.add("DEBARRED_SUPPLIER")

    extra_event_types: list[str] = ["COMPANY_REGISTRATION", "SUPPLIER_NETWORK_LINK"]
    if record.debarred:
        extra_event_types.append("DEBARMENT_LISTING")
    if record.watchlist_flag:
        extra_event_types.append("WATCHLIST_HIT")

    return RegistrySignals(
        family_size=family_size,
        cluster_shared=cluster_shared,
        shell_company=shell_company,
        debarred=record.debarred,
        watchlist_flag=record.watchlist_flag,
        risk_flags=tuple(sorted(risk_flags)),
        extra_event_types=tuple(dict.fromkeys(extra_event_types)),
    )


def ingest_registry_records(
    *,
    records: Sequence[RegistryRecord],
    max_records: Optional[int] = None,
) -> Dict[str, Any]:
    if max_records is not None:
        records = list(records)[: max(0, int(max_records))]
    if not records:
        return {"status": "no_data", "records": 0, "events": 0, "snapshots": 0}

    cluster_members: Dict[str, set[str]] = {}
    for record in records:
        if record.supplier_cluster_key:
            cluster_members.setdefault(record.supplier_cluster_key, set()).add(record.company_id)

    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=engine)
        _ensure_source(db)

        entity_map: Dict[str, EntityAccumulator] = {}
        event_count = 0
        window_start = min(record.occurred_at for record in records)
        window_end = max(record.occurred_at for record in records)

        for idx, record in enumerate(records):
            supplier_key = _entity_key("supplier", record.company_id)
            supplier_family_key = _supplier_family_key(record.supplier_cluster_key)
            director_raw = record.beneficial_owner_id or record.director_id
            director_key = _entity_key("director", director_raw) if director_raw else None
            account_key = _entity_key("account", record.bank_account) if record.bank_account else None

            family_size = len(cluster_members.get(record.supplier_cluster_key, set())) if record.supplier_cluster_key else 0
            signals = _derive_registry_signals(record, family_size=family_size)

            payload = {
                "company_id": record.company_id,
                "company_name": record.company_name,
                "registered_at": record.registered_at.isoformat() if record.registered_at else None,
                "debarred": record.debarred,
                "debarred_at": record.debarred_at.isoformat() if record.debarred_at else None,
                "watchlist_flag": record.watchlist_flag,
                "watchlist_reason": record.watchlist_reason,
                "signals": {
                    "family_size": signals.family_size,
                    "cluster_shared": signals.cluster_shared,
                    "shell_company": signals.shell_company,
                    "debarred": signals.debarred,
                    "watchlist_flag": signals.watchlist_flag,
                    "risk_flags": list(signals.risk_flags),
                },
            }

            network_entities = [key for key in [supplier_family_key, director_key, account_key] if key]
            registration_entities = [supplier_key]
            if supplier_family_key:
                registration_entities.append(supplier_family_key)
            if director_key:
                registration_entities.append(director_key)

            _upsert_event(
                db,
                event_type="COMPANY_REGISTRATION",
                entity_keys=registration_entities,
                occurred_at=record.occurred_at,
                payload=payload,
                idx=idx,
            )
            event_count += 1

            if network_entities:
                _upsert_event(
                    db,
                    event_type="SUPPLIER_NETWORK_LINK",
                    entity_keys=[supplier_key, *network_entities],
                    occurred_at=record.occurred_at,
                    payload=payload,
                    idx=idx + 10_000,
                )
                event_count += 1

            if record.debarred:
                sanction_entities = [supplier_key]
                if director_key:
                    sanction_entities.append(director_key)
                if supplier_family_key:
                    sanction_entities.append(supplier_family_key)
                _upsert_event(
                    db,
                    event_type="DEBARMENT_LISTING",
                    entity_keys=sanction_entities,
                    occurred_at=record.debarred_at or record.occurred_at,
                    payload=payload,
                    idx=idx + 20_000,
                )
                event_count += 1

            if record.watchlist_flag:
                watchlist_entities = [supplier_key]
                if director_key:
                    watchlist_entities.append(director_key)
                if supplier_family_key:
                    watchlist_entities.append(supplier_family_key)
                _upsert_event(
                    db,
                    event_type="WATCHLIST_HIT",
                    entity_keys=watchlist_entities,
                    occurred_at=record.occurred_at,
                    payload=payload,
                    idx=idx + 30_000,
                )
                event_count += 1

            entity_types = {supplier_key: "supplier"}
            if supplier_family_key:
                entity_types[supplier_family_key] = "supplier"
            if director_key:
                entity_types[director_key] = "director"
            if account_key:
                entity_types[account_key] = "account"

            for entity_key in registration_entities:
                _touch_entity(
                    entity_map,
                    entity_key=entity_key,
                    entity_type=entity_types[entity_key],
                    occurred_at=record.occurred_at,
                    event_type="COMPANY_REGISTRATION",
                    amount_ksh=0.0,
                    counterparty_keys=[key for key in registration_entities if key != entity_key],
                    risk_flags=list(signals.risk_flags),
                    related_party=signals.cluster_shared,
                    single_source=False,
                    threshold_split=False,
                    family_size=signals.family_size,
                )

            if network_entities:
                network_event_entities = [supplier_key, *network_entities]
                for entity_key in network_event_entities:
                    _touch_entity(
                        entity_map,
                        entity_key=entity_key,
                        entity_type=entity_types[entity_key],
                        occurred_at=record.occurred_at,
                        event_type="SUPPLIER_NETWORK_LINK",
                        amount_ksh=0.0,
                        counterparty_keys=[key for key in network_event_entities if key != entity_key],
                        risk_flags=list(signals.risk_flags),
                        related_party=signals.cluster_shared,
                        single_source=False,
                        threshold_split=False,
                        family_size=signals.family_size,
                    )

            if record.debarred:
                sanction_entities = [supplier_key]
                if director_key:
                    sanction_entities.append(director_key)
                if supplier_family_key:
                    sanction_entities.append(supplier_family_key)
                for entity_key in sanction_entities:
                    _touch_entity(
                        entity_map,
                        entity_key=entity_key,
                        entity_type=entity_types[entity_key],
                        occurred_at=record.debarred_at or record.occurred_at,
                        event_type="DEBARMENT_LISTING",
                        amount_ksh=0.0,
                        counterparty_keys=[key for key in sanction_entities if key != entity_key],
                        risk_flags=list(signals.risk_flags),
                        related_party=signals.cluster_shared,
                        single_source=False,
                        threshold_split=False,
                        family_size=signals.family_size,
                    )

            if record.watchlist_flag:
                watchlist_entities = [supplier_key]
                if director_key:
                    watchlist_entities.append(director_key)
                if supplier_family_key:
                    watchlist_entities.append(supplier_family_key)
                for entity_key in watchlist_entities:
                    _touch_entity(
                        entity_map,
                        entity_key=entity_key,
                        entity_type=entity_types[entity_key],
                        occurred_at=record.occurred_at,
                        event_type="WATCHLIST_HIT",
                        amount_ksh=0.0,
                        counterparty_keys=[key for key in watchlist_entities if key != entity_key],
                        risk_flags=list(signals.risk_flags),
                        related_party=signals.cluster_shared,
                        single_source=False,
                        threshold_split=False,
                        family_size=signals.family_size,
                    )

        snapshot_rows = [_snapshot_row(row, window_start=window_start, window_end=window_end) for row in entity_map.values()]
        if snapshot_rows:
            stmt = pg_insert(GraphFeatureSnapshot).values(snapshot_rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["entity_key", "window_key", "window_end"],
                set_={
                    "entity_type": stmt.excluded.entity_type,
                    "window_start": stmt.excluded.window_start,
                    "degree": stmt.excluded.degree,
                    "weighted_degree": stmt.excluded.weighted_degree,
                    "event_count": stmt.excluded.event_count,
                    "first_seen": stmt.excluded.first_seen,
                    "last_seen": stmt.excluded.last_seen,
                    "risk_flags": stmt.excluded.risk_flags,
                    "features": stmt.excluded.features,
                    "created_at": stmt.excluded.created_at,
                },
            )
            db.execute(stmt)

        db.commit()
        return {
            "status": "ok",
            "records": len(records),
            "events": event_count,
            "snapshots": len(snapshot_rows),
            "window_key": CORRUPTION_WINDOW_KEY,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest company-registry / beneficial-ownership rows into corruption-domain graph tables.",
    )
    parser.add_argument("--input-file", required=True, help="Flat CSV/JSON/JSONL registry extract.")
    parser.add_argument("--max-records", type=int, default=None, help="Optional cap for development runs.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    records = load_registry_records(args.input_file)
    result = ingest_registry_records(records=records, max_records=args.max_records)
    print(json.dumps(result))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
