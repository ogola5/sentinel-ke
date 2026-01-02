from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.analytics.anomalies import AnomalyScore
from app.analytics.ddos_windows import window_last_minutes
from app.analytics.ddos_queries import fetch_overview, fetch_timeseries
from app.analytics.ddos_indicators import robust_z, convergence_index
from app.search.opensearch import get_client
from app.search.bootstrap import ensure_events_index
from app.ledger.db import SessionLocal


def _extract(series_res: Dict[str, Any]) -> List[Dict[str, Any]]:
    buckets = (((series_res.get("aggregations") or {}).get("by_time") or {}).get("buckets")) or []
    out: List[Dict[str, Any]] = []
    for b in buckets:
        endpoints = (b.get("top_endpoints") or {}).get("buckets") or []
        endpoint_counts = [int(x.get("doc_count") or 0) for x in endpoints]
        out.append(
            {
                "ts": b.get("key_as_string"),
                "events": int((b.get("events") or {}).get("value") or 0),
                "unique_ips": int((b.get("unique_ips") or {}).get("value") or 0),
                "avg_error_rate": (b.get("avg_error_rate") or {}).get("value"),
                "avg_latency_ms": (b.get("avg_latency_ms") or {}).get("value"),
                "convergence": convergence_index(endpoint_counts),
            }
        )
    return out


def _reason_codes(score: float, spikes: float, uips: float, errors_up: bool, latency_up: bool, conv: float) -> List[str]:
    out: List[str] = []
    if spikes >= 3:
        out.append("EVENT_SPIKE")
    if uips >= 3:
        out.append("UNIQUE_IP_SPIKE")
    if errors_up:
        out.append("ERROR_RATE_UP")
    if latency_up:
        out.append("LATENCY_UP")
    if conv >= 0.5:
        out.append("ENDPOINT_CONVERGENCE")
    if not out and score <= 0.1:
        out.append("NORMAL_BASELINE")
    return out


def _flag(now_val: Optional[float], base_vals: List[float], factor: float = 1.5) -> bool:
    if now_val is None or not base_vals:
        return False
    avg = sum(float(v) for v in base_vals) / max(1, len(base_vals))
    return float(now_val) > avg * factor


def run_once(
    *,
    db: Session,
    minutes: int = 60,
    bucket: str = "1m",
    baseline_minutes: int = 360,
    max_services: int = 20,
    max_endpoints: int = 20,
    z_weight: float = 0.6,
    err_latency_weight: float = 0.4,
) -> int:
    client = get_client()
    index = ensure_events_index(client)
    tw = window_last_minutes(minutes)
    bw = window_last_minutes(baseline_minutes)

    overview = fetch_overview(client, index=index, time_range=tw.to_opensearch_range(), max_services=max_services, max_endpoints=max_endpoints)
    buckets = (((overview.get("aggregations") or {}).get("services") or {}).get("buckets")) or []
    if not buckets:
        return 0

    created = 0
    for svc in buckets:
        service_id = svc.get("key")
        endpoints = (svc.get("endpoints") or {}).get("buckets") or []
        endpoint_keys = [e.get("key") for e in endpoints] or [None]

        for endpoint in endpoint_keys:
            try:
                ts = fetch_timeseries(client, index=index, time_range=tw.to_opensearch_range(), bucket=bucket, service_id=service_id, endpoint=endpoint)
                base = fetch_timeseries(client, index=index, time_range=bw.to_opensearch_range(), bucket=bucket, service_id=service_id, endpoint=endpoint)
            except Exception:
                continue

            window_series = _extract(ts)
            base_series = _extract(base)
            if not window_series:
                continue

            base_events = [float(x["events"]) for x in base_series if x["ts"]]
            base_uips = [float(x["unique_ips"]) for x in base_series if x["ts"]]

            now = window_series[-1]
            spike_z = robust_z(float(now["events"]), base_events)
            growth_z = robust_z(float(now["unique_ips"]), base_uips)

            base_err = [x["avg_error_rate"] for x in base_series if x["avg_error_rate"] is not None]
            base_lat = [x["avg_latency_ms"] for x in base_series if x["avg_latency_ms"] is not None]
            errors_up = _flag(now["avg_error_rate"], base_err)
            latency_up = _flag(now["avg_latency_ms"], base_lat)

            conv = float(now["convergence"] or 0.0)
            score = min(1.0, max(0.0, z_weight * max(spike_z, growth_z) / 10.0 + err_latency_weight * (1.0 if errors_up or latency_up else 0.0)))
            reasons = _reason_codes(score, spike_z, growth_z, errors_up, latency_up, conv)

            indicators = {
                "events": now["events"],
                "unique_ips": now["unique_ips"],
                "avg_error_rate": now["avg_error_rate"],
                "avg_latency_ms": now["avg_latency_ms"],
                "convergence": conv,
                "window_start": tw.start.isoformat(),
                "window_end": tw.end.isoformat(),
                "baseline_start": bw.start.isoformat(),
                "baseline_end": bw.end.isoformat(),
            }

            window_end = datetime.fromisoformat(tw.end.isoformat())
            existing = (
                db.query(AnomalyScore)
                .filter(AnomalyScore.service_id == service_id)
                .filter(AnomalyScore.endpoint == endpoint)
                .filter(AnomalyScore.window_end == window_end)
                .first()
            )
            if existing:
                existing.score = score
                existing.reason_codes = reasons
                existing.indicators = indicators
            else:
                db.add(
                    AnomalyScore(
                        service_id=service_id,
                        endpoint=endpoint,
                        window_start=tw.start,
                        window_end=tw.end,
                        score=score,
                        reason_codes=reasons,
                        indicators=indicators,
                    )
                )
                created += 1

    db.commit()
    return created


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=int, default=60)
    p.add_argument("--baseline-minutes", type=int, default=360)
    p.add_argument("--bucket", default="1m")
    p.add_argument("--max-services", type=int, default=20)
    p.add_argument("--max-endpoints", type=int, default=20)
    args = p.parse_args()

    db = SessionLocal()
    try:
        n = run_once(
            db=db,
            minutes=args.minutes,
            baseline_minutes=args.baseline_minutes,
            bucket=args.bucket,
            max_services=args.max_services,
            max_endpoints=args.max_endpoints,
        )
        print(json.dumps({"anomalies_created": n}))
    finally:
        db.close()


if __name__ == "__main__":
    main()
