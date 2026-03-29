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
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

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


class DemoBootstrapRequest(BaseModel):
    domain: Literal["cyber", "corruption", "all"] = "all"
    scenario: Literal["ddos", "malware", "vpn", "sim_swap", "fraud", "ddos_vpn", "ddos_vpn_fraud", "all"] = "ddos_vpn_fraud"
    epochs: int = 40
    cyber_runs: int = 10
    corruption_runs: int = 10
    benign_per_run: int = 100
    seed_sources: bool = True
    allow_demo_real_data_override: bool = True
    allow_demo_fairness_override: bool = True


def _bootstrap_demo_environment(payload: DemoBootstrapRequest) -> dict:
    from app.analytics.corruption.train_worker import run_once as run_corruption_train
    from app.analytics.layer3.gnn_train_worker import run_once as run_cyber_train
    from app.core.config import settings
    from app.demo.run_demo import run_demo
    from app.demo.seed_large_scale import seed_corruption, seed_cyber
    from app.ledger.db import SessionLocal

    summary: dict[str, object] = {
        "domain": payload.domain,
        "scenario": payload.scenario,
        "seed_sources": payload.seed_sources,
        "allow_demo_real_data_override": bool(payload.allow_demo_real_data_override),
        "allow_demo_fairness_override": bool(payload.allow_demo_fairness_override),
        "steps": [],
    }

    if payload.domain in {"cyber", "all"}:
        run_demo(seed=payload.seed_sources, scenario=payload.scenario, mode="db")
        cyber_seed = seed_cyber(n_runs=payload.cyber_runs, benign_per_run=payload.benign_per_run)
        summary["steps"].append({"stage": "cyber_seed", **cyber_seed})

        db = SessionLocal()
        try:
            cyber_result = run_cyber_train(
                db=db,
                window_key="Wmid",
                epochs=max(10, int(payload.epochs)),
                model_version=settings.gnn_model_version,
                allow_demo_real_data_override=bool(
                    payload.allow_demo_real_data_override and settings.gnn_demo_allow_real_data_override
                ),
                allow_demo_fairness_override=bool(
                    payload.allow_demo_fairness_override and settings.gnn_demo_allow_fairness_override
                ),
            )
            summary["steps"].append({"stage": "cyber_train", **cyber_result})
        finally:
            db.close()

    if payload.domain in {"corruption", "all"}:
        corruption_seed = seed_corruption(n_runs=payload.corruption_runs, benign_per_run=payload.benign_per_run)
        summary["steps"].append({"stage": "corruption_seed", **corruption_seed})

        db = SessionLocal()
        try:
            corruption_result = run_corruption_train(
                db=db,
                window_key="Wcorruption",
                epochs=max(10, int(payload.epochs)),
                model_version="corruption-gnn-v1",
                allow_demo_real_data_override=bool(
                    payload.allow_demo_real_data_override and settings.gnn_demo_allow_real_data_override
                ),
                allow_demo_fairness_override=bool(
                    payload.allow_demo_fairness_override and settings.gnn_demo_allow_fairness_override
                ),
            )
            summary["steps"].append({"stage": "corruption_train", **corruption_result})
        finally:
            db.close()

    log.info("demo_bootstrap_complete summary=%s", summary)
    return summary


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


@router.post("/bootstrap", status_code=202)
def bootstrap_demo_environment(
    body: DemoBootstrapRequest,
    background_tasks: BackgroundTasks,
    _principal=Depends(require_central_access),
):
    """
    Bootstrap a usable demo environment end to end.

    Cyber domain:
      1. Replays a Kenyan-style demo scenario into the canonical ingest path
      2. Seeds large-scale synthetic graph snapshots for stable training
      3. Trains the cyber GNN and writes predictions

    Scenario names:
      - ddos
      - malware
      - vpn
      - sim_swap (alias for the fraud / mobile-money chain)
      - fraud
      - ddos_vpn
      - ddos_vpn_fraud

    Corruption domain:
      1. Seeds corruption graph snapshots
      2. Trains the corruption GNN and writes predictions
    """
    if not _demo_enabled():
        raise HTTPException(
            status_code=403,
            detail="demo_endpoints_disabled: set DEMO_ENDPOINTS_ENABLED=true to enable",
        )
    background_tasks.add_task(_bootstrap_demo_environment, body)
    return {
        "accepted": True,
        "domain": body.domain,
        "scenario": body.scenario,
        "message": (
            "Demo bootstrap accepted. This will seed realistic events, seed graph training data, "
            "and train the selected domain(s) in the background."
        ),
    }
