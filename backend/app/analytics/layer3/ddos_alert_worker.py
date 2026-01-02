from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.analytics.ddos_alerts import DDoSAlert
from app.analytics.ddos_windows import window_last_minutes
from app.analytics.ddos_queries import fetch_overview, fetch_timeseries
from app.analytics.ddos_indicators import convergence_index, robust_z, classify_stage, risk_score
from app.core.config import settings
from app.search.opensearch import get_client
from app.search.bootstrap import ensure_events_index
from app.ledger.db import SessionLocal
from app.analytics.mitigations import Mitigation


def _extract_timeseries(series_res: Dict[str, Any]) -> List[Dict[str, Any]]:
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


def _bool_flag(now_val: Optional[float], base_vals: List[float], factor: float = 1.5) -> bool:
    if now_val is None or not base_vals:
        return False
    avg = sum(float(v) for v in base_vals) / max(1, len(base_vals))
    return float(now_val) > avg * factor


def _reason_codes(spike_z: float, growth_z: float, convergence: float, errors_up: bool, latency_up: bool) -> List[str]:
    out: List[str] = []
    if spike_z >= 3:
        out.append("SPIKE_Z_HIGH")
    if growth_z >= 3:
        out.append("UNIQUE_IP_GROWTH_HIGH")
    if convergence >= 0.5:
        out.append("ENDPOINT_CONVERGENCE")
    if errors_up:
        out.append("ERROR_RATE_UP")
    if latency_up:
        out.append("LATENCY_UP")
    return out or ["STRUCTURAL_NORMAL"]


def _mitigation_suggestions(service_id: str, endpoint: Optional[str], providers: Optional[List[str]] = None) -> Dict[str, Any]:
    ep = endpoint or "all"
    prov = providers or []
    return {
        "ISP": [
            "Rate-limit concentrated source ASNs/providers" + (f" ({', '.join(prov)})" if prov else ""),
            "Prepare RTBH/blackhole for worst offenders",
            "Notify upstream/peering if sustained",
        ],
        "APP": [
            f"Tighten WAF rules on endpoint {ep}",
            "Throttle login/API burst rates temporarily",
            "Enable caching/degrade non-critical endpoints if needed",
        ],
        "NCSC": [
            "Cross-service early warning to stakeholders",
            "Publish IOC bundle (IPs/providers/endpoints) to partners",
        ],
    }


def run_once(
    *,
    db: Session,
    minutes: int = 60,
    bucket: str = "1m",
    baseline_minutes: int = 360,
    max_services: int = 20,
    max_endpoints: int = 20,
) -> int:
    """
    Compute DDoS structural alerts for top services/endpoints in the window.
    Idempotent on (service_id, endpoint, window_end).
    """
    client = get_client()
    index = ensure_events_index(client)
    tw = window_last_minutes(minutes)
    bw = window_last_minutes(baseline_minutes)

    # Discover active services/endpoints
    overview = fetch_overview(client, index=index, time_range=tw.to_opensearch_range(), max_services=max_services, max_endpoints=max_endpoints)
    buckets = (((overview.get("aggregations") or {}).get("services") or {}).get("buckets")) or []
    if not buckets:
        return 0

    created = 0

    for svc in buckets:
        service_id = svc.get("key")
        endpoints = (svc.get("endpoints") or {}).get("buckets") or []
        endpoint_keys = [e.get("key") for e in endpoints] or [None]  # None means all endpoints for service

        for endpoint in endpoint_keys:
            try:
                ts = fetch_timeseries(client, index=index, time_range=tw.to_opensearch_range(), bucket=bucket, service_id=service_id, endpoint=endpoint)
                base = fetch_timeseries(client, index=index, time_range=bw.to_opensearch_range(), bucket=bucket, service_id=service_id, endpoint=endpoint)
            except Exception:
                # Skip this endpoint on OS error; keep going
                continue

            window_series = _extract_timeseries(ts)
            base_series = _extract_timeseries(base)
            if not window_series:
                continue

            base_events = [float(x["events"]) for x in base_series if x["ts"]]
            base_uips = [float(x["unique_ips"]) for x in base_series if x["ts"]]

            now = window_series[-1]
            spike_z = robust_z(float(now["events"]), base_events)
            growth_z = robust_z(float(now["unique_ips"]), base_uips)

            base_err = [x["avg_error_rate"] for x in base_series if x["avg_error_rate"] is not None]
            base_lat = [x["avg_latency_ms"] for x in base_series if x["avg_latency_ms"] is not None]
            errors_up = _bool_flag(now["avg_error_rate"], base_err)
            latency_up = _bool_flag(now["avg_latency_ms"], base_lat)

            conv = float(now["convergence"] or 0.0)
            stage = classify_stage(spike_z=spike_z, growth_z=growth_z, convergence=conv, errors_up=errors_up, latency_up=latency_up)
            risk = risk_score(spike_z=spike_z, growth_z=growth_z, convergence=conv, errors_up=errors_up, latency_up=latency_up)

            reasons = _reason_codes(spike_z, growth_z, conv, errors_up, latency_up)

            window_end = datetime.fromisoformat(tw.end.isoformat())
            alert = (
                db.query(DDoSAlert)
                .filter(DDoSAlert.service_id == service_id)
                .filter(DDoSAlert.endpoint == endpoint)
                .filter(DDoSAlert.window_end == window_end)
                .first()
            )

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
                "mitigations": _mitigation_suggestions(service_id, endpoint),
                "ioc": {
                    "service_id": service_id,
                    "endpoint": endpoint,
                },
            }

            if alert:
                alert.spike_z = spike_z
                alert.unique_ip_growth_z = growth_z
                alert.convergence = conv
                alert.risk = risk
                alert.stage = stage
                alert.errors_up = errors_up
                alert.latency_up = latency_up
                alert.reason_codes = reasons
                alert.indicators = indicators
            else:
                db.add(
                    DDoSAlert(
                        service_id=service_id,
                        endpoint=endpoint,
                        window_start=tw.start,
                        window_end=tw.end,
                        spike_z=spike_z,
                        unique_ip_growth_z=growth_z,
                        convergence=conv,
                        risk=risk,
                        stage=stage,
                        errors_up=errors_up,
                        latency_up=latency_up,
                        reason_codes=reasons,
                        indicators=indicators,
                    )
                )
                created += 1

            # Upsert mitigation/IOC bundle
            mid = _mitigation_suggestions(service_id, endpoint)
            mit = (
                db.query(Mitigation)
                .filter(Mitigation.kind == "DDOS")
                .filter(Mitigation.ref_id == f"{service_id}:{endpoint or '*'}:{tw.end.isoformat()}")
                .first()
            )
            if mit:
                mit.payload = mid
            else:
                db.add(
                    Mitigation(
                        kind="DDOS",
                        ref_id=f"{service_id}:{endpoint or '*'}:{tw.end.isoformat()}",
                        stakeholders=["ISP", "APP", "NCSC"],
                        payload=mid,
                    )
                )

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
        print(json.dumps({"alerts_created": n}))
    finally:
        db.close()


if __name__ == "__main__":
    main()
