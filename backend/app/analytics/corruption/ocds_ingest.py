from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
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
from app.analytics.corruption.feature_builder import CORRUPTION_EVENT_TYPES, CORRUPTION_WINDOW_KEY
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
    supplier_director_id: Optional[str]
    supplier_bank_account: Optional[str]
    inspector_id: Optional[str]
    milestone_id: Optional[str]
    delivery_progress_pct: Optional[float]
    certified_progress_pct: Optional[float]
    complaint_count: int
    quality_failure_count: int
    delay_days: int
    supplier_debarred: bool
    delivery_status: Optional[str]


@dataclass(frozen=True)
class ProcurementSignals:
    cluster_shared: bool
    family_size: int
    price_inflated: bool
    amendment_inflated: bool
    shell_company: bool
    single_source: bool
    emergency: bool
    threshold_split: bool
    supplier_debarred: bool
    project_delay: bool
    complaints_active: bool
    quality_failure: bool
    delivery_mismatch: bool
    accepted_delivery: bool
    risk_flags: tuple[str, ...]
    extra_event_types: tuple[str, ...]
    progress_mismatch: float
    execution_rate: float
    payment_to_delivery_ratio: float


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
    complaint_count: int = 0
    quality_failure_count: int = 0
    delay_days_max: int = 0
    inspection_count: int = 0
    supplier_family_size: int = 0
    payment_to_delivery_ratio_max: float = 0.0
    progress_mismatch_max: float = 0.0
    delivery_progress_total: float = 0.0
    delivery_progress_points: int = 0
    certified_progress_total: float = 0.0
    certified_progress_points: int = 0
    adverse_outcome_count: int = 0
    sanction_event_count: int = 0
    recovery_amount_ksh: float = 0.0
    outcome_label: Optional[int] = None


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


def _as_pct(value: Any) -> Optional[float]:
    raw = _as_float(value)
    if raw is None:
        return None
    if raw > 1.0:
        raw = raw / 100.0
    return max(0.0, min(1.0, float(raw)))


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


def _build_supplier_cluster_key(row: Mapping[str, Any]) -> Optional[str]:
    tax_id = str(_pick(row, "supplier_tax_id", "awards_0_suppliers_0_identifier_id", "kra_pin") or "").strip().lower()
    bank_account = str(_pick(row, "supplier_bank_account", "bank_account", "supplier_account") or "").strip().lower()
    email = str(_pick(row, "supplier_email", "awards_0_suppliers_0_contact_email") or "").strip().lower()
    phone = str(_pick(row, "supplier_phone", "awards_0_suppliers_0_contact_phone") or "").strip().lower()
    address = str(_pick(row, "supplier_address", "awards_0_suppliers_0_address_streetaddress") or "").strip().lower()

    strong_parts = [part for part in [tax_id, bank_account] if part]
    weak_parts = [part for part in [email, phone, address] if part]
    if strong_parts:
        if len(strong_parts) >= 2:
            cluster_parts = strong_parts
        else:
            cluster_parts = strong_parts + weak_parts[:2]
    else:
        cluster_parts = weak_parts[:3]
    if not cluster_parts:
        return None
    return "|".join(cluster_parts[:3])


def _supplier_family_key(cluster_key: Optional[str]) -> Optional[str]:
    if not cluster_key:
        return None
    digest = hashlib.sha256(cluster_key.encode("utf-8")).hexdigest()[:24]
    return f"supplier_family:{digest}"


def _event_entities_for_type(
    *,
    event_type: str,
    base_entities: Sequence[str],
    supplier_key: str,
    supplier_family_key: Optional[str],
    director_key: Optional[str],
    account_key: Optional[str],
    inspector_key: Optional[str],
) -> List[str]:
    event_entities = list(base_entities)
    if supplier_family_key and event_type in {"SINGLE_SOURCE_AWARD", "COMPLAINT_FILED", "PROJECT_DELAY"}:
        event_entities.append(supplier_family_key)
    if director_key and event_type in {"COMPANY_REGISTRATION", "SINGLE_SOURCE_AWARD", "COMPLAINT_FILED"}:
        event_entities.append(director_key)
    if account_key and event_type in {"PAYMENT_DISBURSEMENT", "ADVANCE_PAYMENT"}:
        event_entities.append(account_key)
    if inspector_key and event_type in {"SITE_INSPECTION", "PROJECT_MILESTONE_CERTIFIED", "DELIVERY_ACCEPTANCE", "DEFECT_NOTICE"}:
        event_entities.append(inspector_key)
    if event_type == "COMPANY_REGISTRATION":
        event_entities = [supplier_key]
        if supplier_family_key:
            event_entities.append(supplier_family_key)
        if director_key:
            event_entities.append(director_key)
    return event_entities


