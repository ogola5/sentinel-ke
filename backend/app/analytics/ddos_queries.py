# app/analytics/ddos_queries.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from opensearchpy import OpenSearch


# We will aggregate only on keyword subfields
A_SERVICE = "anchors.service_id.keyword"
A_ENDPOINT = "anchors.endpoint.keyword"
A_IP = "anchors.ip.keyword"

# Optional numeric signals (if you ingest them as numbers in payload)
P_REQ_RATE = "payload.req_rate"          # number (optional)
P_ERROR_RATE = "payload.error_rate"      # number (optional)
P_LAT_MS = "payload.avg_latency_ms"      # number (optional)


def _base_filter(time_range: Dict[str, str], service_id: Optional[str], endpoint: Optional[str]) -> List[Dict[str, Any]]:
    filters: List[Dict[str, Any]] = [
        {"term": {"event_type": "DDOS_SIGNAL_EVENT"}},
        {"range": {"occurred_at": time_range}},
    ]
    if service_id:
        filters.append({"term": {A_SERVICE: service_id}})
    if endpoint:
        filters.append({"term": {A_ENDPOINT: endpoint}})
    return filters


def overview_agg_body(time_range: Dict[str, str], max_services: int, max_endpoints: int) -> Dict[str, Any]:
    return {
        "size": 0,
        "query": {"bool": {"filter": _base_filter(time_range, None, None)}},
        "aggs": {
            "services": {
                "terms": {"field": A_SERVICE, "size": max_services},
                "aggs": {
                    "endpoints": {"terms": {"field": A_ENDPOINT, "size": max_endpoints}},
                    "unique_ips": {"cardinality": {"field": A_IP}},
                    "events": {"value_count": {"field": "event_hash"}},
                },
            }
        },
    }


def timeseries_body(time_range: Dict[str, str], bucket: str, service_id: str, endpoint: Optional[str]) -> Dict[str, Any]:
    """
    Returns per-bucket counts + per-bucket unique IPs.
    If payload numeric fields exist, we also compute avg error_rate / latency.
    """
    return {
        "size": 0,
        "query": {"bool": {"filter": _base_filter(time_range, service_id, endpoint)}},
        "aggs": {
            "by_time": {
                "date_histogram": {
                    "field": "occurred_at",
                    "fixed_interval": bucket,
                    "min_doc_count": 0,
                },
                "aggs": {
                    "events": {"value_count": {"field": "event_hash"}},
                    "unique_ips": {"cardinality": {"field": A_IP}},
                    # Best-effort numeric fields; safe if field missing (OpenSearch returns null)
                    "avg_error_rate": {"avg": {"field": P_ERROR_RATE}},
                    "avg_latency_ms": {"avg": {"field": P_LAT_MS}},
                    # endpoint convergence within bucket (distribution)
                    "top_endpoints": {"terms": {"field": A_ENDPOINT, "size": 20}},
                },
            }
        },
    }


def fetch_overview(client: OpenSearch, index: str, time_range: Dict[str, str], max_services: int = 20, max_endpoints: int = 10) -> Dict[str, Any]:
    body = overview_agg_body(time_range=time_range, max_services=max_services, max_endpoints=max_endpoints)
    return client.search(index=index, body=body)


def fetch_timeseries(client: OpenSearch, index: str, time_range: Dict[str, str], bucket: str, service_id: str, endpoint: Optional[str]) -> Dict[str, Any]:
    body = timeseries_body(time_range=time_range, bucket=bucket, service_id=service_id, endpoint=endpoint)
    return client.search(index=index, body=body)
