"""
Sentinel-KE Edge Agent — FastAPI Application
=============================================

Provides three operational endpoints so the National Command Centre (or a
local operator) can monitor and trigger this edge agent:

  GET  /status      Liveness + last run summary
  POST /run         Trigger an immediate GNN run → publish cycle
  GET  /patterns    Last run's high-risk results (in-memory, not persisted)

The scheduler loop runs in a FastAPI lifespan background task and calls
the GNN → publish pipeline every `run_interval_s` seconds.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException

from app.config import settings
from app.connector import get_connector
from app.gnn_runner import GNNResult, run_gnn
from app.publisher import publish

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory state (single-process; fine for edge agent)
# ---------------------------------------------------------------------------

_state: Dict[str, Any] = {
    "last_run_at":      None,
    "last_run_status":  "never",
    "last_error":       None,
    "last_accepted":    0,
    "last_high_risk":   0,
    "last_scored":      0,
    "run_count":        0,
    "last_results":     [],  # List[GNNResult] — most recent run
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def _run_pipeline() -> Dict[str, Any]:
    """Fetch → GNN → publish. Returns summary dict."""
    window_end   = _utcnow()
    window_start = window_end - timedelta(hours=settings.window_hours)

    connector = get_connector()
    records   = connector.fetch(window_start, window_end)
    logger.info("Fetched %d entity records for window [%s → %s]", len(records), window_start.isoformat(), window_end.isoformat())

    results = run_gnn(records, window_start, window_end)
    logger.info("GNN scored %d entities", len(results))

    hub_resp = publish(results, window_start, window_end)

    high_risk = [r for r in results if r.risk_score >= settings.risk_threshold]
    _state["last_run_at"]     = _utcnow().isoformat()
    _state["last_run_status"] = "ok"
    _state["last_error"]      = None
    _state["last_accepted"]   = hub_resp.get("accepted", 0)
    _state["last_high_risk"]  = len(high_risk)
    _state["last_scored"]     = len(results)
    _state["run_count"]      += 1
    _state["last_results"]    = results

    return {
        "entities_scored":  len(results),
        "high_risk_count":  len(high_risk),
        "hub_accepted":     hub_resp.get("accepted", 0),
        "window_start":     window_start.isoformat(),
        "window_end":       window_end.isoformat(),
    }


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------

async def _scheduler_loop():
    logger.info("Scheduler started — interval: %ds", settings.run_interval_s)
    while True:
        try:
            summary = await asyncio.get_event_loop().run_in_executor(None, _run_pipeline)
            logger.info("Scheduled run complete: %s", summary)
        except Exception as exc:
            _state["last_run_status"] = "error"
            _state["last_error"]      = str(exc)
            logger.exception("Scheduled GNN run failed: %s", exc)
        await asyncio.sleep(settings.run_interval_s)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    task = asyncio.create_task(_scheduler_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Sentinel-KE Edge Agent",
    description=(
        "Runs a local GNN on partner data and streams privacy-preserving "
        "risk patterns to the Sentinel-KE national hub."
    ),
    version="1.0.0",
    lifespan=_lifespan,
)


@app.get("/status", summary="Agent liveness and last-run summary")
def status() -> Dict[str, Any]:
    return {
        "partner_id":        settings.partner_id,
        "hub_url":           settings.hub_url,
        "data_source":       settings.data_source,
        "run_interval_s":    settings.run_interval_s,
        "risk_threshold":    settings.risk_threshold,
        "model_version":     settings.model_version,
        "last_run_at":       _state["last_run_at"],
        "last_run_status":   _state["last_run_status"],
        "last_error":        _state["last_error"],
        "last_scored":       _state["last_scored"],
        "last_high_risk":    _state["last_high_risk"],
        "last_accepted":     _state["last_accepted"],
        "run_count":         _state["run_count"],
    }


@app.post("/run", summary="Trigger an immediate GNN run and publish cycle", status_code=200)
def trigger_run() -> Dict[str, Any]:
    try:
        summary = _run_pipeline()
        return {"status": "ok", **summary}
    except Exception as exc:
        _state["last_run_status"] = "error"
        _state["last_error"]      = str(exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/patterns", summary="Last run's high-risk entity results (in-memory)")
def last_patterns(min_risk: float = 0.0, limit: int = 200) -> List[Dict[str, Any]]:
    results: List[GNNResult] = _state["last_results"]
    filtered = [r for r in results if r.risk_score >= min_risk]
    filtered.sort(key=lambda r: r.risk_score, reverse=True)
    return [
        {
            "entity_type":  r.entity_type,
            "risk_score":   r.risk_score,
            "uncertainty":  r.uncertainty,
            "fraud_family": r.fraud_family,
            "chain_score":  r.chain_score,
            "risk_flags":   r.risk_flags,
            # entity_key is NOT returned — it never leaves the agent's runtime
        }
        for r in filtered[:limit]
    ]
