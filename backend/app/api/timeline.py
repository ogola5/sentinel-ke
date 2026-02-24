# app/api/timeline.py
from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime

from app.api.deps import AuthPrincipal, require_request_principal
from app.search.opensearch import get_client

router = APIRouter(prefix="/v1/events", tags=["timeline"])


@router.get("/timeline")
def events_timeline(
    start: datetime = Query(...),
    end: datetime = Query(...),
    interval: str = Query("1m"),
    principal: AuthPrincipal = Depends(require_request_principal),
):
    os = get_client()

    must = [
        {
            "range": {
                "occurred_at": {
                    "gte": start.isoformat(),
                    "lte": end.isoformat(),
                }
            }
        }
    ]
    if principal.access_level == "section":
        section_code = (principal.section_code or "").strip()
        if not section_code:
            raise HTTPException(status_code=403, detail="principal_section_code_missing")
        must.append({"term": {"section_code": section_code}})

    resp = os.search(
        index="sentinel-events-v1",
        size=0,
        query={"bool": {"must": must}},
        aggs={
            "timeline": {
                "date_histogram": {
                    "field": "occurred_at",
                    "fixed_interval": interval,
                }
            }
        },
    )

    buckets = resp["aggregations"]["timeline"]["buckets"]

    return [
        {
            "timestamp": b["key_as_string"],
            "count": b["doc_count"],
        }
        for b in buckets
    ]
