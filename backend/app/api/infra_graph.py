from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.graph.infra_projector import InfraNeo4jProjector


router = APIRouter(prefix="/v1/graph/infra", tags=["graph-infra"])


@router.post("/project/{cluster_id}")
def project_one_cluster(
    cluster_id: str,
    db: Session = Depends(get_db),
):
    proj = InfraNeo4jProjector(db)
    try:
        res = proj.project_cluster(cluster_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"neo4j projection failed: {e}")

    return {
        "cluster_id": cluster_id,
        "clusters_projected": res.clusters_projected,
        "members_projected": res.members_projected,
        "edges_projected": res.edges_projected,
    }


@router.post("/project-recent")
def project_recent_clusters(
    limit: int = Query(200, ge=1, le=2000),
    kind: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    proj = InfraNeo4jProjector(db)
    try:
        res = proj.project_recent(limit=limit, kind=kind)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"neo4j projection failed: {e}")

    return {
        "limit": limit,
        "kind": kind,
        "clusters_projected": res.clusters_projected,
        "members_projected": res.members_projected,
        "edges_projected": res.edges_projected,
    }
