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
    _as_int,
    _as_pct,
    _entity_key,
    _is_near_threshold,
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

log = logging.getLogger("sentinel.corruption.payment_ingest")

IFMIS_SOURCE_ID = "ifmis_disbursement"
IFMIS_API_KEY = "ifmis-disbursement-secret-key"
IFMIS_CLASSIFICATION = "RESTRICTED"


@dataclass(frozen=True)
class PaymentTrailRecord:
    payment_id: str
    invoice_id: str
    voucher_id: Optional[str]
    occurred_at: datetime
    department_id: str
    department_name: str
    supplier_id: str
    supplier_name: str
    contract_id: Optional[str]
    project_id: Optional[str]
    project_title: Optional[str]
    approver_id: Optional[str]
    account_id: Optional[str]
    milestone_id: Optional[str]
    amount_ksh: float
    approved_amount_ksh: Optional[float]
    advance_payment_ksh: Optional[float]
    retention_amount_ksh: Optional[float]
    delivery_progress_pct: Optional[float]
    certified_progress_pct: Optional[float]
    approval_stage_count: int
    due_at: Optional[datetime]
    released_at: Optional[datetime]
    payment_status: Optional[str]
    emergency_procurement: bool
    supplier_debarred: bool
    audit_flag: bool
    manual_override: bool


@dataclass(frozen=True)
class PaymentSignals:
    approver_load: int
    payment_split: bool
    approval_bypass: bool
    delayed_payment: bool
    high_advance: bool
    delivery_mismatch: bool
    approver_concentration: bool
    risk_flags: tuple[str, ...]
    extra_event_types: tuple[str, ...]
    payment_to_delivery_ratio: float
    progress_mismatch: float


def _ensure_source(db) -> None:
    stmt = pg_insert(SourceRegistry).values(
        source_id=IFMIS_SOURCE_ID,
        source_type="gov",
        section_code="economy",
        classification_level=IFMIS_CLASSIFICATION,
        api_key_hash=hash_api_key(IFMIS_API_KEY),
        api_key_lookup=_key_lookup_hash(IFMIS_API_KEY),
        is_active=True,
    ).on_conflict_do_nothing(index_elements=["source_id"])
    db.execute(stmt)
    db.flush()


def _event_hash(*parts: str) -> str:
    return "ifmis:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:56]


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
        source_id=IFMIS_SOURCE_ID,
        section_code="economy",
        classification=IFMIS_CLASSIFICATION,
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


def normalize_payment_row(row: Mapping[str, Any]) -> Optional[PaymentTrailRecord]:
    invoice_id = str(_pick(row, "invoice_id", "record_id", "invoice_number") or "").strip()
    payment_id = str(_pick(row, "payment_id", "transaction_id", "payment_reference") or invoice_id).strip()
    department_id = str(_pick(row, "department_id", "agency_id", "ministry_id") or "").strip()
    supplier_id = str(_pick(row, "supplier_id", "vendor_id", "beneficiary_id") or "").strip()
    occurred_at = _parse_dt(_pick(row, "approved_at", "occurred_at", "invoice_date", "captured_at"))
    amount_ksh = _as_float(_pick(row, "amount_ksh", "approved_amount", "invoice_amount", "amount"))
    if not all([payment_id, invoice_id, department_id, supplier_id, occurred_at]) or amount_ksh is None:
        return None

    return PaymentTrailRecord(
        payment_id=payment_id,
        invoice_id=invoice_id,
        voucher_id=str(_pick(row, "voucher_id", "payment_voucher_id") or "").strip() or None,
        occurred_at=occurred_at,
        department_id=department_id,
        department_name=str(_pick(row, "department_name", "agency_name", "ministry_name") or department_id).strip(),
        supplier_id=supplier_id,
        supplier_name=str(_pick(row, "supplier_name", "vendor_name", "beneficiary_name") or supplier_id).strip(),
        contract_id=str(_pick(row, "contract_id", "tender_contract_id") or "").strip() or None,
        project_id=str(_pick(row, "project_id", "ifmis_project_id") or "").strip() or None,
        project_title=str(_pick(row, "project_title", "project_name") or "").strip() or None,
        approver_id=str(_pick(row, "approver_id", "approved_by", "authorizer_id") or "").strip() or None,
        account_id=str(_pick(row, "account_id", "ifmis_account_id", "vote_head_account") or "").strip() or None,
        milestone_id=str(_pick(row, "milestone_id", "certificate_id", "approval_stage_id") or "").strip() or None,
        amount_ksh=float(amount_ksh),
        approved_amount_ksh=_as_float(_pick(row, "approved_amount_ksh", "approved_amount")),
        advance_payment_ksh=_as_float(_pick(row, "advance_payment_ksh", "advance_amount")),
        retention_amount_ksh=_as_float(_pick(row, "retention_amount_ksh", "retention_amount")),
        delivery_progress_pct=_as_pct(_pick(row, "delivery_progress_pct", "project_delivery_progress_pct")),
        certified_progress_pct=_as_pct(_pick(row, "certified_progress_pct", "certified_progress_pct")),
        approval_stage_count=_as_int(_pick(row, "approval_stage_count", "approval_steps")) or 0,
        due_at=_parse_dt(_pick(row, "due_at", "payment_due_date")),
        released_at=_parse_dt(_pick(row, "released_at", "payment_released_at")),
        payment_status=str(_pick(row, "payment_status", "status") or "").strip() or None,
        emergency_procurement=_as_bool(_pick(row, "emergency_procurement", "emergency_flag")),
        supplier_debarred=_as_bool(_pick(row, "supplier_debarred", "debarred_supplier")),
        audit_flag=_as_bool(_pick(row, "audit_flag", "audit_exception_flag")),
        manual_override=_as_bool(_pick(row, "manual_override", "override_flag")),
    )


