from __future__ import annotations

import argparse
import json
import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.analytics.corruption.ocds_ingest import (
    ProcurementRecord,
    _iter_flat_rows,
    _pick,
    ingest_procurement_records,
    normalize_procurement_row,
)

log = logging.getLogger("sentinel.corruption.ppra_awards_ingest")


def _map_awards_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "ocid": _pick(row, "ocid", "award_notice_no", "award_number", "contract_award_no", "reference_no"),
        "award_id": _pick(row, "award_id", "award_notice_no", "award_number"),
        "contract_id": _pick(row, "contract_id", "contract_no", "contract_number"),
        "award_date": _pick(row, "award_date", "date_of_award", "contract_award_date", "date"),
        "buyer_id": _pick(row, "buyer_id", "procuring_entity_id", "entity_code", "pe_code"),
        "buyer_name": _pick(row, "buyer_name", "procuring_entity", "procuring_entity_name", "entity_name"),
        "tender_id": _pick(row, "tender_id", "tender_no", "tender_number", "tender_reference", "reference_no"),
        "tender_title": _pick(row, "tender_title", "description", "tender_description", "procurement_title"),
        "supplier_id": _pick(row, "supplier_id", "awardee_id", "vendor_id", "supplier_pin", "kra_pin"),
        "supplier_name": _pick(row, "supplier_name", "awardee_name", "supplier", "contractor", "vendor_name"),
        "award_value_amount": _pick(row, "award_value_amount", "contract_sum", "contract_amount", "award_amount", "amount_ksh"),
        "tender_value_amount": _pick(row, "tender_value_amount", "estimated_cost", "estimated_amount", "budget_amount"),
        "procurement_method": _pick(row, "procurement_method", "method"),
        "procurement_method_details": _pick(row, "procurement_method_details", "method_details", "procurement_category"),
        "tenderer_count": _pick(row, "tenderer_count", "number_of_bidders", "number_of_tenderers", "bidders"),
        "project_id": _pick(row, "project_id", "project_code", "ifmis_project_id"),
        "project_title": _pick(row, "project_title", "project_name", "project"),
        "supplier_tax_id": _pick(row, "supplier_tax_id", "kra_pin", "supplier_pin"),
        "supplier_bank_account": _pick(row, "supplier_bank_account", "bank_account", "supplier_account"),
        "beneficial_owner_id": _pick(row, "beneficial_owner_id", "director_id", "supplier_director_id"),
        "site_inspector_id": _pick(row, "site_inspector_id", "inspector_id"),
        "certificate_id": _pick(row, "certificate_id", "milestone_id"),
        "delivery_progress_pct": _pick(row, "delivery_progress_pct", "completion_pct"),
        "certified_progress_pct": _pick(row, "certified_progress_pct", "certified_pct"),
        "complaint_count": _pick(row, "complaint_count", "complaints"),
        "quality_failure_count": _pick(row, "quality_failure_count", "defects", "quality_failures"),
        "delay_days": _pick(row, "delay_days", "days_delayed"),
        "supplier_debarred": _pick(row, "supplier_debarred", "debarred", "blacklisted"),
        "delivery_status": _pick(row, "delivery_status", "status"),
    }


def normalize_ppra_awards_row(row: Mapping[str, Any]) -> Optional[ProcurementRecord]:
    return normalize_procurement_row(_map_awards_row(row))


def load_ppra_awards_records(input_file: str) -> List[ProcurementRecord]:
    out: List[ProcurementRecord] = []
    for row in _iter_flat_rows(input_file):
        record = normalize_ppra_awards_row(row)
        if record is not None:
            out.append(record)
    return out


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest PPRA contract-award exports into corruption-domain graph tables.",
    )
    parser.add_argument("--input-file", required=True, help="Flat CSV/JSON/JSONL PPRA contract-award export.")
    parser.add_argument("--max-records", type=int, default=None, help="Optional cap for development runs.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    records = load_ppra_awards_records(args.input_file)
    result = ingest_procurement_records(records=records, max_records=args.max_records)
    print(json.dumps(result))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
