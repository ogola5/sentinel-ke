from __future__ import annotations

import argparse
import hashlib
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert

import app.db.registry  # noqa: F401
from app.analytics.ai_models import GraphFeatureSnapshot
from app.analytics.corruption.ocds_ingest import (
    EntityAccumulator,
    _as_bool,
    _as_float,
    _entity_key,
    _iter_flat_rows,
    _parse_dt,
    _pick,
    _snapshot_row,
    _touch_entity,
)
from app.analytics.corruption.feature_builder import CORRUPTION_WINDOW_KEY
from app.core.security import hash_api_key
from app.db.base import Base
from app.ledger.db import SessionLocal, engine
from app.ledger.models import EventEntityIndex, EventLog, SourceRegistry
from app.ledger.repository import _key_lookup_hash

log = logging.getLogger("sentinel.corruption.outcome_ingest")

OUTCOME_SOURCE_ID = "corruption_outcomes"
OUTCOME_API_KEY = "corruption-outcomes-secret-key"
OUTCOME_CLASSIFICATION = "RESTRICTED"

ADVERSE_STATUSES = {
    "adverse",
    "confirmed",
    "sanctioned",
    "upheld",
    "convicted",
    "liable",
    "substantiated",
}
NEGATIVE_STATUSES = {"cleared", "dismissed", "closed_no_finding", "exonerated"}


@dataclass(frozen=True)
class OutcomeRecord:
    outcome_id: str
    case_id: Optional[str]
    occurred_at: datetime
    department_id: str
    department_name: str
    supplier_id: Optional[str]
    supplier_name: Optional[str]
    official_id: Optional[str]
    contract_id: Optional[str]
    project_id: Optional[str]
    project_title: Optional[str]
    finding_type: str
    outcome_status: str
    sanction_type: Optional[str]
    loss_amount_ksh: Optional[float]
    recovery_amount_ksh: Optional[float]
    source_system: Optional[str]


@dataclass(frozen=True)
class OutcomeSignals:
    adverse: bool
    cleared: bool
    audit_finding: bool
    sanction_applied: bool
    recovery_order: bool
    supplier_sanctioned: bool
    official_sanctioned: bool
    outcome_label: Optional[int]
    risk_flags: tuple[str, ...]
    extra_event_types: tuple[str, ...]


def _ensure_source(db) -> None:
    stmt = pg_insert(SourceRegistry).values(
        source_id=OUTCOME_SOURCE_ID,
        source_type="gov",
        section_code="economy",
        classification_level=OUTCOME_CLASSIFICATION,
        api_key_hash=hash_api_key(OUTCOME_API_KEY),
        api_key_lookup=_key_lookup_hash(OUTCOME_API_KEY),
        is_active=True,
    ).on_conflict_do_nothing(index_elements=["source_id"])
    db.execute(stmt)
    db.flush()


def _event_hash(*parts: str) -> str:
    return "outcome:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:56]


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
        source_id=OUTCOME_SOURCE_ID,
        section_code="economy",
        classification=OUTCOME_CLASSIFICATION,
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


def normalize_outcome_row(row: Mapping[str, Any]) -> Optional[OutcomeRecord]:
    outcome_id = str(_pick(row, "outcome_id", "finding_id", "record_id") or "").strip()
    department_id = str(_pick(row, "department_id", "agency_id", "ministry_id") or "").strip()
    occurred_at = _parse_dt(_pick(row, "occurred_at", "decision_date", "finding_date", "updated_at"))
    finding_type = str(_pick(row, "finding_type", "case_type", "outcome_type") or "").strip()
    outcome_status = str(_pick(row, "outcome_status", "decision_status", "status") or "").strip().lower()
    if not all([outcome_id, department_id, occurred_at, finding_type, outcome_status]):
        return None

    return OutcomeRecord(
        outcome_id=outcome_id,
        case_id=str(_pick(row, "case_id", "reference_id", "tribunal_case_id") or "").strip() or None,
        occurred_at=occurred_at,
        department_id=department_id,
        department_name=str(_pick(row, "department_name", "agency_name", "ministry_name") or department_id).strip(),
        supplier_id=str(_pick(row, "supplier_id", "vendor_id") or "").strip() or None,
        supplier_name=str(_pick(row, "supplier_name", "vendor_name") or "").strip() or None,
        official_id=str(_pick(row, "official_id", "subject_official_id", "actor_id") or "").strip() or None,
        contract_id=str(_pick(row, "contract_id", "tender_contract_id") or "").strip() or None,
        project_id=str(_pick(row, "project_id", "ifmis_project_id") or "").strip() or None,
        project_title=str(_pick(row, "project_title", "project_name") or "").strip() or None,
        finding_type=finding_type,
        outcome_status=outcome_status,
        sanction_type=str(_pick(row, "sanction_type", "penalty_type") or "").strip() or None,
        loss_amount_ksh=_as_float(_pick(row, "loss_amount_ksh", "loss_amount", "exposure_amount")),
        recovery_amount_ksh=_as_float(_pick(row, "recovery_amount_ksh", "recovered_amount", "recovery_amount")),
        source_system=str(_pick(row, "source_system", "source") or "").strip() or None,
    )


def load_outcome_records(input_file: str) -> List[OutcomeRecord]:
    out: List[OutcomeRecord] = []
    for row in _iter_flat_rows(input_file):
        record = normalize_outcome_row(row)
        if record is not None:
            out.append(record)
    return out