def load_payment_records(input_file: str) -> List[PaymentTrailRecord]:
    out: List[PaymentTrailRecord] = []
    for row in _iter_flat_rows(input_file):
        record = normalize_payment_row(row)
        if record is not None:
            out.append(record)
    return out


def _derive_payment_signals(
    record: PaymentTrailRecord,
    *,
    approver_load: int,
) -> PaymentSignals:
    approved_amount = float(record.approved_amount_ksh if record.approved_amount_ksh is not None else record.amount_ksh)
    delivery_progress = float(record.delivery_progress_pct or 0.0)
    certified_progress = float(record.certified_progress_pct or 0.0)
    progress_mismatch = max(0.0, certified_progress - delivery_progress)
    payment_ratio = approved_amount / max(1.0, float(record.amount_ksh or 0.0))
    payment_to_delivery_ratio = payment_ratio - delivery_progress if delivery_progress > 0 else payment_ratio

    payment_split = _is_near_threshold(approved_amount)
    approval_bypass = bool(record.manual_override or (record.approval_stage_count <= 1 and approved_amount >= 1_000_000.0))
    delayed_payment = bool(
        (record.due_at and record.released_at and (record.released_at - record.due_at).days >= 30)
        or str(record.payment_status or "").strip().lower() in {"held", "blocked", "pending_review"}
    )
    high_advance = bool(record.advance_payment_ksh and approved_amount > 0 and float(record.advance_payment_ksh) / approved_amount >= 0.2)
    delivery_mismatch = bool(progress_mismatch >= 0.25 or payment_to_delivery_ratio >= 0.35)
    approver_concentration = approver_load >= 3

    risk_flags: set[str] = set()
    if record.audit_flag:
        risk_flags.add("AUDIT_FINDING")
    if record.supplier_debarred:
        risk_flags.add("DEBARRED_SUPPLIER")
    if delivery_mismatch:
        risk_flags.add("PROJECT_DELIVERY_MISMATCH")
    if approval_bypass:
        risk_flags.add("PAYMENT_APPROVAL_BYPASS")
    if delayed_payment:
        risk_flags.add("PAYMENT_DELAY_RISK")
    if high_advance:
        risk_flags.add("ADVANCE_PAYMENT_RISK")

    extra_event_types: list[str] = ["INVOICE_APPROVED"]
    if record.voucher_id:
        extra_event_types.append("PAYMENT_VOUCHER_CREATED")
    if record.released_at:
        extra_event_types.append("PAYMENT_DISBURSEMENT")
    if record.approver_id:
        extra_event_types.append("APPROVER_LINK")
    if high_advance:
        extra_event_types.append("ADVANCE_PAYMENT")
    if record.milestone_id or record.certified_progress_pct is not None:
        extra_event_types.append("PROJECT_MILESTONE_CERTIFIED")
    if delayed_payment:
        extra_event_types.append("PAYMENT_HOLD")

    return PaymentSignals(
        approver_load=approver_load,
        payment_split=payment_split,
        approval_bypass=approval_bypass,
        delayed_payment=delayed_payment,
        high_advance=high_advance,
        delivery_mismatch=delivery_mismatch,
        approver_concentration=approver_concentration,
        risk_flags=tuple(sorted(risk_flags)),
        extra_event_types=tuple(dict.fromkeys(extra_event_types)),
        payment_to_delivery_ratio=round(max(0.0, payment_to_delivery_ratio), 6),
        progress_mismatch=round(progress_mismatch, 6),
    )


