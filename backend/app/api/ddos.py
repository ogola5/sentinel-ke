# app/api/ddos.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from opensearchpy import OpenSearch

from app.analytics.ddos_windows import bucket_interval, window_last_minutes
from app.analytics.ddos_queries import fetch_overview, fetch_timeseries
from app.analytics.ddos_indicators import convergence_index, robust_z, classify_stage, risk_score
from app.search.opensearch import get_client  # your existing OpenSearch client factory
from app.core.config import settings       # your existing settings
from app.analytics.ddos_stages import classify_ddos_stage
from app.analytics.ddos_alerts import DDoSAlert
from app.ledger.db import get_db
from sqlalchemy.orm import Session
from app.api.deps import pagination_params

router = APIRouter(prefix="/v1/ddos", tags=["ddos"])


def _events_index() -> str:
    # your env already has OPENSEARCH_INDEX_EVENTS=sentinel-events-v1
    idx = getattr(settings, "opensearch_index_events", None)
    if not idx:
        # fallback if settings attr differs
        idx = "sentinel-events-v1"
    return idx


@router.get("/overview")
def ddos_overview(
    minutes: int = Query(60, ge=1, le=10080),
    max_services: int = Query(20, ge=1, le=200),
    max_endpoints: int = Query(10, ge=1, le=200),
):
    """
    High-level view: top services/endpoints by activity in the window.
    This endpoint is intentionally metric-light; scoring happens in /indicators.
    """
    tw = window_last_minutes(minutes)
    client: OpenSearch = get_client()
    index = _events_index()

    try:
        res = fetch_overview(client, index=index, time_range=tw.to_opensearch_range(), max_services=max_services, max_endpoints=max_endpoints)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"opensearch_error: {str(e)}")

    buckets = (((res.get("aggregations") or {}).get("services") or {}).get("buckets")) or []
    if not buckets:
        return {"window": {"start": tw.start.isoformat(), "end": tw.end.isoformat()}, "items": [], "note": "no ddos signals in window"}

    items: List[Dict[str, Any]] = []
    for b in buckets:
        svc = b.get("key")
        endpoints = (b.get("endpoints") or {}).get("buckets") or []
        items.append(
            {
                "service_id": svc,
                "events": int((b.get("events") or {}).get("value") or 0),
                "unique_ips": int((b.get("unique_ips") or {}).get("value") or 0),
                "top_endpoints": [{"endpoint": eb.get("key"), "events": int(eb.get("doc_count") or 0)} for eb in endpoints],
            }
        )

    return {"window": {"start": tw.start.isoformat(), "end": tw.end.isoformat()}, "items": items}


