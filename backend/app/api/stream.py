"""
Sentinel-KE — Server-Sent Events (SSE) real-time stream endpoint.

GET /v1/stream/events?token=<api_key>
  → Streams new EventRecord objects as they appear in the DB, ~2-second lag.

Auth:  Pass the FRONTEND_API_KEY value as ?token= query parameter.
       EventSource (browser native) cannot send custom headers, so we accept
       the API key as a query parameter exclusively for this SSE endpoint.

Data protocol:
  data: {EventRecord JSON}\n\n   — new event
  : heartbeat\n\n                — keep-alive every 15 s (ignored by client)

EventRecord shape matches frontend src/types/domain.ts EventRecord.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse

from app.core.config import settings
from app.ledger.db import SessionLocal
from app.ledger.models import EventLog

log = logging.getLogger("sentinel.stream")

router = APIRouter(prefix="/v1/stream", tags=["stream"])

_POLL_SECS    = 2      # how often to check DB for new events
_HEARTBEAT_N  = 8      # send heartbeat every N polls (= 16 s)
_MAX_PER_POLL = 20     # cap events sent per poll cycle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _source_from_row(row: EventLog) -> str:
    """Infer frontend SourceType from source_id / section_code."""
    sc = ((row.section_code or "") + (row.source_id or "")).lower()
    if any(k in sc for k in ("telco", "mpesa", "safaricom", "airtel", "telkom")):
        return "telco"
    if any(k in sc for k in ("bank", "equity", "kcb", "cbk", "mfin", "fin")):
        return "bank"
    if any(k in sc for k in ("osint", "stix", "threat", "cve", "vuln")):
        return "osint"
    if any(k in sc for k in ("infra", "ddos", "cdn", "dns", "cloud")):
        return "infra"
    return "gov"


def _build_summary(event_type: str, payload: dict) -> str:
    et = (event_type or "").upper()
    if "DDOS" in et:
        svc  = payload.get("service_id", "unknown")
        rate = payload.get("request_rate")
        return f"DDoS on {svc}" + (f" — {rate:.0f} rps" if isinstance(rate, (int, float)) else "")
    if "WEB" in et or "ATTACK" in et:
        attack = payload.get("attack_type", "web attack")
        svc    = payload.get("service_id", payload.get("asset_id", "unknown"))
        return f"{attack} on {svc}"
    if "VULN" in et:
        cve = payload.get("cve_id", "")
        return f"Vulnerability: {cve}" if cve else "Vulnerability detected"
    if "MOBILE" in et or "MPESA" in et or "AIRTIME" in et or "BILLING" in et:
        return "Mobile money event"
    if "CAMPAIGN" in et:
        return payload.get("campaign_name", "New campaign detected")
    return event_type.replace("_", " ").title()


def _row_to_event(row: EventLog) -> dict:
    payload = row.payload_json or {}
    return {
        "event_hash":     row.event_hash,
        "type":           row.event_type or "",
        "source":         _source_from_row(row),
        "classification": row.classification or "UNCLASSIFIED",
        "confidence":     float(payload.get("confidence", 0.75)),
        "occurred_at":    _iso(row.occurred_at),
        "received_at":    _iso(row.received_at),
        "service_id":     str(payload.get("service_id") or payload.get("asset_id") or ""),
        "endpoint":       str(payload.get("endpoint") or ""),
        "summary":        _build_summary(row.event_type or "", payload),
        "evidence":       [],
    }


def _check_token(token: Optional[str]) -> bool:
    if settings.api_auth_disabled:
        return True
    if not token:
        return False
    valid = {settings.frontend_api_key, settings.ingest_api_key}
    return token in valid


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------

async def _event_stream(request: Request) -> AsyncIterator[str]:
    """Async generator that yields SSE-formatted strings."""
    # Find the most recent event timestamp so we don't re-send history on connect
    db = SessionLocal()
    try:
        latest = (
            db.query(EventLog.occurred_at)
            .order_by(EventLog.occurred_at.desc())
            .first()
        )
        last_ts: datetime = latest[0] if latest and latest[0] else _utcnow()
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
    finally:
        db.close()

    heartbeat_count = 0

    while True:
        if await request.is_disconnected():
            log.debug("sse_client_disconnected")
            break

        # ── Poll DB for new events ─────────────────────────────────────────
        db = SessionLocal()
        try:
            rows = (
                db.query(EventLog)
                .filter(EventLog.occurred_at > last_ts)
                .order_by(EventLog.occurred_at.asc())
                .limit(_MAX_PER_POLL)
                .all()
            )
        except Exception as exc:
            log.warning("sse_poll_error err=%s", exc)
            rows = []
        finally:
            db.close()

        for row in rows:
            evt = _row_to_event(row)
            yield f"data: {json.dumps(evt)}\n\n"
            ts = row.occurred_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            last_ts = ts

        # ── Heartbeat ──────────────────────────────────────────────────────
        heartbeat_count += 1
        if heartbeat_count >= _HEARTBEAT_N:
            yield ": heartbeat\n\n"
            heartbeat_count = 0

        await asyncio.sleep(_POLL_SECS)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/events", summary="Server-Sent Events: real-time threat event stream")
async def stream_events(
    request: Request,
    token: Optional[str] = Query(
        default=None,
        description="FRONTEND_API_KEY value — required because EventSource cannot set headers",
    ),
):
    """
    SSE stream of new threat events as they are ingested.

    **Usage (browser):**
    ```js
    const es = new EventSource(`/v1/stream/events?token=${apiKey}`);
    es.onmessage = (e) => console.log(JSON.parse(e.data));
    ```

    **Auth:** pass `FRONTEND_API_KEY` as `?token=`.
    Disabled when `API_AUTH_DISABLED=true`.
    """
    if not _check_token(token):
        return Response(status_code=401, content="Unauthorized: valid ?token= required for SSE")

    return StreamingResponse(
        _event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control":      "no-cache",
            "X-Accel-Buffering":  "no",
            "Connection":         "keep-alive",
        },
    )
