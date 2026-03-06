"""
Sentinel-KE Demo Data API
=========================

Provides HTTP endpoints for seeding synthetic training data so the GNN
pipeline can be exercised from the dashboard without SSH access.

Endpoints
---------
POST /v1/demo/ingest-synthetic-gnn-data   — seed cyber-domain snapshots (7 threat families)
POST /v1/demo/ingest-corruption-data      — seed corruption-domain snapshots (6 fraud families)

Both endpoints are restricted to central-access users and are intended for
development / demo environments only.  They are no-ops in production if
APP_ENV != "development" (configurable via DEMO_ENDPOINTS_ENABLED env var).
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import require_central_access

log = logging.getLogger("sentinel.api.demo")
router = APIRouter(prefix="/v1/demo", tags=["demo"])


def _demo_enabled() -> bool:
    explicit = os.getenv("DEMO_ENDPOINTS_ENABLED", "").lower()
    if explicit in ("1", "true", "yes"):
        return True
    if explicit in ("0", "false", "no"):
        return False
    # Default: allowed in development, disabled in production
    from app.core.config import settings
    return getattr(settings, "app_env", "production").lower() == "development"


def _seed_cyber() -> dict:
    from app.demo.seed_large_scale import seed_cyber
    return seed_cyber(n_runs=10, benign_per_run=100)


def _seed_corruption() -> dict:
    from app.demo.seed_large_scale import seed_corruption
    return seed_corruption(n_runs=10, benign_per_run=100)


@router.post("/ingest-synthetic-gnn-data", status_code=202)
def ingest_cyber_synthetic(
    background_tasks: BackgroundTasks,
    _principal=Depends(require_central_access),
):
    """
    Seed the database with large-scale synthetic cyber-domain GNN training data.

    Inserts ~4,000 nodes across 50 community batches (mule networks, DDoS botnets,
    phishing campaigns, SIM swaps, airtime siphoning + benign traffic) into
    graph_feature_snapshot with window_key="Wmid".

    After this returns, trigger training with:
      POST /v1/ai/gnn/train {"domain": "cyber"}
    """
    if not _demo_enabled():
        raise HTTPException(
            status_code=403,
            detail="demo_endpoints_disabled: set DEMO_ENDPOINTS_ENABLED=true to enable",
        )
    background_tasks.add_task(_seed_cyber)
    return {
        "accepted": True,
        "domain": "cyber",
        "window_key": "Wmid",
        "message": (
            "Seeding ~4,000 nodes across 10 community runs (5 threat families each) in background. "
            "Then call POST /v1/ai/gnn/train {\"domain\": \"cyber\"} to retrain."
        ),
    }


@router.post("/ingest-corruption-data", status_code=202)
def ingest_corruption_synthetic(
    background_tasks: BackgroundTasks,
    _principal=Depends(require_central_access),
):
    """
    Seed the database with large-scale synthetic corruption-domain GNN training data.

    Inserts ~3,500 nodes across 10 community runs (tender cartels, ghost workers,
    shell company networks + benign entities) into graph_feature_snapshot with
    window_key="Wcorruption".

    After this returns, trigger training with:
      POST /v1/ai/gnn/train {"domain": "corruption"}
    """
    if not _demo_enabled():
        raise HTTPException(
            status_code=403,
            detail="demo_endpoints_disabled: set DEMO_ENDPOINTS_ENABLED=true to enable",
        )
    background_tasks.add_task(_seed_corruption)
    return {
        "accepted": True,
        "domain": "corruption",
        "window_key": "Wcorruption",
        "message": (
            "Seeding ~3,500 nodes across 10 community runs (3 corruption families each) in background. "
            "Then call POST /v1/ai/gnn/train {\"domain\": \"corruption\"} to retrain."
        ),
    }
