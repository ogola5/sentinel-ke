from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert

import app.db.registry  # noqa: F401
from app.analytics.ai_models import GraphFeatureSnapshot
from app.analytics.corruption.feature_builder import CORRUPTION_WINDOW_KEY
from app.core.security import hash_api_key
from app.db.base import Base
from app.ledger.db import SessionLocal, engine
from app.ledger.models import EventEntityIndex, EventLog, SourceRegistry
from app.ledger.repository import _key_lookup_hash

log = logging.getLogger("sentinel.corruption.ocds_ingest")

PPRA_SOURCE_ID = "ppra_ocds"
PPRA_API_KEY = "ppra-ocds-secret-key"
PPRA_CLASSIFICATION = "PUBLIC"
PPRA_THRESHOLD_LEVELS = (100_000.0, 500_000.0, 1_000_000.0, 5_000_000.0, 10_000_000.0)
NON_COMPETITIVE_METHODS = {"direct", "direct contracting", "limited", "restricted", "single_source"}


@dataclass(frozen=True)
class ProcurementRecord:
    ocid: str
    occurred_at: datetime
    buyer_id: str
    buyer_name: str
    tender_id: str
    tender_title: str
    supplier_id: str
    supplier_name: str
    contract_id: Optional[str]
    award_id: Optional[str]
    amount_ksh: float
    estimated_amount_ksh: Optional[float]
    payment_amount_ksh: Optional[float]
    advance_payment_ksh: Optional[float]
    procurement_method: str
    procurement_method_details: str
    tenderer_count: Optional[int]
    supplier_registered_at: Optional[datetime]
    supplier_cluster_key: Optional[str]
    audit_flag: bool
    amendment_count: int
    amended_amount_ksh: Optional[float]
    project_id: Optional[str]
    project_title: Optional[str]


@dataclass
class EntityAccumulator:
    entity_key: str
    entity_type: str
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    event_count: int = 0
    risk_flags: set[str] = field(default_factory=set)
    corruption_events: Counter[str] = field(default_factory=Counter)
    counterparty_keys: set[str] = field(default_factory=set)
    counterparty_amounts: Dict[str, float] = field(default_factory=dict)
    total_value_ksh: float = 0.0
    payment_amount_ksh: float = 0.0
    related_party_amount_ksh: float = 0.0
    fy_end_event_count: int = 0
    award_like_count: int = 0
    threshold_split_hits: int = 0
    single_source_count: int = 0
    amendment_count: int = 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _norm_key(key: str) -> str:
    return "".join(ch for ch in str(key or "").lower() if ch.isalnum())


def _slug(value: str, *, fallback: str) -> str:
    raw = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").strip().lower())
    raw = "_".join(part for part in raw.split("_") if part)
    return raw or fallback


