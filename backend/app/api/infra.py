# app/api/infra.py
from fastapi import APIRouter
from app.search.opensearch import get_client
from app.search.bootstrap import ensure_events_index

router = APIRouter(prefix="/v1/infra", tags=["infra"])

@router.get("/ip/{ip}")
def ip_context(ip: str):
    client = get_client()
    index = ensure_events_index(client)

    body = {
        "size": 0,
        "query": {"term": {"anchors_flat": f"ip:{ip}"}},
        "aggs": {
            "persons": {"cardinality": {"field": "anchors.person_h"}},
            "devices": {"cardinality": {"field": "anchors.device_id"}},
            "services": {"cardinality": {"field": "anchors.service_id"}},
            "first_seen": {"min": {"field": "occurred_at"}},
            "last_seen": {"max": {"field": "occurred_at"}},
        },
    }

    res = client.search(index=index, body=body)

    return {
        "ip": ip,
        "summary": {
            "event_count": res["hits"]["total"]["value"],
            "unique_persons": res["aggregations"]["persons"]["value"],
            "unique_devices": res["aggregations"]["devices"]["value"],
            "unique_services": res["aggregations"]["services"]["value"],
            "first_seen": res["aggregations"]["first_seen"]["value_as_string"],
            "last_seen": res["aggregations"]["last_seen"]["value_as_string"],
        },
        "risk_signals": {
            "shared_across_persons": res["aggregations"]["persons"]["value"] > 1,
            "shared_across_services": res["aggregations"]["services"]["value"] > 1,
            "likely_infra": res["aggregations"]["persons"]["value"] > 3,
        },
    }