def _payment_event_amount(record: PaymentTrailRecord, *, event_type: str) -> float:
    approved_amount = float(record.approved_amount_ksh if record.approved_amount_ksh is not None else record.amount_ksh)
    if event_type == "INVOICE_APPROVED":
        return max(0.0, approved_amount)
    return 0.0


def _payment_event_entities(
    *,
    event_type: str,
    base_entities: Sequence[str],
    invoice_key: str,
    approver_key: Optional[str],
    account_key: Optional[str],
) -> List[str]:
    entities = list(base_entities)
    if event_type == "INVOICE_APPROVED":
        entities.append(invoice_key)
    if event_type == "PAYMENT_VOUCHER_CREATED":
        entities.append(invoice_key)
    if event_type == "PAYMENT_DISBURSEMENT" and account_key:
        entities.append(account_key)
    if event_type == "APPROVER_LINK" and approver_key:
        entities.append(approver_key)
    if event_type == "ADVANCE_PAYMENT":
        entities.append(invoice_key)
        if account_key:
            entities.append(account_key)
    if event_type == "PROJECT_MILESTONE_CERTIFIED":
        entities.append(invoice_key)
        if approver_key:
            entities.append(approver_key)
    if event_type == "PAYMENT_HOLD" and approver_key:
        entities.append(approver_key)
    return list(dict.fromkeys(entities))


