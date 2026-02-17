from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.ingestion.service import IngestionService
from app.integrations.connectors import list_connectors, map_external_event
from app.integrations.schemas import ConnectorBatchRequest, ConnectorEventRequest

router = APIRouter(prefix="/v1/integrations", tags=["integrations"])
log = logging.getLogger("sentinel.api.integrations")


@router.get("/connectors")
def get_connectors():
    return {"items": list_connectors()}


@router.post("/{connector_key}/event")
def ingest_connector_event(
    connector_key: str,
    req: ConnectorEventRequest,
    db: Session = Depends(get_db),
):
    try:
        event = map_external_event(
            connector_key=connector_key,
            payload=req.payload,
            confidence=req.confidence,
            classification=req.classification,
        )
        svc = IngestionService(db, pseudonym_salt=settings.pseudonym_salt or None)
        res = svc.ingest_event(event=event, source_api_key=req.source_api_key)
        return {
            "connector": connector_key,
            "mapped_event_type": event.event_type,
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
        log.exception("ingest_connector_event_failed connector=%s", connector_key)
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/{connector_key}/batch")
def ingest_connector_batch(
    connector_key: str,
    req: ConnectorBatchRequest,
    db: Session = Depends(get_db),
):
    svc = IngestionService(db, pseudonym_salt=settings.pseudonym_salt or None)
    out = []
    for idx, payload in enumerate(req.items):
        try:
            event = map_external_event(
                connector_key=connector_key,
                payload=payload,
                confidence=req.confidence,
                classification=req.classification,
            )
            res = svc.ingest_event(event=event, source_api_key=req.source_api_key)
            out.append(
                {
                    "index": idx,
                    "event_hash": res.event_hash,
                    "status": res.status,
                    "mapped_event_type": event.event_type,
                }
            )
        except Exception:
            log.exception("ingest_connector_batch_item_failed connector=%s index=%s", connector_key, idx)
            out.append({"index": idx, "error": "internal_error"})
    return {"connector": connector_key, "results": out}
