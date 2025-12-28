# app/api/events.py
from __future__ import annotations

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.search.opensearch import get_client
from app.search.bootstrap import ensure_events_index

router = APIRouter(prefix="/v1/events", tags=["events"])


def _index_name() -> str:
    client = get_client()
    return ensure_events_index(client)


# -------------------------
# GET EVENT BY HASH
# -------------------------
@router.get("/{event_hash}")
def get_event(event_hash: str):
    client = get_client()
    index = _index_name()

    try:
        res = client.get(index=index, id=event_hash)
        return res["_source"]
    except Exception:
        raise HTTPException(status_code=404, detail="event_not_found")


# -------------------------
# SEARCH EVENTS
# -------------------------
@router.get("/search")
def search_events(
    q: Optional[str] = None,
    event_type: Optional[str] = None,
    source_id: Optional[str] = None,
    anchor: Optional[str] = None,  # ip:1.2.3.4 | person_h:demo1
    start: Optional[str] = None,   # ISO
    end: Optional[str] = None,     # ISO
    size: int = Query(default=50, ge=1, le=200),
):
    client = get_client()
    index = _index_name()

    must = []

    if q:
        must.append({
            "query_string": {
                "query": q,
                "default_operator": "AND",
            }
        })

    if event_type:
        must.append({"term": {"event_type": event_type}})

    if source_id:
        must.append({"term": {"source_id": source_id}})

    if anchor:
        must.append({"term": {"anchors_flat": anchor}})

    if start or end:
        rng = {}
        if start:
            rng["gte"] = start
        if end:
            rng["lte"] = end
        must.append({"range": {"occurred_at": rng}})

    body = {
        "query": {"bool": {"must": must or [{"match_all": {}}]}},
        "sort": [{"occurred_at": {"order": "desc"}}],
        "size": size,
    }

    res = client.search(index=index, body=body)

    return {
        "count": res["hits"]["total"]["value"],
        "items": [h["_source"] for h in res["hits"]["hits"]],
    }


# -------------------------
# EVENTS TIMELINE
# -------------------------
@router.get("/timeline")
def timeline(
    start: str,
    end: str,
    interval: str = Query(default="1m", pattern=r"^\d+[smhd]$"),
    event_type: Optional[str] = None,
    source_id: Optional[str] = None,
):
    client = get_client()
    index = _index_name()

    must = [{"range": {"occurred_at": {"gte": start, "lte": end}}}]

    if event_type:
        must.append({"term": {"event_type": event_type}})
    if source_id:
        must.append({"term": {"source_id": source_id}})

    body = {
        "size": 0,
        "query": {"bool": {"must": must}},
        "aggs": {
            "by_time": {
                "date_histogram": {
                    "field": "occurred_at",
                    "fixed_interval": interval,
                    "min_doc_count": 0,
                }
            }
        },
    }

    res = client.search(index=index, body=body)
    buckets = res["aggregations"]["by_time"]["buckets"]

    return {
        "start": start,
        "end": end,
        "interval": interval,
        "points": [
            {"t": b["key_as_string"], "count": b["doc_count"]}
            for b in buckets
        ],
    }