def _derive_outcome_signals(record: OutcomeRecord) -> OutcomeSignals:
    status = str(record.outcome_status or "").strip().lower()
    finding_norm = str(record.finding_type or "").strip().lower()
    sanction_norm = str(record.sanction_type or "").strip().lower()

    adverse = status in ADVERSE_STATUSES
    cleared = status in NEGATIVE_STATUSES
    audit_finding = "audit" in finding_norm or "ppra" in finding_norm
    sanction_applied = bool(sanction_norm) or status in {"sanctioned", "convicted", "liable"}
    recovery_order = bool(record.recovery_amount_ksh and record.recovery_amount_ksh > 0)
    supplier_sanctioned = sanction_applied and bool(record.supplier_id)
    official_sanctioned = sanction_applied and bool(record.official_id)

    risk_flags: set[str] = set()
    if audit_finding:
        risk_flags.add("AUDIT_FINDING")
    if adverse:
        risk_flags.add("CASE_CONFIRMED_CORRUPTION")
    if supplier_sanctioned and ("debar" in sanction_norm or "blacklist" in sanction_norm):
        risk_flags.add("DEBARRED_SUPPLIER")
    if official_sanctioned:
        risk_flags.add("OFFICIAL_SANCTIONED")
    if recovery_order:
        risk_flags.add("RECOVERY_ORDER")

    outcome_label: Optional[int]
    if adverse:
        outcome_label = 1
    elif cleared:
        outcome_label = 0
    else:
        outcome_label = None

    extra_event_types: list[str] = ["CASE_OUTCOME_RECORDED"]
    if audit_finding:
        extra_event_types.append("AUDIT_FINDING_EVENT")
    if sanction_applied:
        extra_event_types.append("SANCTION_APPLIED")
    if recovery_order:
        extra_event_types.append("RECOVERY_ORDER")

    return OutcomeSignals(
        adverse=adverse,
        cleared=cleared,
        audit_finding=audit_finding,
        sanction_applied=sanction_applied,
        recovery_order=recovery_order,
        supplier_sanctioned=supplier_sanctioned,
        official_sanctioned=official_sanctioned,
        outcome_label=outcome_label,
        risk_flags=tuple(sorted(risk_flags)),
        extra_event_types=tuple(dict.fromkeys(extra_event_types)),
    )


def ingest_outcome_records(
    *,
    records: Sequence[OutcomeRecord],
    max_records: Optional[int] = None,
) -> Dict[str, Any]:
    if max_records is not None:
        records = list(records)[: max(0, int(max_records))]
    if not records:
        return {"status": "no_data", "records": 0, "events": 0, "snapshots": 0}

    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=engine)
        _ensure_source(db)

        entity_map: Dict[str, EntityAccumulator] = {}
        event_count = 0
        window_start = min(record.occurred_at for record in records)
        window_end = max(record.occurred_at for record in records)

        for idx, record in enumerate(records):
            department_key = _entity_key("department", record.department_id)
            entities = [department_key]
            supplier_key = _entity_key("supplier", record.supplier_id) if record.supplier_id else None
            official_key = _entity_key("official", record.official_id) if record.official_id else None
            contract_key = _entity_key("contract", record.contract_id) if record.contract_id else None
            project_key = _entity_key("project", record.project_id or record.project_title) if (record.project_id or record.project_title) else None
            for key in [supplier_key, official_key, contract_key, project_key]:
                if key:
                    entities.append(key)

            signals = _derive_outcome_signals(record)
            payload = {
                "outcome_id": record.outcome_id,
                "case_id": record.case_id,
                "department_name": record.department_name,
                "supplier_name": record.supplier_name,
                "finding_type": record.finding_type,
                "outcome_status": record.outcome_status,
                "sanction_type": record.sanction_type,
                "loss_amount_ksh": record.loss_amount_ksh,
                "recovery_amount_ksh": record.recovery_amount_ksh,
                "source_system": record.source_system,
                "signals": asdict(signals),
            }

            entity_types = {department_key: "department"}
            if supplier_key:
                entity_types[supplier_key] = "supplier"
            if official_key:
                entity_types[official_key] = "official"
            if contract_key:
                entity_types[contract_key] = "contract"
            if project_key:
                entity_types[project_key] = "project"

            for offset, event_type in enumerate(signals.extra_event_types):
                apply_outcome_metrics = offset == 0
                _upsert_event(
                    db,
                    event_type=event_type,
                    entity_keys=entities,
                    occurred_at=record.occurred_at,
                    payload=payload,
                    idx=idx + offset,
                )
                event_count += 1
                for entity_key in entities:
                    _touch_entity(
                        entity_map,
                        entity_key=entity_key,
                        entity_type=entity_types[entity_key],
                        occurred_at=record.occurred_at,
                        event_type=event_type,
                        amount_ksh=0.0,
                        counterparty_keys=[key for key in entities if key != entity_key],
                        risk_flags=list(signals.risk_flags),
                        related_party=False,
                        single_source=False,
                        threshold_split=False,
                        adverse_outcome=1 if apply_outcome_metrics and signals.adverse else 0,
                        sanction_event=1 if apply_outcome_metrics and signals.sanction_applied else 0,
                        recovery_amount_ksh=float(record.recovery_amount_ksh or 0.0) if apply_outcome_metrics else 0.0,
                        outcome_label=signals.outcome_label if apply_outcome_metrics else None,
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
        description="Ingest audit/tribunal/case outcomes into corruption-domain graph tables.",
    )
    parser.add_argument("--input-file", required=True, help="Flat CSV/JSON/JSONL outcome extract.")
    parser.add_argument("--max-records", type=int, default=None, help="Optional cap for development runs.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    records = load_outcome_records(args.input_file)
    result = ingest_outcome_records(records=records, max_records=args.max_records)
    print(json.dumps(result))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
