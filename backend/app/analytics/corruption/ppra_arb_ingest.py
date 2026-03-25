from __future__ import annotations

import argparse
import json
import logging
from typing import Any, List, Mapping, Optional, Sequence

from app.analytics.corruption.ocds_ingest import _iter_flat_rows, _pick
from app.analytics.corruption.outcome_ingest import OutcomeRecord, ingest_outcome_records
from app.analytics.corruption.ocds_ingest import _as_float, _parse_dt

log = logging.getLogger("sentinel.corruption.ppra_arb_ingest")

_ADVERSE_TERMS = ("set aside", "annul", "nullif", "cancel", "repeat evaluation", "repeat tender", "irregular")
_CLEAR_TERMS = ("dismiss", "strike out", "uphold award", "declin", "deny")


def _arb_status(row: Mapping[str, Any]) -> str:
    raw = " ".join(
        str(
            _pick(
                row,
                "decision",
                "decision_summary",
                "outcome",
                "disposition",
                "remedy",
                "orders",
                "status",
            )
            or ""
        ).strip()
        for _ in [0]
    ).lower()
    if any(term in raw for term in _ADVERSE_TERMS):
        return "adverse"
    if any(term in raw for term in _CLEAR_TERMS):
        return "dismissed"
    return "under_review"


def normalize_ppra_arb_row(row: Mapping[str, Any]) -> Optional[OutcomeRecord]:
    case_id = str(_pick(row, "case_id", "application_no", "reference_no", "arb_case_no") or "").strip()
    decision_date = _parse_dt(_pick(row, "decision_date", "date", "date_delivered", "published_at"))
    department_name = str(_pick(row, "procuring_entity", "entity_name", "buyer_name") or "").strip()
    if not all([case_id, decision_date, department_name]):
        return None

    department_id = str(_pick(row, "procuring_entity_id", "entity_code", "buyer_id") or department_name).strip()
    supplier_name = str(
        _pick(row, "supplier_name", "awardee_name", "awardee", "respondent_name", "applicant_name")
        or ""
    ).strip() or None
    supplier_id = str(
        _pick(row, "supplier_id", "awardee_id", "vendor_id", "kra_pin")
        or supplier_name
        or ""
    ).strip() or None

    outcome_status = _arb_status(row)
    remedy = str(_pick(row, "remedy", "orders", "decision_summary") or "").strip().lower()
    sanction_type = None
    if "debar" in remedy or "blacklist" in remedy:
        sanction_type = "debarment"
    elif outcome_status == "adverse":
        sanction_type = "award_set_aside"

    return OutcomeRecord(
        outcome_id=f"ppra-arb:{case_id}",
        case_id=case_id,
        occurred_at=decision_date,
        department_id=department_id,
        department_name=department_name,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        official_id=str(_pick(row, "official_id", "entity_head_id") or "").strip() or None,
        contract_id=str(_pick(row, "contract_id", "contract_no", "award_id") or "").strip() or None,
        project_id=str(_pick(row, "project_id", "project_code") or "").strip() or None,
        project_title=str(_pick(row, "project_title", "project_name") or "").strip() or None,
        finding_type="ppra_arb_decision",
        outcome_status=outcome_status,
        sanction_type=sanction_type,
        loss_amount_ksh=_as_float(_pick(row, "loss_amount_ksh", "loss_amount", "amount_in_issue")),
        recovery_amount_ksh=_as_float(_pick(row, "recovery_amount_ksh", "recovered_amount")),
        source_system="ppra_arb",
    )


def load_ppra_arb_records(input_file: str) -> List[OutcomeRecord]:
    out: List[OutcomeRecord] = []
    for row in _iter_flat_rows(input_file):
        record = normalize_ppra_arb_row(row)
        if record is not None:
            out.append(record)
    return out


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest PPRA ARB decision exports into corruption outcomes.")
    parser.add_argument("--input-file", required=True, help="Flat CSV/JSON/JSONL PPRA ARB decision export.")
    parser.add_argument("--max-records", type=int, default=None, help="Optional cap for development runs.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    records = load_ppra_arb_records(args.input_file)
    result = ingest_outcome_records(records=records, max_records=args.max_records)
    print(json.dumps(result))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