def ingest_payment_records(
    *,
    records: Sequence[PaymentTrailRecord],
    max_records: Optional[int] = None,
) -> Dict[str, Any]:
    if max_records is not None:
        records = list(records)[: max(0, int(max_records))]
    if not records:
        return {"status": "no_data", "records": 0, "events": 0, "snapshots": 0}

    approver_counts: Dict[str, int] = {}
    for record in records:
        if record.approver_id:
            approver_counts[record.approver_id] = approver_counts.get(record.approver_id, 0) + 1

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
            supplier_key = _entity_key("supplier", record.supplier_id)
            contract_key = _entity_key("contract", record.contract_id or f"{record.payment_id}-contract")
            invoice_key = _entity_key("payment", record.invoice_id)
            entities = [department_key, supplier_key, contract_key]
            project_key = None
            if record.project_id or record.project_title:
                project_key = _entity_key("project", record.project_id or record.project_title or record.payment_id)
                entities.append(project_key)
            approver_key = _entity_key("official", record.approver_id) if record.approver_id else None
            account_key = _entity_key("account", record.account_id) if record.account_id else None

            signals = _derive_payment_signals(record, approver_load=approver_counts.get(record.approver_id or "", 0))

            payload = {
                "payment_id": record.payment_id,
                "invoice_id": record.invoice_id,
                "voucher_id": record.voucher_id,
                "department_name": record.department_name,
                "supplier_name": record.supplier_name,
                "project_id": record.project_id,
                "project_title": record.project_title,
                "amount_ksh": round(record.amount_ksh, 2),
                "approved_amount_ksh": round(float(record.approved_amount_ksh or record.amount_ksh), 2),
                "payment_status": record.payment_status,
                "signals": asdict(signals),
            }

            base_event_entities = list(entities) + [invoice_key]
            _upsert_event(
                db,
                event_type="INVOICE_APPROVED",
                entity_keys=base_event_entities,
                occurred_at=record.occurred_at,
                payload=payload,
                idx=idx,
            )
            event_count += 1

            entity_types = {
                department_key: "department",
                supplier_key: "supplier",
                contract_key: "contract",
                invoice_key: "payment",
            }
            if project_key:
                entity_types[project_key] = "project"
            if approver_key:
                entity_types[approver_key] = "official"
            if account_key:
                entity_types[account_key] = "account"

            for entity_key in base_event_entities:
                _touch_entity(
                    entity_map,
                    entity_key=entity_key,
                    entity_type=entity_types[entity_key],
                    occurred_at=record.occurred_at,
                    event_type="INVOICE_APPROVED",
                    amount_ksh=_payment_event_amount(record, event_type="INVOICE_APPROVED"),
                    counterparty_keys=[key for key in base_event_entities if key != entity_key],
                    risk_flags=list(signals.risk_flags),
                    related_party=False,
                    single_source=record.emergency_procurement,
                    threshold_split=signals.payment_split,
                    payment_amount_ksh=0.0,
                    complaint_count=0,
                    quality_failure_count=0,
                    delay_days=max(0, (record.released_at - record.due_at).days) if record.due_at and record.released_at else 0,
                    delivery_progress_pct=record.delivery_progress_pct,
                    certified_progress_pct=record.certified_progress_pct,
                    payment_to_delivery_ratio=signals.payment_to_delivery_ratio,
                    progress_mismatch=signals.progress_mismatch,
                )

            for offset, event_type in enumerate(signals.extra_event_types[1:], start=1):
                event_entities = _payment_event_entities(
                    event_type=event_type,
                    base_entities=entities,
                    invoice_key=invoice_key,
                    approver_key=approver_key,
                    account_key=account_key,
                )
                _upsert_event(
                    db,
                    event_type=event_type,
                    entity_keys=event_entities,
                    occurred_at=record.released_at if event_type == "PAYMENT_DISBURSEMENT" and record.released_at else record.occurred_at,
                    payload=payload,
                    idx=idx + offset,
                )
                event_count += 1
                for entity_key in event_entities:
                    _touch_entity(
                        entity_map,
                        entity_key=entity_key,
                        entity_type=entity_types[entity_key],
                        occurred_at=record.released_at if event_type == "PAYMENT_DISBURSEMENT" and record.released_at else record.occurred_at,
                        event_type=event_type,
                        amount_ksh=_payment_event_amount(record, event_type=event_type),
                        counterparty_keys=[key for key in event_entities if key != entity_key],
                        risk_flags=list(signals.risk_flags),
                        related_party=False,
                        single_source=record.emergency_procurement,
                        threshold_split=signals.payment_split,
                        payment_amount_ksh=(
                            float(record.approved_amount_ksh if record.approved_amount_ksh is not None else record.amount_ksh)
                            if event_type == "PAYMENT_DISBURSEMENT"
                            else float(record.advance_payment_ksh or 0.0)
                            if event_type == "ADVANCE_PAYMENT"
                            else 0.0
                        ),
                        complaint_count=0,
                        quality_failure_count=0,
                        delay_days=max(0, (record.released_at - record.due_at).days) if event_type == "PAYMENT_HOLD" and record.due_at and record.released_at else 0,
                        delivery_progress_pct=record.delivery_progress_pct if event_type in {"PROJECT_MILESTONE_CERTIFIED", "PAYMENT_DISBURSEMENT"} else None,
                        certified_progress_pct=record.certified_progress_pct if event_type == "PROJECT_MILESTONE_CERTIFIED" else None,
                        payment_to_delivery_ratio=signals.payment_to_delivery_ratio,
                        progress_mismatch=signals.progress_mismatch,
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
        description="Ingest IFMIS-style payment trail rows into corruption-domain graph tables.",
    )
    parser.add_argument("--input-file", required=True, help="Flat CSV/JSON/JSONL payment extract.")
    parser.add_argument("--max-records", type=int, default=None, help="Optional cap for development runs.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    records = load_payment_records(args.input_file)
    result = ingest_payment_records(records=records, max_records=args.max_records)
    print(json.dumps(result))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