@router.get("/indicators")
def ddos_indicators(
    service_id: str = Query(..., min_length=1),
    endpoint: Optional[str] = Query(None),
    minutes: int = Query(180, ge=5, le=10080),
    bucket: str = Query("1m"),
    baseline_minutes: int = Query(360, ge=30, le=10080),
):
    """
    Returns time-series + computed indicators + stage classification.
    - window: last `minutes`
    - baseline: last `baseline_minutes` (ending now)
    """
    bkt = bucket_interval(bucket)
    tw = window_last_minutes(minutes)
    bw = window_last_minutes(baseline_minutes)

    client: OpenSearch = get_client()
    index = _events_index()

    try:
        ts = fetch_timeseries(client, index=index, time_range=tw.to_opensearch_range(), bucket=bkt, service_id=service_id, endpoint=endpoint)
        base = fetch_timeseries(client, index=index, time_range=bw.to_opensearch_range(), bucket=bkt, service_id=service_id, endpoint=endpoint)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"opensearch_error: {str(e)}")

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

    window_series = _extract(ts)
    base_series = _extract(base)

    if not window_series:
        return {
            "service_id": service_id,
            "endpoint": endpoint,
            "bucket": bkt,
            "window": {"start": tw.start.isoformat(), "end": tw.end.isoformat()},
            "series": [],
            "note": "no ddos signals in window",
        }

    # Baseline vectors
    base_events = [float(x["events"]) for x in base_series if x["ts"] is not None]
    base_uips = [float(x["unique_ips"]) for x in base_series if x["ts"] is not None]

    # Use last window point as "now" (deterministic)
    now = window_series[-1]
    spike_z = robust_z(float(now["events"]), base_events)
    growth_z = robust_z(float(now["unique_ips"]), base_uips)

    # errors/latency "up" heuristics (best-effort)
    # if baseline is empty or missing numeric fields, we keep them False.
    errors_up = False
    latency_up = False
    if base_series:
        base_err = [x["avg_error_rate"] for x in base_series if x["avg_error_rate"] is not None]
        base_lat = [x["avg_latency_ms"] for x in base_series if x["avg_latency_ms"] is not None]
        if now["avg_error_rate"] is not None and base_err:
            errors_up = float(now["avg_error_rate"]) > (sum(float(v) for v in base_err) / max(1, len(base_err))) * 1.5
        if now["avg_latency_ms"] is not None and base_lat:
            latency_up = float(now["avg_latency_ms"]) > (sum(float(v) for v in base_lat) / max(1, len(base_lat))) * 1.5

    conv = float(now["convergence"] or 0.0)
    stage = classify_stage(spike_z=spike_z, growth_z=growth_z, convergence=conv, errors_up=errors_up, latency_up=latency_up)
    risk = risk_score(spike_z=spike_z, growth_z=growth_z, convergence=conv, errors_up=errors_up, latency_up=latency_up)

    return {
        "service_id": service_id,
        "endpoint": endpoint,
        "bucket": bkt,
        "window": {"start": tw.start.isoformat(), "end": tw.end.isoformat()},
        "baseline": {"start": bw.start.isoformat(), "end": bw.end.isoformat()},
        "now": {
            "ts": now["ts"],
            "events": now["events"],
            "unique_ips": now["unique_ips"],
            "avg_error_rate": now["avg_error_rate"],
            "avg_latency_ms": now["avg_latency_ms"],
            "convergence": conv,
        },
        "indicators": {"spike_z": spike_z, "unique_ip_growth_z": growth_z, "convergence": conv},
        "classification": {"stage": stage, "risk": risk, "errors_up": errors_up, "latency_up": latency_up},
        "series": window_series,
    }


@router.get("/alerts")
def list_ddos_alerts(
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(DDoSAlert)
        .order_by(DDoSAlert.window_end.desc(), DDoSAlert.risk.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "service_id": r.service_id,
                "endpoint": r.endpoint,
                "window_start": r.window_start.isoformat(),
                "window_end": r.window_end.isoformat(),
                "stage": r.stage,
                "risk": r.risk,
                "spike_z": r.spike_z,
                "unique_ip_growth_z": r.unique_ip_growth_z,
                "convergence": r.convergence,
                "errors_up": r.errors_up,
                "latency_up": r.latency_up,
                "reason_codes": r.reason_codes,
                "indicators": r.indicators,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }

@router.get("/signals")
def ddos_signals_hint(
    service_id: Optional[str] = Query(None),
    endpoint: Optional[str] = Query(None),
    minutes: int = Query(60, ge=1, le=10080),
):
    """
    MVP helper: we don't create a separate raw-signal endpoint yet because you already have /v1/events/search.
    This returns the exact filters the UI should use against /v1/events/search.
    """
    tw = window_last_minutes(minutes)
    filters: Dict[str, Any] = {
        "event_type": "DDOS_SIGNAL_EVENT",
        "occurred_at": {"gte": tw.start.isoformat(), "lte": tw.end.isoformat()},
        "anchors": {},
    }
    if service_id:
        filters["anchors"]["service_id"] = service_id
    if endpoint:
        filters["anchors"]["endpoint"] = endpoint

    return {"use_events_search": "/v1/events/search", "filters": filters}
