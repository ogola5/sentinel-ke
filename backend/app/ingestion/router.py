from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.api.deps import get_db
from app.core.config import settings
from app.ingestion.schemas import CanonicalEvent
from app.ingestion.service import IngestionService

router = APIRouter(prefix="/v1/ingest", tags=["ingestion"])
log = logging.getLogger("sentinel.api.ingest")


def _require_api_key(x_api_key: Optional[str]) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    return x_api_key


@router.post("/event")
def ingest_event(
    event: CanonicalEvent,
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    api_key = _require_api_key(x_api_key)

    try:
        svc = IngestionService(db, pseudonym_salt=settings.pseudonym_salt or None)
        res = svc.ingest_event(event=event, source_api_key=api_key)
        return {
            "event_hash": res.event_hash,
            "status": res.status,
            "accepted_at": res.accepted_at,
            "source_id": res.source_id,
            "classification": res.classification,
        }
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        log.exception("ingest_event_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/batch")
def ingest_batch(
    events: List[CanonicalEvent],
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    api_key = _require_api_key(x_api_key)

    svc = IngestionService(db, pseudonym_salt=settings.pseudonym_salt or None)
    out = []
    for ev in events:
        try:
            res = svc.ingest_event(event=ev, source_api_key=api_key)
            out.append({"event_hash": res.event_hash, "status": res.status})
        except Exception:
            log.exception("ingest_batch_item_failed")
            out.append({"error": "internal_error"})
    return {"results": out}


@router.get("/schema")
def get_schema():
    # Pydantic v2
    return CanonicalEvent.model_json_schema()
