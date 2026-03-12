# app/api/events.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Text, cast, or_
from sqlalchemy.orm import Session

from app.api.deps import AuthPrincipal, get_db, require_request_principal
from app.ledger.models import EventLog
from app.search.opensearch import get_client, is_opensearch_disabled_error
from app.search.bootstrap import ensure_events_index

router = APIRouter(prefix="/v1/events", tags=["events"])


def _index_name() -> str:
    client = get_client()
    return ensure_events_index(client)


def _apply_section_scope_to_must(must: list[dict], principal: AuthPrincipal) -> None:
    if principal.access_level != "section":
        return
    section_code = (principal.section_code or "").strip()
    if not section_code:
        raise HTTPException(status_code=403, detail="principal_section_code_missing")
    must.append({"term": {"section_code": section_code}})


def _enforce_event_doc_scope(doc: dict, principal: AuthPrincipal) -> None:
    if principal.access_level != "section":
        return
    section_code = (principal.section_code or "").strip()
    if not section_code:
        raise HTTPException(status_code=403, detail="principal_section_code_missing")
    if (doc or {}).get("section_code") != section_code:
        raise HTTPException(status_code=404, detail="event_not_found")


def _parse_iso_datetime(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalise_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _row_to_doc(row: EventLog) -> dict:
    anchors = dict(row.anchors_json or {})
    payload = dict(row.payload_json or {})
    occurred_at = _normalise_dt(row.occurred_at)
    received_at = _normalise_dt(row.received_at)
    return {
        "event_hash": row.event_hash,
        "event_type": row.event_type,
        "source_id": row.source_id,
        "section_code": row.section_code,
        "classification": row.classification,
        "schema_version": row.schema_version,
        "signature_valid": bool(row.signature_valid),
        "occurred_at": occurred_at.isoformat() if occurred_at else None,
        "received_at": received_at.isoformat() if received_at else None,
        "anchors": anchors,
        "anchors_flat": [f"{k}:{v}" for k, v in anchors.items() if v],
        "payload": payload,
    }


def _scoped_query(db: Session, principal: AuthPrincipal):
    query = db.query(EventLog)
    if principal.access_level == "section":
        section_code = (principal.section_code or "").strip()
        if not section_code:
            raise HTTPException(status_code=403, detail="principal_section_code_missing")
        query = query.filter(EventLog.section_code == section_code)
    return query


def _apply_anchor_filter(query, anchor: str):
    key, sep, value = anchor.partition(":")
    if sep and key and value:
        return query.filter(EventLog.anchors_json[key].astext == value)
    return query.filter(cast(EventLog.anchors_json, Text).ilike(f"%{anchor}%"))


def _db_search_events(
    *,
    db: Session,
    principal: AuthPrincipal,
    q: Optional[str],
    event_type: Optional[str],
    source_id: Optional[str],
    anchor: Optional[str],
    start: Optional[str],
    end: Optional[str],
    size: int,
):
    query = _scoped_query(db, principal)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                EventLog.event_type.ilike(like),
                EventLog.source_id.ilike(like),
                cast(EventLog.anchors_json, Text).ilike(like),
                cast(EventLog.payload_json, Text).ilike(like),
            )
        )
    if event_type:
        query = query.filter(EventLog.event_type == event_type)
    if source_id:
        query = query.filter(EventLog.source_id == source_id)
    if anchor:
        query = _apply_anchor_filter(query, anchor)
    if start:
        query = query.filter(EventLog.occurred_at >= _parse_iso_datetime(start))
    if end:
        query = query.filter(EventLog.occurred_at <= _parse_iso_datetime(end))

    total = query.count()
    rows = query.order_by(EventLog.occurred_at.desc()).limit(size).all()
    return {"count": total, "items": [_row_to_doc(row) for row in rows]}


def _parse_interval(interval: str) -> timedelta:
    unit = interval[-1]
    qty = int(interval[:-1])
    if unit == "s":
        return timedelta(seconds=qty)
    if unit == "m":
        return timedelta(minutes=qty)
    if unit == "h":
        return timedelta(hours=qty)
    if unit == "d":
        return timedelta(days=qty)
    raise ValueError("unsupported_interval")


def _db_timeline(
    *,
    db: Session,
    principal: AuthPrincipal,
    start: str,
    end: str,
    interval: str,
    event_type: Optional[str],
    source_id: Optional[str],
):
    start_dt = _parse_iso_datetime(start)
    end_dt = _parse_iso_datetime(end)
    step = _parse_interval(interval)
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="invalid_time_range")

    query = _scoped_query(db, principal).filter(
        EventLog.occurred_at >= start_dt,
        EventLog.occurred_at <= end_dt,
    )
    if event_type:
        query = query.filter(EventLog.event_type == event_type)
    if source_id:
        query = query.filter(EventLog.source_id == source_id)

    rows = query.order_by(EventLog.occurred_at.asc()).all()
    points: dict[datetime, int] = {}
    bucket_count = int(((end_dt - start_dt).total_seconds() // step.total_seconds()) + 1)
    for idx in range(max(bucket_count, 0)):
        points[start_dt + (step * idx)] = 0

    for row in rows:
        occurred_at = _normalise_dt(row.occurred_at)
        if occurred_at is None:
            continue
        offset = max(0.0, (occurred_at - start_dt).total_seconds())
        bucket_index = int(offset // step.total_seconds())
        bucket_time = start_dt + (step * bucket_index)
        if bucket_time > end_dt:
            continue
        points[bucket_time] = points.get(bucket_time, 0) + 1

    return {
        "start": start,
        "end": end,
        "interval": interval,
        "points": [
            {"t": bucket.isoformat(), "count": count}
            for bucket, count in sorted(points.items(), key=lambda item: item[0])
        ],
    }


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
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
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

        _apply_section_scope_to_must(must, principal)

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
    except Exception as exc:
        if not is_opensearch_disabled_error(exc):
            # Render/runtime-only mode falls back to Postgres.
            # When OpenSearch is simply unavailable, the ledger still has the
            # canonical event log and remains useful for search/timeline flows.
            pass
        return _db_search_events(
            db=db,
            principal=principal,
            q=q,
            event_type=event_type,
            source_id=source_id,
            anchor=anchor,
            start=start,
            end=end,
            size=size,
        )


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
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        client = get_client()
        index = _index_name()

        must = [{"range": {"occurred_at": {"gte": start, "lte": end}}}]

        if event_type:
            must.append({"term": {"event_type": event_type}})
        if source_id:
            must.append({"term": {"source_id": source_id}})
        _apply_section_scope_to_must(must, principal)

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
    except Exception as exc:
        if not is_opensearch_disabled_error(exc):
            pass
        return _db_timeline(
            db=db,
            principal=principal,
            start=start,
            end=end,
            interval=interval,
            event_type=event_type,
            source_id=source_id,
        )


# -------------------------
# GET EVENT BY HASH
# -------------------------
@router.get("/{event_hash}")
def get_event(
    event_hash: str,
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        client = get_client()
        index = _index_name()
        res = client.get(index=index, id=event_hash)
        src = res["_source"]
        _enforce_event_doc_scope(src, principal)
        return src
    except HTTPException:
        raise
    except Exception as exc:
        if not is_opensearch_disabled_error(exc):
            pass
        row = db.get(EventLog, event_hash)
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")
        src = _row_to_doc(row)
        _enforce_event_doc_scope(src, principal)
        return src
