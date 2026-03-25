from __future__ import annotations

import argparse
import json
import logging
from typing import Any, List, Mapping, Optional, Sequence

from app.analytics.corruption.ocds_ingest import _as_float, _iter_flat_rows, _parse_dt, _pick
from app.analytics.corruption.outcome_ingest import OutcomeRecord, ingest_outcome_records

log = logging.getLogger("sentinel.corruption.public_case_outcome_ingest")


def _status_from_text(text: str) -> str:
    x = (text or "").strip().lower()
    if any(term in x for term in ("convict", "liable", "guilty", "upheld", "judgment for", "recovery ordered")):
        return "confirmed"
    if any(term in x for term in ("acquit", "dismiss", "not guilty", "withdrawn", "struck out")):
        return "dismissed"
    return "under_review"


def normalize_kenyalaw_row(row: Mapping[str, Any]) -> Optional[OutcomeRecord]:
    case_id = str(_pick(row, "case_id", "case_number", "citation", "reference_no") or "").strip()
    occurred_at = _parse_dt(_pick(row, "decision_date", "date", "judgment_date", "published_at"))
    title = str(_pick(row, "title", "case_title", "name") or "").strip()
    department = str(_pick(row, "department_name", "agency_name", "ministry_name", "court_division") or "").strip()
    if not all([case_id, occurred_at, title]):
        return None
    summary = str(_pick(row, "summary", "holding", "disposition", "outcome") or "").strip()
    department_name = department or "Kenya Law linked agency"
    department_id = str(_pick(row, "department_id", "agency_id", "ministry_id") or department_name).strip()
    supplier_name = str(_pick(row, "supplier_name", "company_name", "respondent_name") or "").strip() or None
    official_name = str(_pick(row, "official_name", "accused_name", "defendant_name") or "").strip() or None
    official_id = official_name or None
    status = _status_from_text(f"{title} {summary}")
    return OutcomeRecord(
        outcome_id=f"kenyalaw:{case_id}",
        case_id=case_id,
        occurred_at=occurred_at,
        department_id=department_id,
        department_name=department_name,
        supplier_id=supplier_name or None,
        supplier_name=supplier_name,
        official_id=official_id,
        contract_id=str(_pick(row, "contract_id", "contract_no", "tender_ref") or "").strip() or None,
        project_id=str(_pick(row, "project_id", "project_code") or "").strip() or None,
        project_title=str(_pick(row, "project_title", "project_name") or "").strip() or None,
        finding_type="kenyalaw_judgment",
        outcome_status=status,
        sanction_type=str(_pick(row, "sanction_type", "order_type") or "").strip() or None,
        loss_amount_ksh=_as_float(_pick(row, "loss_amount_ksh", "loss_amount", "exposure_amount")),
        recovery_amount_ksh=_as_float(_pick(row, "recovery_amount_ksh", "recovered_amount", "recovery_amount")),
        source_system="kenyalaw",
    )


def normalize_eacc_row(row: Mapping[str, Any]) -> Optional[OutcomeRecord]:
    case_id = str(_pick(row, "case_id", "reference_no", "case_number", "record_id") or "").strip()
    occurred_at = _parse_dt(_pick(row, "decision_date", "date", "published_at", "updated_at"))
    title = str(_pick(row, "title", "case_title", "headline") or "").strip()
    if not all([case_id, occurred_at, title]):
        return None
    summary = str(_pick(row, "summary", "description", "outcome") or "").strip()
    department_name = str(_pick(row, "department_name", "agency_name", "ministry_name") or "EACC-linked agency").strip()
    department_id = str(_pick(row, "department_id", "agency_id", "ministry_id") or department_name).strip()
    supplier_name = str(_pick(row, "supplier_name", "company_name") or "").strip() or None
    official_name = str(_pick(row, "official_name", "accused_name", "respondent_name") or "").strip() or None
    status = _status_from_text(f"{title} {summary}")
    sanction = str(_pick(row, "sanction_type", "penalty_type", "order_type") or "").strip() or None
    if not sanction and status == "confirmed":
        sanction = "anti_corruption_judgment"
    return OutcomeRecord(
        outcome_id=f"eacc:{case_id}",
        case_id=case_id,
        occurred_at=occurred_at,
        department_id=department_id,
        department_name=department_name,
        supplier_id=supplier_name or None,
        supplier_name=supplier_name,
        official_id=official_name or None,
        contract_id=str(_pick(row, "contract_id", "contract_no", "tender_ref") or "").strip() or None,
        project_id=str(_pick(row, "project_id", "project_code") or "").strip() or None,
        project_title=str(_pick(row, "project_title", "project_name") or "").strip() or None,
        finding_type="eacc_case_outcome",
        outcome_status=status,
        sanction_type=sanction,
        loss_amount_ksh=_as_float(_pick(row, "loss_amount_ksh", "loss_amount", "asset_value")),
        recovery_amount_ksh=_as_float(_pick(row, "recovery_amount_ksh", "recovered_amount", "recovery_amount")),
        source_system="eacc",
    )


def load_public_case_outcome_records(input_file: str, *, source: str) -> List[OutcomeRecord]:
    source_norm = source.strip().lower()
    out: List[OutcomeRecord] = []
    for row in _iter_flat_rows(input_file):
        if source_norm == "kenyalaw":
            record = normalize_kenyalaw_row(row)
        elif source_norm == "eacc":
            record = normalize_eacc_row(row)
        else:
            raise ValueError(f"unsupported public outcome source '{source}'")
        if record is not None:
            out.append(record)
    return out


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest Kenya Law or EACC case outcomes into corruption outcomes.")
    parser.add_argument("--source", choices=("kenyalaw", "eacc"), required=True, help="Public outcome source family.")
    parser.add_argument("--input-file", required=True, help="Flat CSV/JSON/JSONL export file.")
    parser.add_argument("--max-records", type=int, default=None, help="Optional cap for development runs.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    records = load_public_case_outcome_records(args.input_file, source=args.source)
    result = ingest_outcome_records(records=records, max_records=args.max_records)
    print(json.dumps(result))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
