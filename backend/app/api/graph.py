# app/api/graph.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ledger.db import get_db
from app.graph.service import GraphService

router = APIRouter(prefix="/v1/graph", tags=["graph"])


def _svc(db: Session) -> GraphService:
    # database name is "neo4j" in community by default
    return GraphService(db, neo4j_database="neo4j")


@router.get("/entity/{entity_key}")
def get_entity(entity_key: str, db: Session = Depends(get_db)):
    svc = _svc(db)
    try:
        return {"entity": svc.get_entity(key=entity_key)}
    except KeyError:
        raise HTTPException(status_code=404, detail="entity_not_found")
    finally:
        svc.close()


@router.get("/neighbors/{entity_key}")
def get_neighbors(
    entity_key: str,
    depth: int = Query(1, ge=1, le=3),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    svc = _svc(db)
    try:
        return svc.neighbors(key=entity_key, depth=depth, limit=limit)
    except KeyError:
        raise HTTPException(status_code=404, detail="entity_not_found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        svc.close()


@router.get("/path")
def explain_path(
    from_key: str = Query(..., alias="from"),
    to_key: str = Query(..., alias="to"),
    max_hops: int = Query(4, ge=1, le=8),
    db: Session = Depends(get_db),
):
    svc = _svc(db)
    try:
        return svc.explain_path(from_key=from_key, to_key=to_key, max_hops=max_hops)
    except KeyError:
        raise HTTPException(status_code=404, detail="path_not_found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        svc.close()


@router.get("/evidence/{event_hash}")
def get_evidence(event_hash: str, db: Session = Depends(get_db)):
    svc = _svc(db)
    try:
        return svc.get_evidence_event(event_hash=event_hash)
    except KeyError:
        raise HTTPException(status_code=404, detail="event_not_found")
    finally:
        svc.close()