def _event_amount_ksh(record: ProcurementRecord, *, event_type: str) -> float:
    if event_type == "TENDER_AWARD":
        return max(0.0, float(record.amount_ksh or 0.0))
    if event_type == "PAYMENT_DISBURSEMENT":
        return max(0.0, float(record.payment_amount_ksh or 0.0))
    if event_type == "ADVANCE_PAYMENT":
        return max(0.0, float(record.advance_payment_ksh or 0.0))
    if event_type == "TENDER_AMENDMENT":
        if record.amended_amount_ksh is None:
            return 0.0
        return max(0.0, float(record.amended_amount_ksh) - float(record.amount_ksh or 0.0))
    return 0.0


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


def _delivery_status_flags(status: Optional[str]) -> tuple[bool, bool]:
    s = str(status or "").strip().lower()
    if not s:
        return False, False
    accepted = any(term in s for term in ("accepted", "complete", "completed", "certified"))
    delayed = any(term in s for term in ("delay", "delayed", "stalled", "abandoned"))
    return accepted, delayed


def _derive_procurement_signals(
    record: ProcurementRecord,
    *,
    family_size: int,
) -> ProcurementSignals:
    cluster_shared = family_size > 1
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

    accepted_delivery, delayed_from_status = _delivery_status_flags(record.delivery_status)
    project_delay = bool(record.delay_days >= 30 or delayed_from_status)
    complaints_active = bool(record.complaint_count > 0)
    quality_failure = bool(record.quality_failure_count > 0)

    delivery_progress = float(record.delivery_progress_pct or 0.0)
    certified_progress = float(record.certified_progress_pct or 0.0)
    progress_mismatch = max(0.0, certified_progress - delivery_progress)
    payment_ratio = 0.0
    if record.amount_ksh > 0 and record.payment_amount_ksh:
        payment_ratio = max(0.0, float(record.payment_amount_ksh) / float(record.amount_ksh))
    payment_to_delivery_ratio = payment_ratio - delivery_progress if delivery_progress > 0 else payment_ratio
    delivery_mismatch = bool(
        progress_mismatch >= 0.25
        or payment_to_delivery_ratio >= 0.35
    )

    risk_flags: set[str] = set()
    if cluster_shared:
        risk_flags.update({"DIRECTOR_CONFLICT", "RELATED_PARTY_TRANSACTION"})
    if price_inflated or amendment_inflated:
        risk_flags.add("PRICE_INFLATION")
    if shell_company:
        risk_flags.add("SHELL_COMPANY")
    if record.audit_flag:
        risk_flags.add("AUDIT_FINDING")
    if record.supplier_debarred:
        risk_flags.add("DEBARRED_SUPPLIER")
    if quality_failure:
        risk_flags.add("QUALITY_FAILURE")
    if delivery_mismatch:
        risk_flags.add("PROJECT_DELIVERY_MISMATCH")
    if project_delay:
        risk_flags.add("PROJECT_DELAY_RISK")
    if complaints_active:
        risk_flags.add("COMPLAINT_PRESSURE")

    extra_event_types: list[str] = []
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
    if record.inspector_id or quality_failure or record.delivery_progress_pct is not None:
        extra_event_types.append("SITE_INSPECTION")
    if record.milestone_id or record.certified_progress_pct is not None:
        extra_event_types.append("PROJECT_MILESTONE_CERTIFIED")
    if accepted_delivery:
        extra_event_types.append("DELIVERY_ACCEPTANCE")
    if quality_failure:
        extra_event_types.append("DEFECT_NOTICE")
    if complaints_active:
        extra_event_types.append("COMPLAINT_FILED")
    if project_delay:
        extra_event_types.append("PROJECT_DELAY")

    return ProcurementSignals(
        cluster_shared=cluster_shared,
        family_size=family_size,
        price_inflated=price_inflated,
        amendment_inflated=amendment_inflated,
        shell_company=shell_company,
        single_source=single_source,
        emergency=emergency,
        threshold_split=threshold_split,
        supplier_debarred=bool(record.supplier_debarred),
        project_delay=project_delay,
        complaints_active=complaints_active,
        quality_failure=quality_failure,
        delivery_mismatch=delivery_mismatch,
        accepted_delivery=accepted_delivery,
        risk_flags=tuple(sorted(risk_flags)),
        extra_event_types=tuple(dict.fromkeys(extra_event_types)),
        progress_mismatch=round(progress_mismatch, 6),
        execution_rate=max(0.0, min(1.0, delivery_progress if record.delivery_progress_pct is not None else 1.0)),
        payment_to_delivery_ratio=round(max(0.0, payment_to_delivery_ratio), 6),
    )


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
    cluster_key = _build_supplier_cluster_key(row)

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
        supplier_director_id=str(_pick(row, "supplier_director_id", "beneficial_owner_id", "director_id") or "").strip() or None,
        supplier_bank_account=str(_pick(row, "supplier_bank_account", "bank_account", "supplier_account") or "").strip() or None,
        inspector_id=str(_pick(row, "inspector_id", "site_inspector_id", "engineer_id") or "").strip() or None,
        milestone_id=str(_pick(row, "milestone_id", "certificate_id", "inspection_id") or "").strip() or None,
        delivery_progress_pct=_as_pct(_pick(row, "delivery_progress_pct", "project_delivery_progress_pct", "implementation_progress_pct")),
        certified_progress_pct=_as_pct(_pick(row, "certified_progress_pct", "inspection_certified_progress_pct", "milestone_progress_pct")),
        complaint_count=_as_int(_pick(row, "complaint_count", "review_request_count", "bid_complaint_count")) or 0,
        quality_failure_count=_as_int(_pick(row, "quality_failure_count", "failed_quality_tests", "defect_count")) or 0,
        delay_days=_as_int(_pick(row, "delay_days", "project_delay_days", "slippage_days")) or 0,
        supplier_debarred=_as_bool(_pick(row, "supplier_debarred", "debarred_supplier", "blacklisted_supplier")),
        delivery_status=str(_pick(row, "delivery_status", "project_status", "completion_status") or "").strip() or None,
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
    family_size: int = 0,
    complaint_count: int = 0,
    quality_failure_count: int = 0,
    delay_days: int = 0,
    delivery_progress_pct: Optional[float] = None,
    certified_progress_pct: Optional[float] = None,
    payment_to_delivery_ratio: float = 0.0,
    progress_mismatch: float = 0.0,
    adverse_outcome: int = 0,
    sanction_event: int = 0,
    recovery_amount_ksh: float = 0.0,
    outcome_label: Optional[int] = None,
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
    if event_type == "SITE_INSPECTION":
        row.inspection_count += 1
    row.complaint_count += max(0, int(complaint_count or 0))
    row.quality_failure_count += max(0, int(quality_failure_count or 0))
    row.delay_days_max = max(row.delay_days_max, max(0, int(delay_days or 0)))
    row.supplier_family_size = max(row.supplier_family_size, max(0, int(family_size or 0)))
    row.payment_to_delivery_ratio_max = max(row.payment_to_delivery_ratio_max, max(0.0, float(payment_to_delivery_ratio or 0.0)))
    row.progress_mismatch_max = max(row.progress_mismatch_max, max(0.0, float(progress_mismatch or 0.0)))
    row.adverse_outcome_count += max(0, int(adverse_outcome or 0))
    row.sanction_event_count += max(0, int(sanction_event or 0))
    row.recovery_amount_ksh += max(0.0, float(recovery_amount_ksh or 0.0))
    if outcome_label in {0, 1}:
        row.outcome_label = int(outcome_label) if row.outcome_label is None else max(int(row.outcome_label), int(outcome_label))
    if delivery_progress_pct is not None:
        row.delivery_progress_total += max(0.0, min(1.0, float(delivery_progress_pct)))
        row.delivery_progress_points += 1
    if certified_progress_pct is not None:
        row.certified_progress_total += max(0.0, min(1.0, float(certified_progress_pct)))
        row.certified_progress_points += 1
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

    if row.delivery_progress_points > 0:
        execution_rate = row.delivery_progress_total / max(1, row.delivery_progress_points)
    elif total_value > 0.0 and row.payment_amount_ksh > 0.0:
        execution_rate = min(1.0, row.payment_amount_ksh / total_value)
    else:
        execution_rate = 1.0

    fy_end_fraction = row.fy_end_event_count / max(1, row.event_count)
    related_party_ratio = row.related_party_amount_ksh / total_value if total_value > 0.0 else 0.0
    amendment_ratio = row.amendment_count / max(1, row.corruption_events.get("TENDER_AWARD", 0))
    threshold_splitting = row.threshold_split_hits / max(1, row.award_like_count)
    age_sec = max(0.0, (window_end - (row.last_seen or window_end)).total_seconds())
    tracked_events = set(CORRUPTION_EVENT_TYPES)
    other_event_count = sum(
        count for evt, count in row.corruption_events.items() if evt not in tracked_events
    )
    corruption_events = dict(row.corruption_events)
    if other_event_count > 0:
        corruption_events["other"] = other_event_count
    avg_certified_progress = (
        row.certified_progress_total / max(1, row.certified_progress_points)
        if row.certified_progress_points > 0 else None
    )

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
            "corruption_events": corruption_events,
            "last_seen_age_sec": age_sec,
            "fy_end_event_fraction": round(fy_end_fraction, 6),
            "related_party_ratio": round(min(1.0, related_party_ratio), 6),
            "amendment_ratio": round(min(1.0, amendment_ratio), 6),
            "execution_rate": round(min(1.0, execution_rate), 6),
            "concentration_ratio": round(min(1.0, concentration_ratio), 6),
            "threshold_splitting": round(min(1.0, threshold_splitting), 6),
            "single_source": bool(row.single_source_count > 0),
            "supplier_family_size": row.supplier_family_size,
            "complaint_count": row.complaint_count,
            "quality_failure_count": row.quality_failure_count,
            "delay_days_max": row.delay_days_max,
            "inspection_count": row.inspection_count,
            "progress_mismatch_max": round(min(1.0, row.progress_mismatch_max), 6),
            "payment_to_delivery_ratio_max": round(min(4.0, row.payment_to_delivery_ratio_max), 6),
            "delivery_progress_avg": round(min(1.0, execution_rate), 6),
            "certified_progress_avg": round(min(1.0, avg_certified_progress), 6) if avg_certified_progress is not None else None,
            "adverse_outcome_count": row.adverse_outcome_count,
            "sanction_event_count": row.sanction_event_count,
            "recovery_amount_ksh": round(max(0.0, row.recovery_amount_ksh), 2),
            "outcome_label": row.outcome_label,
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

            family_size = len(cluster_members.get(record.supplier_cluster_key, set())) if record.supplier_cluster_key else 0
            signals = _derive_procurement_signals(record, family_size=family_size)

            payload = {
                "ocid": record.ocid,
                "buyer_name": record.buyer_name,
                "supplier_name": record.supplier_name,
                "tender_title": record.tender_title,
                "amount_ksh": round(record.amount_ksh, 2),
                "procurement_method": record.procurement_method,
                "procurement_method_details": record.procurement_method_details,
                "project_id": record.project_id,
                "project_title": record.project_title,
                "signals": asdict(signals),
            }

            supplier_family_key = _supplier_family_key(record.supplier_cluster_key)
            director_key = _entity_key("director", record.supplier_director_id) if record.supplier_director_id else None
            account_key = _entity_key("account", record.supplier_bank_account) if record.supplier_bank_account else None
            inspector_key = _entity_key("official", record.inspector_id) if record.inspector_id else None
            _upsert_event(
                db,
                event_type="TENDER_AWARD",
                entity_keys=entities,
                occurred_at=record.occurred_at,
                payload=payload,
                idx=idx,
            )
            event_count += 1

            network_entities = [key for key in [supplier_family_key, director_key, account_key, inspector_key] if key]
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

            if project_key and signals.delivery_mismatch:
                _upsert_event(
                    db,
                    event_type="PROJECT_DELIVERY_ALERT",
                    entity_keys=[contract_key, project_key, supplier_key, department_key],
                    occurred_at=record.occurred_at,
                    payload=payload,
                    idx=idx + 20_000,
                )
                event_count += 1

            extra_event_types = list(signals.extra_event_types)

            for offset, event_type in enumerate(extra_event_types, start=1):
                event_entities = _event_entities_for_type(
                    event_type=event_type,
                    base_entities=entities,
                    supplier_key=supplier_key,
                    supplier_family_key=supplier_family_key,
                    director_key=director_key,
                    account_key=account_key,
                    inspector_key=inspector_key,
                )
                _upsert_event(
                    db,
                    event_type=event_type,
                    entity_keys=event_entities,
                    occurred_at=record.occurred_at,
                    payload=payload,
                    idx=idx + offset,
                )
                event_count += 1

            base_entity_types = {
                department_key: "department",
                tender_key: "tender",
                supplier_key: "supplier",
                contract_key: "contract",
            }
            if project_key:
                base_entity_types[project_key] = "project"
            entity_types = dict(base_entity_types)
            if supplier_family_key:
                entity_types[supplier_family_key] = "company"
            if director_key:
                entity_types[director_key] = "director"
            if account_key:
                entity_types[account_key] = "account"
            if inspector_key:
                entity_types[inspector_key] = "official"

            for entity_key, entity_type in base_entity_types.items():
                _touch_entity(
                    entity_map,
                    entity_key=entity_key,
                    entity_type=entity_type,
                    occurred_at=record.occurred_at,
                    event_type="TENDER_AWARD",
                    amount_ksh=_event_amount_ksh(record, event_type="TENDER_AWARD"),
                    counterparty_keys=[key for key in entities if key != entity_key],
                    risk_flags=list(signals.risk_flags),
                    related_party=signals.cluster_shared,
                    single_source=signals.single_source,
                    threshold_split=signals.threshold_split,
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
                        single_source=signals.single_source,
                        threshold_split=signals.threshold_split,
                        family_size=signals.family_size,
                    )

            if project_key and signals.delivery_mismatch:
                alert_entities = [contract_key, project_key, supplier_key, department_key]
                for entity_key in alert_entities:
                    _touch_entity(
                        entity_map,
                        entity_key=entity_key,
                        entity_type=entity_types[entity_key],
                        occurred_at=record.occurred_at,
                        event_type="PROJECT_DELIVERY_ALERT",
                        amount_ksh=0.0,
                        counterparty_keys=[key for key in alert_entities if key != entity_key],
                        risk_flags=list(signals.risk_flags),
                        related_party=signals.cluster_shared,
                        single_source=signals.single_source,
                        threshold_split=signals.threshold_split,
                        family_size=signals.family_size,
                        payment_to_delivery_ratio=signals.payment_to_delivery_ratio,
                        progress_mismatch=signals.progress_mismatch,
                    )

            for event_type in extra_event_types:
                event_entities = _event_entities_for_type(
                    event_type=event_type,
                    base_entities=entities,
                    supplier_key=supplier_key,
                    supplier_family_key=supplier_family_key,
                    director_key=director_key,
                    account_key=account_key,
                    inspector_key=inspector_key,
                )
                for entity_key in event_entities:
                    _touch_entity(
                        entity_map,
                        entity_key=entity_key,
                        entity_type=entity_types[entity_key],
                        occurred_at=record.occurred_at,
                        event_type=event_type,
                        amount_ksh=_event_amount_ksh(record, event_type=event_type),
                        counterparty_keys=[key for key in event_entities if key != entity_key],
                        risk_flags=list(signals.risk_flags),
                        related_party=signals.cluster_shared,
                        single_source=signals.single_source,
                        threshold_split=signals.threshold_split,
                        payment_amount_ksh=float(record.payment_amount_ksh or 0.0) if event_type == "PAYMENT_DISBURSEMENT" else 0.0,
                        family_size=signals.family_size,
                        complaint_count=record.complaint_count if event_type == "COMPLAINT_FILED" else 0,
                        quality_failure_count=record.quality_failure_count if event_type == "DEFECT_NOTICE" else 0,
                        delay_days=record.delay_days if event_type == "PROJECT_DELAY" else 0,
                        delivery_progress_pct=record.delivery_progress_pct if event_type in {"SITE_INSPECTION", "DELIVERY_ACCEPTANCE"} else None,
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