def _pick(row: Mapping[str, Any], *keys: str) -> Any:
    idx = {_norm_key(k): v for k, v in row.items()}
    for key in keys:
        nk = _norm_key(key)
        if nk in idx and idx[nk] not in {None, ""}:
            return idx[nk]
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _as_int(value: Any) -> Optional[int]:
    f = _as_float(value)
    if f is None:
        return None
    return int(f)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in {"1", "true", "t", "yes", "y", "flagged", "review"}


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None
        normalized = s.replace("Z", "+00:00")
        dt = None
        for fmt in (
            None,
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                if fmt is None:
                    dt = datetime.fromisoformat(normalized)
                else:
                    dt = datetime.strptime(s, fmt)
                break
            except Exception:
                continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _entity_key(kind: str, raw: str) -> str:
    return f"{kind}:{_slug(raw, fallback=kind)}"


def _is_single_source(method: str, method_details: str, tenderer_count: Optional[int]) -> bool:
    method_norm = str(method or "").strip().lower()
    detail_norm = str(method_details or "").strip().lower()
    if method_norm in NON_COMPETITIVE_METHODS:
        return True
    if any(term in detail_norm for term in ("single source", "direct", "sole source", "restricted")):
        return True
    return tenderer_count == 1


def _is_emergency(method: str, method_details: str) -> bool:
    x = f"{method or ''} {method_details or ''}".strip().lower()
    return "emergency" in x


def _is_near_threshold(amount_ksh: float) -> bool:
    amount = max(0.0, float(amount_ksh or 0.0))
    if amount <= 0:
        return False
    for threshold in PPRA_THRESHOLD_LEVELS:
        if threshold * 0.90 <= amount < threshold:
            return True
    return False


def _iter_flat_rows(path: str) -> Iterator[Dict[str, Any]]:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".csv":
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(row for row in f if not row.startswith("#"))
            for row in reader:
                if row:
                    yield dict(row)
        return
    if suffix in {".jsonl", ".ndjson"}:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    row = json.loads(s)
                    if isinstance(row, dict):
                        yield row
        return
    payload = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                yield row
        return
    if isinstance(payload, dict):
        rows = payload.get("records") or payload.get("results") or payload.get("releases")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    yield row
            return
    raise ValueError(f"unsupported OCDS input format: {path}")


def normalize_procurement_row(row: Mapping[str, Any]) -> Optional[ProcurementRecord]:
    buyer_name = str(_pick(row, "buyer_name", "buyer_name_en", "buyer_legal_name", "buyer") or "").strip()
    buyer_id = str(_pick(row, "buyer_id", "buyer_identifier_id", "buyer_identifier_scheme") or buyer_name).strip()
    supplier_name = str(
        _pick(
            row,
            "supplier_name",
            "award_supplier_name",
            "awards_0_suppliers_0_name",
            "contracts_0_suppliers_0_name",
            "supplier",
        )
        or ""
    ).strip()
    supplier_id = str(
        _pick(
            row,
            "supplier_id",
            "award_supplier_id",
            "awards_0_suppliers_0_id",
            "awards_0_suppliers_0_identifier_id",
            "contracts_0_suppliers_0_id",
        )
        or supplier_name
    ).strip()
    tender_id = str(_pick(row, "tender_id", "ocid", "compiled_release_ocid", "id") or "").strip()
    ocid = str(_pick(row, "ocid", "compiled_release_ocid", "release_id", "id") or tender_id).strip()
    occurred_at = _parse_dt(
        _pick(
            row,
            "award_date",
            "awards_0_date",
            "contracts_0_datesigned",
            "date",
            "release_date",
            "tender_date",
        )
    )
    if not all([buyer_id, supplier_id, tender_id, occurred_at]):
        return None

    amount_ksh = _as_float(
        _pick(
            row,
            "award_value_amount",
            "awards_0_value_amount",
            "contracts_0_value_amount",
            "amount",
        )
    )
    if amount_ksh is None:
        return None

    registration_dt = _parse_dt(
        _pick(
            row,
            "supplier_registration_date",
            "awards_0_suppliers_0_registration_date",
            "parties_0_details_registration_date",
        )
    )
    method = str(_pick(row, "procurement_method", "tender_procurement_method", "tender_procurementmethod") or "").strip()
    method_details = str(
        _pick(row, "procurement_method_details", "tender_procurement_method_details", "tender_procurementmethoddetails")
        or ""
    ).strip()
    cluster_parts = [
        str(_pick(row, "supplier_email", "awards_0_suppliers_0_contact_email") or "").strip().lower(),
        str(_pick(row, "supplier_phone", "awards_0_suppliers_0_contact_phone") or "").strip().lower(),
        str(_pick(row, "supplier_address", "awards_0_suppliers_0_address_streetaddress") or "").strip().lower(),
        str(_pick(row, "supplier_tax_id", "awards_0_suppliers_0_identifier_id") or "").strip().lower(),
    ]
    cluster_parts = [part for part in cluster_parts if part]
    cluster_key = "|".join(cluster_parts[:2]) if cluster_parts else None

    return ProcurementRecord(
        ocid=ocid,
        occurred_at=occurred_at,
        buyer_id=buyer_id,
        buyer_name=buyer_name or buyer_id,
        tender_id=tender_id,
        tender_title=str(_pick(row, "tender_title", "title", "tender_description") or "").strip(),
        supplier_id=supplier_id,
        supplier_name=supplier_name or supplier_id,
        contract_id=str(_pick(row, "contract_id", "contracts_0_id") or "").strip() or None,
        award_id=str(_pick(row, "award_id", "awards_0_id") or "").strip() or None,
        amount_ksh=float(amount_ksh),
        estimated_amount_ksh=_as_float(_pick(row, "estimated_amount", "tender_value_amount", "budget_amount")),
        payment_amount_ksh=_as_float(_pick(row, "payment_amount", "implementation_transactions_0_value_amount")),
        advance_payment_ksh=_as_float(_pick(row, "advance_payment_amount", "advance_amount")),
        procurement_method=method,
        procurement_method_details=method_details,
        tenderer_count=_as_int(_pick(row, "tenderer_count", "number_of_tenderers", "tender_number_of_tenderers")),
        supplier_registered_at=registration_dt,
        supplier_cluster_key=cluster_key,
        audit_flag=_as_bool(_pick(row, "audit_flag", "ppra_flag", "flagged", "review_required")),
        amendment_count=_as_int(_pick(row, "amendment_count", "contracts_0_amendments_count")) or 0,
        amended_amount_ksh=_as_float(_pick(row, "amended_amount", "contracts_0_implementation_finalvalue_amount")),
        project_id=str(_pick(row, "project_id", "planning_project_id") or "").strip() or None,
        project_title=str(_pick(row, "project_title", "planning_project_title") or "").strip() or None,
    )


def load_procurement_records(input_file: str) -> List[ProcurementRecord]:
    out: List[ProcurementRecord] = []
    for row in _iter_flat_rows(input_file):
        record = normalize_procurement_row(row)
        if record is not None:
            out.append(record)
    return out


def _ensure_source(db) -> None:
    stmt = pg_insert(SourceRegistry).values(
        source_id=PPRA_SOURCE_ID,
        source_type="gov",
        section_code="economy",
        classification_level=PPRA_CLASSIFICATION,
        api_key_hash=hash_api_key(PPRA_API_KEY),
        api_key_lookup=_key_lookup_hash(PPRA_API_KEY),
        is_active=True,
    ).on_conflict_do_nothing(index_elements=["source_id"])
    db.execute(stmt)
    db.flush()


def _event_hash(*parts: str) -> str:
    return "ocds:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:56]


def _upsert_event(db, *, event_type: str, entity_keys: Sequence[str], occurred_at: datetime, payload: Dict[str, Any], idx: int) -> str:
    event_hash = _event_hash(event_type, *sorted(entity_keys), occurred_at.isoformat(), str(idx))
    anchors = {
        key.split(":", 1)[0]: key.split(":", 1)[1]
        for key in entity_keys
        if ":" in key
    }
    stmt = pg_insert(EventLog).values(
        event_hash=event_hash,
        event_type=event_type,
        source_id=PPRA_SOURCE_ID,
        section_code="economy",
        classification=PPRA_CLASSIFICATION,
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


def _touch_entity(
    entity_map: Dict[str, EntityAccumulator],
    *,
    entity_key: str,
    entity_type: str,
    occurred_at: datetime,
    event_type: str,
    amount_ksh: float,
    counterparty_keys: Sequence[str],
    risk_flags: Sequence[str],
    related_party: bool,
    single_source: bool,
    threshold_split: bool,
    payment_amount_ksh: float = 0.0,
) -> None:
    row = entity_map.setdefault(entity_key, EntityAccumulator(entity_key=entity_key, entity_type=entity_type))
    row.event_count += 1
    row.corruption_events[event_type] += 1
    row.total_value_ksh += max(0.0, float(amount_ksh or 0.0))
    row.payment_amount_ksh += max(0.0, float(payment_amount_ksh or 0.0))
    if related_party:
        row.related_party_amount_ksh += max(0.0, float(amount_ksh or 0.0))
    if occurred_at.month in {5, 6}:
        row.fy_end_event_count += 1
    if event_type in {"TENDER_AWARD", "SINGLE_SOURCE_AWARD", "EMERGENCY_PROCUREMENT"}:
        row.award_like_count += 1
    if threshold_split:
        row.threshold_split_hits += 1
    if single_source:
        row.single_source_count += 1
    if event_type == "TENDER_AMENDMENT":
        row.amendment_count += 1
    row.risk_flags.update(str(flag) for flag in risk_flags if str(flag))
    if row.first_seen is None or occurred_at < row.first_seen:
        row.first_seen = occurred_at
    if row.last_seen is None or occurred_at > row.last_seen:
        row.last_seen = occurred_at

    for counterparty in counterparty_keys:
        if counterparty and counterparty != entity_key:
            row.counterparty_keys.add(counterparty)
            row.counterparty_amounts[counterparty] = row.counterparty_amounts.get(counterparty, 0.0) + max(0.0, float(amount_ksh or 0.0))


def _snapshot_row(row: EntityAccumulator, *, window_start: datetime, window_end: datetime) -> Dict[str, Any]:
    total_value = max(0.0, float(row.total_value_ksh))
    concentration_ratio = 0.0
    if total_value > 0.0 and row.counterparty_amounts:
        concentration_ratio = max(row.counterparty_amounts.values()) / total_value

    execution_rate = 1.0
    if total_value > 0.0 and row.payment_amount_ksh > 0.0:
        execution_rate = min(1.0, row.payment_amount_ksh / total_value)

    fy_end_fraction = row.fy_end_event_count / max(1, row.event_count)
    related_party_ratio = row.related_party_amount_ksh / total_value if total_value > 0.0 else 0.0
    amendment_ratio = row.amendment_count / max(1, row.corruption_events.get("TENDER_AWARD", 0))
    threshold_splitting = row.threshold_split_hits / max(1, row.award_like_count)
    age_sec = max(0.0, (window_end - (row.last_seen or window_end)).total_seconds())

    return {
        "id": uuid.uuid4(),
        "entity_key": row.entity_key,
        "entity_type": row.entity_type,
        "window_key": CORRUPTION_WINDOW_KEY,
        "window_start": window_start,
        "window_end": window_end,
        "degree": len(row.counterparty_keys),
        "weighted_degree": max(len(row.counterparty_keys), row.event_count),
        "event_count": row.event_count,
        "first_seen": row.first_seen,
        "last_seen": row.last_seen,
        "risk_flags": sorted(row.risk_flags),
        "features": {
            "transaction_count": row.event_count,
            "counterparty_count": len(row.counterparty_keys),
            "total_value_ksh": round(total_value, 2),
            "corruption_events": dict(row.corruption_events),
            "last_seen_age_sec": age_sec,
            "fy_end_event_fraction": round(fy_end_fraction, 6),
            "related_party_ratio": round(min(1.0, related_party_ratio), 6),
            "amendment_ratio": round(min(1.0, amendment_ratio), 6),
            "execution_rate": round(min(1.0, execution_rate), 6),
            "concentration_ratio": round(min(1.0, concentration_ratio), 6),
            "threshold_splitting": round(min(1.0, threshold_splitting), 6),
            "single_source": bool(row.single_source_count > 0),
        },
        "created_at": _utcnow(),
    }


def ingest_procurement_records(
    *,
    records: Sequence[ProcurementRecord],
    max_records: Optional[int] = None,
) -> Dict[str, Any]:
    if max_records is not None:
        records = list(records)[: max(0, int(max_records))]
    if not records:
        return {"status": "no_data", "records": 0, "events": 0, "snapshots": 0}

    cluster_members: Dict[str, set[str]] = {}
    for record in records:
        if record.supplier_cluster_key:
            cluster_members.setdefault(record.supplier_cluster_key, set()).add(record.supplier_id)

    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=engine)
        _ensure_source(db)

        entity_map: Dict[str, EntityAccumulator] = {}
        event_count = 0
        window_start = min(record.occurred_at for record in records)
        window_end = max(record.occurred_at for record in records)

        for idx, record in enumerate(records):
            department_key = _entity_key("department", record.buyer_id)
            tender_key = _entity_key("tender", record.tender_id or record.ocid)
            supplier_key = _entity_key("supplier", record.supplier_id)
            contract_key = _entity_key("contract", record.contract_id or f"{record.tender_id}-contract")
            entities = [department_key, tender_key, supplier_key, contract_key]

            project_key = None
            if record.project_id or record.project_title:
                project_key = _entity_key("project", record.project_id or record.project_title or record.ocid)
                entities.append(project_key)

            cluster_shared = bool(
                record.supplier_cluster_key
                and len(cluster_members.get(record.supplier_cluster_key, set())) > 1
            )
            price_inflated = bool(
                record.estimated_amount_ksh
                and record.estimated_amount_ksh > 0
                and record.amount_ksh >= record.estimated_amount_ksh * 1.25
            )
            amendment_inflated = bool(
                record.amended_amount_ksh
                and record.amended_amount_ksh > record.amount_ksh * 1.20
            )
            shell_company = bool(
                record.supplier_registered_at
                and (record.occurred_at - record.supplier_registered_at).days <= 180
                and record.amount_ksh >= 1_000_000.0
            )
            single_source = _is_single_source(
                record.procurement_method,
                record.procurement_method_details,
                record.tenderer_count,
            )
            emergency = _is_emergency(record.procurement_method, record.procurement_method_details)
            threshold_split = _is_near_threshold(record.amount_ksh)

            risk_flags = set()
            if cluster_shared:
                risk_flags.add("DIRECTOR_CONFLICT")
                risk_flags.add("RELATED_PARTY_TRANSACTION")
            if price_inflated or amendment_inflated:
                risk_flags.add("PRICE_INFLATION")
            if shell_company:
                risk_flags.add("SHELL_COMPANY")
            if record.audit_flag:
                risk_flags.add("AUDIT_FINDING")

            payload = {
                "ocid": record.ocid,
                "buyer_name": record.buyer_name,
                "supplier_name": record.supplier_name,
                "tender_title": record.tender_title,
                "amount_ksh": round(record.amount_ksh, 2),
                "procurement_method": record.procurement_method,
                "procurement_method_details": record.procurement_method_details,
            }
            _upsert_event(
                db,
                event_type="TENDER_AWARD",
                entity_keys=entities,
                occurred_at=record.occurred_at,
                payload=payload,
                idx=idx,
            )
            event_count += 1

            extra_event_types: List[str] = []
            if single_source:
                extra_event_types.append("SINGLE_SOURCE_AWARD")
            if emergency:
                extra_event_types.append("EMERGENCY_PROCUREMENT")
            if record.amendment_count > 0 or amendment_inflated:
                extra_event_types.append("TENDER_AMENDMENT")
            if record.payment_amount_ksh and record.payment_amount_ksh > 0:
                extra_event_types.append("PAYMENT_DISBURSEMENT")
            if record.advance_payment_ksh and record.advance_payment_ksh > 0:
                extra_event_types.append("ADVANCE_PAYMENT")
            if record.supplier_registered_at:
                extra_event_types.append("COMPANY_REGISTRATION")
            if record.audit_flag:
                extra_event_types.append("AUDIT_FINDING_EVENT")

            for offset, event_type in enumerate(extra_event_types, start=1):
                event_entities = entities if event_type != "COMPANY_REGISTRATION" else [supplier_key]
                _upsert_event(
                    db,
                    event_type=event_type,
                    entity_keys=event_entities,
                    occurred_at=record.occurred_at,
                    payload=payload,
                    idx=idx + offset,
                )
                event_count += 1

            entity_types = {
                department_key: "department",
                tender_key: "tender",
                supplier_key: "supplier",
                contract_key: "contract",
            }
            if project_key:
                entity_types[project_key] = "project"

            for entity_key, entity_type in entity_types.items():
                _touch_entity(
                    entity_map,
                    entity_key=entity_key,
                    entity_type=entity_type,
                    occurred_at=record.occurred_at,
                    event_type="TENDER_AWARD",
                    amount_ksh=record.amount_ksh,
                    counterparty_keys=[key for key in entities if key != entity_key],
                    risk_flags=sorted(risk_flags),
                    related_party=cluster_shared,
                    single_source=single_source,
                    threshold_split=threshold_split,
                )
                for event_type in extra_event_types:
                    if event_type == "COMPANY_REGISTRATION" and entity_key != supplier_key:
                        continue
                    _touch_entity(
                        entity_map,
                        entity_key=entity_key,
                        entity_type=entity_type,
                        occurred_at=record.occurred_at,
                        event_type=event_type,
                        amount_ksh=record.amount_ksh,
                        counterparty_keys=[key for key in entities if key != entity_key],
                        risk_flags=sorted(risk_flags),
                        related_party=cluster_shared,
                        single_source=single_source,
                        threshold_split=threshold_split,
                        payment_amount_ksh=float(record.payment_amount_ksh or 0.0) if event_type == "PAYMENT_DISBURSEMENT" else 0.0,
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
        description="Ingest flat OCDS/PPRA procurement rows into corruption-domain event and snapshot tables.",
    )
    parser.add_argument("--input-file", required=True, help="Flat CSV/JSON/JSONL procurement extract.")
    parser.add_argument("--max-records", type=int, default=None, help="Optional cap for development runs.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    records = load_procurement_records(args.input_file)
    result = ingest_procurement_records(records=records, max_records=args.max_records)
    print(json.dumps(result))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
