"""
DDoS benchmark ingestor (layer3) — CIC-DDoS2019 and UNSW-NB15.

Reads a CSV, auto-detects the format from column headers, aggregates
per-source-IP, and writes GraphFeatureSnapshot rows (window_key="Wddos").

Format detection:
  CIC-DDoS2019  → expects columns: "Source IP", "Destination IP", "Label"
  UNSW-NB15     → expects columns: "srcip", "dstip", "Label" (1=attack, 0=normal)

Usage:
    python -m app.analytics.layer3.ddos_benchmark_ingest --input-file /data/cic_ddos.csv
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

import app.db.registry  # noqa: F401
from app.analytics.ai_models import GraphFeatureSnapshot
from app.db.base import Base
from app.ledger.db import SessionLocal, engine

log = logging.getLogger("sentinel.layer3.ddos_benchmark_ingest")

_WINDOW_KEY = "Wddos"

# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

_CIC_REQUIRED = {"source ip", "destination ip", "label"}
_UNSW_REQUIRED = {"srcip", "dstip", "label"}

_FORMAT_CIC = "cic_ddos2019"
_FORMAT_UNSW = "unsw_nb15"


def detect_format(headers: List[str]) -> Optional[str]:
    """Return 'cic_ddos2019', 'unsw_nb15', or None if unrecognised."""
    norm = {h.strip().lower() for h in headers}
    if _CIC_REQUIRED.issubset(norm):
        return _FORMAT_CIC
    if _UNSW_REQUIRED.issubset(norm):
        return _FORMAT_UNSW
    return None


# ---------------------------------------------------------------------------
# Row normalisation
# ---------------------------------------------------------------------------

def _norm_key(k: str) -> str:
    return k.strip().lower()


def _get(row: Dict[str, str], *keys: str) -> str:
    for k in keys:
        for rk, rv in row.items():
            if rk.strip().lower() == k.lower():
                return str(rv or "").strip()
    return ""


def normalise_cic_row(row: Dict[str, str]) -> Optional[Tuple[str, str, bool, float, float]]:
    """Return (src_ip, dst_ip, is_attack, bytes_fwd, bytes_bwd) or None."""
    src = _get(row, "Source IP", "src_ip", "source ip")
    dst = _get(row, "Destination IP", "dst_ip", "destination ip")
    label = _get(row, "Label", "label").upper()
    if not src or not dst:
        return None
    is_attack = label not in ("", "BENIGN")
    try:
        fwd = float(_get(row, "Total Length of Fwd Packets", "totlen_fwd_pkts") or 0)
    except ValueError:
        fwd = 0.0
    try:
        bwd = float(_get(row, "Total Length of Bwd Packets", "totlen_bwd_pkts") or 0)
    except ValueError:
        bwd = 0.0
    return src, dst, is_attack, fwd, bwd


def normalise_unsw_row(row: Dict[str, str]) -> Optional[Tuple[str, str, bool, float, float]]:
    """Return (src_ip, dst_ip, is_attack, sbytes, dbytes) or None."""
    src = _get(row, "srcip", "src_ip")
    dst = _get(row, "dstip", "dst_ip")
    label_raw = _get(row, "label", "attack_cat")
    if not src or not dst:
        return None
    # UNSW: label 1 = attack, 0 = normal; also accept string "attack_cat" text
    try:
        is_attack = int(float(label_raw)) == 1
    except ValueError:
        is_attack = label_raw.strip().lower() not in ("", "0", "normal", "benign")
    try:
        sbytes = float(_get(row, "sbytes") or 0)
    except ValueError:
        sbytes = 0.0
    try:
        dbytes = float(_get(row, "dbytes") or 0)
    except ValueError:
        dbytes = 0.0
    return src, dst, is_attack, sbytes, dbytes


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def aggregate_rows(
    path: str,
    *,
    fmt: Optional[str] = None,
) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    """
    Read CSV at *path*, detect format, aggregate per source IP.

    Returns (detected_format, {entity_key: stats_dict}).
    """
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        detected = fmt or detect_format(headers)
        if detected is None:
            raise ValueError(
                f"Cannot detect DDoS CSV format from headers: {headers}. "
                "Expected CIC-DDoS2019 (Source IP/Destination IP/Label) or "
                "UNSW-NB15 (srcip/dstip/Label)."
            )

        stats: Dict[str, Dict[str, Any]] = {}

        for row in reader:
            if detected == _FORMAT_CIC:
                parsed = normalise_cic_row(row)
            else:
                parsed = normalise_unsw_row(row)
            if parsed is None:
                continue
            src_ip, dst_ip, is_attack, bytes_fwd, bytes_bwd = parsed

            ek = f"ip:{src_ip}"
            if ek not in stats:
                stats[ek] = {
                    "src_ip": src_ip,
                    "event_count": 0,
                    "attack_count": 0,
                    "unique_dests": set(),
                    "total_bytes": 0.0,
                }
            s = stats[ek]
            s["event_count"] += 1
            if is_attack:
                s["attack_count"] += 1
            s["unique_dests"].add(dst_ip)
            s["total_bytes"] += bytes_fwd + bytes_bwd

    return detected, stats


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def run_ingest(
    db: Session,
    *,
    csv_path: str,
    fmt: Optional[str] = None,
    max_records: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Aggregate a DDoS benchmark CSV and write GraphFeatureSnapshot rows.
    """
    Base.metadata.create_all(bind=engine)

    detected, stats = aggregate_rows(csv_path, fmt=fmt)

    now = datetime.now(timezone.utc)
    snap_rows = []

    items = list(stats.items())
    if max_records is not None:
        items = items[: max(0, int(max_records))]

    for entity_key, s in items:
        unique_dest_count = len(s["unique_dests"])
        attack_ratio = s["attack_count"] / max(1, s["event_count"])
        risk_flags: List[str] = []
        if attack_ratio > 0.5:
            risk_flags.append("DDOS_ATTACK_SOURCE")

        snap_rows.append(
            {
                "entity_key": entity_key,
                "entity_type": "ip",
                "window_key": _WINDOW_KEY,
                "window_start": now,
                "window_end": now,
                "degree": unique_dest_count,
                "weighted_degree": s["event_count"],
                "event_count": s["event_count"],
                "first_seen": now,
                "last_seen": now,
                "risk_flags": risk_flags,
                "features": {
                    "dataset": detected,
                    "attack_count": s["attack_count"],
                    "benign_count": s["event_count"] - s["attack_count"],
                    "unique_destinations": unique_dest_count,
                    "total_bytes": s["total_bytes"],
                    "attack_ratio": round(attack_ratio, 4),
                },
                "created_at": now,
            }
        )

    if snap_rows:
        stmt = pg_insert(GraphFeatureSnapshot).values(snap_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["entity_key", "window_key", "window_end"],
            set_={
                "event_count": stmt.excluded.event_count,
                "degree": stmt.excluded.degree,
                "weighted_degree": stmt.excluded.weighted_degree,
                "risk_flags": stmt.excluded.risk_flags,
                "features": stmt.excluded.features,
            },
        )
        db.execute(stmt)
        db.commit()

    return {
        "status": "ok",
        "format": detected,
        "snapshots": len(snap_rows),
        "total_source_ips": len(stats),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Ingest DDoS benchmark CSV (CIC-DDoS2019 or UNSW-NB15) into graph feature snapshots."
    )
    parser.add_argument("--input-file", required=True, help="Path to CSV file.")
    parser.add_argument("--format", choices=(_FORMAT_CIC, _FORMAT_UNSW), default=None,
                        help="Force format. Auto-detected from headers if omitted.")
    parser.add_argument("--max-records", type=int, default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = run_ingest(db, csv_path=args.input_file, fmt=args.format, max_records=args.max_records)
        print(json.dumps(result))
    finally:
        db.close()


if __name__ == "__main__":
    main()
