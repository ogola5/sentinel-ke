"""
VPN benchmark ingestor (layer3) — ISCX VPN-nonVPN and CIC-IDS2017.

Reads a CSV, classifies flows as VPN or nonVPN, aggregates per source IP,
and writes GraphFeatureSnapshot rows (window_key="Wvpn").

VPN flows get risk_flags=["VPN_CLUSTER_MEMBER"].
nonVPN flows get risk_flags=[] (negative training signal).

Usage:
    python -m app.analytics.layer3.vpn_benchmark_ingest --input-file /data/iscx_vpn.csv
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

import app.db.registry  # noqa: F401
from app.analytics.ai_models import GraphFeatureSnapshot
from app.db.base import Base
from app.ledger.db import SessionLocal, engine

log = logging.getLogger("sentinel.layer3.vpn_benchmark_ingest")

_WINDOW_KEY = "Wvpn"

# ---------------------------------------------------------------------------
# Row normalisation
# ---------------------------------------------------------------------------

def _get(row: Dict[str, str], *keys: str) -> str:
    """Case-insensitive key lookup across column names."""
    for k in keys:
        for rk, rv in row.items():
            if rk.strip().lower() == k.strip().lower():
                return str(rv or "").strip()
    return ""


def _is_vpn_flow(row: Dict[str, str]) -> bool:
    """Return True when a row represents VPN traffic."""
    label = _get(row, "label", "category", "traffic_type", "class", "Label").lower()
    vpn_flag = _get(row, "vpn", "is_vpn", "vpn_label").lower()
    app_label = _get(row, "app_label", "application", "app", "service").lower()

    if vpn_flag in {"1", "true", "yes", "vpn"}:
        return True
    # Use exact token match to avoid "vpn" matching inside "nonvpn"
    label_tokens = set(label.replace("-", " ").replace("_", " ").split())
    if "vpn" in label_tokens or "tor" in label_tokens:
        return True
    app_tokens = set(app_label.replace("-", " ").replace("_", " ").split())
    if "vpn" in app_tokens:
        return True
    return False


def normalise_vpn_row(row: Dict[str, str]) -> Optional[Tuple[str, bool, float, float, float]]:
    """
    Return (src_ip, is_vpn, byte_volume, duration_ms, conn_count) or None.
    """
    src = _get(row, "src_ip", "source_ip", "ip", "src", "Source IP", "srcip")
    if not src:
        return None

    is_vpn = _is_vpn_flow(row)

    try:
        byte_fwd = float(_get(row, "Total Fwd Packets", "tot_fwd_pkts", "sbytes", "flow_byts_s") or 0)
    except ValueError:
        byte_fwd = 0.0
    try:
        byte_bwd = float(_get(row, "Total Backward Packets", "tot_bwd_pkts", "dbytes") or 0)
    except ValueError:
        byte_bwd = 0.0
    byte_volume = byte_fwd + byte_bwd

    try:
        duration = float(_get(row, "Flow Duration", "duration", "dur", "flow_duration") or 0)
    except ValueError:
        duration = 0.0

    return src, is_vpn, byte_volume, duration, 1.0


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def aggregate_rows(
    path: str,
) -> Dict[str, Dict[str, Any]]:
    """
    Read CSV at *path* and aggregate per source IP.

    Returns {entity_key: stats_dict}.
    """
    file_path = Path(path)
    stats: Dict[str, Dict[str, Any]] = {}

    with file_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = normalise_vpn_row(row)
            if parsed is None:
                continue
            src_ip, is_vpn, byte_volume, duration, _ = parsed
            ek = f"ip:{src_ip}"
            if ek not in stats:
                stats[ek] = {
                    "src_ip": src_ip,
                    "conn_count": 0,
                    "vpn_count": 0,
                    "nonvpn_count": 0,
                    "total_bytes": 0.0,
                    "total_duration_ms": 0.0,
                    "min_duration": float("inf"),
                    "max_duration": 0.0,
                }
            s = stats[ek]
            s["conn_count"] += 1
            s["total_bytes"] += byte_volume
            s["total_duration_ms"] += duration
            if duration < s["min_duration"]:
                s["min_duration"] = duration
            if duration > s["max_duration"]:
                s["max_duration"] = duration
            if is_vpn:
                s["vpn_count"] += 1
            else:
                s["nonvpn_count"] += 1

    # Normalise min_duration sentinel
    for s in stats.values():
        if s["min_duration"] == float("inf"):
            s["min_duration"] = 0.0

    return stats


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def run_ingest(
    db: Session,
    *,
    csv_path: str,
    max_records: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Aggregate a VPN benchmark CSV and write GraphFeatureSnapshot rows.
    """
    Base.metadata.create_all(bind=engine)

    stats = aggregate_rows(csv_path)

    now = datetime.now(timezone.utc)
    snap_rows = []

    items = list(stats.items())
    if max_records is not None:
        items = items[: max(0, int(max_records))]

    for entity_key, s in items:
        # An IP is flagged VPN if the majority of its flows are VPN
        vpn_ratio = s["vpn_count"] / max(1, s["conn_count"])
        is_vpn_entity = s["vpn_count"] > 0
        risk_flags: List[str] = ["VPN_CLUSTER_MEMBER"] if is_vpn_entity else []

        avg_duration = s["total_duration_ms"] / max(1, s["conn_count"])

        snap_rows.append(
            {
                "entity_key": entity_key,
                "entity_type": "ip",
                "window_key": _WINDOW_KEY,
                "window_start": now,
                "window_end": now,
                "degree": s["conn_count"],
                "weighted_degree": s["conn_count"],
                "event_count": s["conn_count"],
                "first_seen": now,
                "last_seen": now,
                "risk_flags": risk_flags,
                "features": {
                    "conn_count": s["conn_count"],
                    "vpn_count": s["vpn_count"],
                    "nonvpn_count": s["nonvpn_count"],
                    "vpn_ratio": round(vpn_ratio, 4),
                    "total_bytes": s["total_bytes"],
                    "avg_duration_ms": round(avg_duration, 2),
                    "min_duration_ms": s["min_duration"],
                    "max_duration_ms": s["max_duration"],
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
        "snapshots": len(snap_rows),
        "total_source_ips": len(stats),
        "vpn_ips": sum(1 for s in stats.values() if s["vpn_count"] > 0),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Ingest VPN benchmark CSV (ISCX VPN-nonVPN / CIC-IDS2017) into graph feature snapshots."
    )
    parser.add_argument("--input-file", required=True, help="Path to CSV file.")
    parser.add_argument("--max-records", type=int, default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = run_ingest(db, csv_path=args.input_file, max_records=args.max_records)
        print(json.dumps(result))
    finally:
        db.close()


if __name__ == "__main__":
    main()
