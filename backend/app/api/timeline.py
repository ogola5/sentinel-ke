# app/api/timeline.py
from fastapi import APIRouter, Query
from datetime import datetime

from app.search.opensearch import get_client

router = APIRouter(prefix="/v1/events", tags=["timeline"])


@router.get("/timeline")
def events_timeline(
    start: datetime = Query(...),
    end: datetime = Query(...),
    interval: str = Query("1m"),
):
    os = get_client()

    resp = os.search(
        index="sentinel-events-v1",
        size=0,
        query={
            "range": {
                "occurred_at": {
                    "gte": start.isoformat(),
                    "lte": end.isoformat(),
                }
            }
        },
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
