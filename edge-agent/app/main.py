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
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.connector import get_connector
from app.gnn_runner import GNNResult, current_artifact_info, run_gnn
from app.publisher import (
    acknowledge_warning as send_warning_acknowledgement,
    check_hub_connectivity,
    fetch_warning_inbox,
    publish,
    send_heartbeat,
)
from app.warning_resolver import (
    load_warning_cache,
    record_warning_ack,
    sync_warning_cache,
    update_hash_index,
)

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
    "is_running":       False,  # True while _run_pipeline() is executing
    "hub_reachable":    None,
    "hub_last_checked_at": None,
    "hub_last_error":   None,
    "last_publish_status": "never",
    "last_heartbeat_at": None,
    "last_heartbeat_status": "never",
    "last_warning_sync_at": None,
    "last_warning_sync_status": "never",
    "last_warning_sync_error": None,
    "last_warning_count": 0,
    "last_hash_index_entries": 0,
    "startup_warning":  None,
}


class WarningAckRequest(BaseModel):
    status: str = "received"
    detail: Dict[str, Any] = Field(default_factory=dict)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _state_path() -> Path:
    return Path(settings.state_path).expanduser()


def _serializable_state() -> Dict[str, Any]:
    return {
        "last_run_at": _state["last_run_at"],
        "last_run_status": _state["last_run_status"],
        "last_error": _state["last_error"],
        "last_accepted": _state["last_accepted"],
        "last_high_risk": _state["last_high_risk"],
        "last_scored": _state["last_scored"],
        "run_count": _state["run_count"],
        "hub_reachable": _state["hub_reachable"],
        "hub_last_checked_at": _state["hub_last_checked_at"],
        "hub_last_error": _state["hub_last_error"],
        "last_publish_status": _state["last_publish_status"],
        "last_heartbeat_at": _state["last_heartbeat_at"],
        "last_heartbeat_status": _state["last_heartbeat_status"],
        "last_warning_sync_at": _state["last_warning_sync_at"],
        "last_warning_sync_status": _state["last_warning_sync_status"],
        "last_warning_sync_error": _state["last_warning_sync_error"],
        "last_warning_count": _state["last_warning_count"],
        "last_hash_index_entries": _state["last_hash_index_entries"],
        "startup_warning": _state["startup_warning"],
    }


def _load_state_from_disk() -> None:
    path = _state_path()
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("edge_agent_state_load_failed path=%s error=%s", path, exc)
        return
    if not isinstance(payload, dict):
        return
    for key, value in payload.items():
        if key in _state and key not in {"last_results", "is_running"}:
            _state[key] = value


def _save_state_to_disk() -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_serializable_state(), indent=2, sort_keys=True), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("edge_agent_state_save_failed path=%s error=%s", path, exc)


def _mark_hub_status(*, reachable: bool, error: Optional[str] = None) -> None:
    _state["hub_reachable"] = reachable
    _state["hub_last_checked_at"] = _utcnow().isoformat()
    _state["hub_last_error"] = error


def _heartbeat_payload() -> Dict[str, Any]:
    artifact = current_artifact_info()
    metadata = dict(artifact.get("metadata") or {})
    return {
        "partner_id": settings.partner_id,
        "agent_version": settings.agent_version,
        "model_version": metadata.get("model_version") or settings.model_version,
        "artifact": artifact,
        "last_run_at": _state["last_run_at"],
        "last_run_status": _state["last_run_status"],
        "run_count": _state["run_count"],
        "data_source": settings.data_source,
        "hub_reachable": _state["hub_reachable"],
        "last_publish_status": _state["last_publish_status"],
        "capabilities": [
            "local_gnn",
            "pattern_publish",
            "signed_heartbeat",
            "warning_inbox",
            "local_hash_resolution",
            f"data_source:{settings.data_source}",
        ],
    }


def _probe_hub_on_startup() -> None:
    try:
        payload = check_hub_connectivity(timeout_s=settings.startup_health_timeout_s)
        _mark_hub_status(reachable=True)
        _state["startup_warning"] = None
        logger.info(
            "Edge agent startup hub connectivity OK: status=%s hub=%s",
            payload.get("status"),
            settings.hub_url,
        )
    except Exception as exc:  # noqa: BLE001
        detail = f"hub_unreachable: {exc}"
        _mark_hub_status(reachable=False, error=detail)
        _state["startup_warning"] = (
            f"Hub is unreachable at {settings.hub_url}. "
            "Check HUB_URL / API key / network before expecting pattern submission."
        )
        logger.warning(_state["startup_warning"])


def _emit_heartbeat() -> None:
    if not settings.heartbeat_enabled:
        return
    try:
        send_heartbeat(_heartbeat_payload(), timeout_s=settings.startup_health_timeout_s)
        _state["last_heartbeat_at"] = _utcnow().isoformat()
        _state["last_heartbeat_status"] = "accepted"
        _mark_hub_status(reachable=True)
    except Exception as exc:  # noqa: BLE001
        detail = f"heartbeat_failed: {exc}"
        _state["last_heartbeat_status"] = "error"
        _mark_hub_status(reachable=False, error=detail)
        logger.warning("Edge heartbeat failed: %s", exc)


def _sync_warning_inbox(*, status: str = "open") -> Dict[str, Any]:
    try:
        payload = fetch_warning_inbox(status=status, timeout_s=settings.startup_health_timeout_s)
        warning_cache = sync_warning_cache(list(payload.get("warnings") or []))
        _state["last_warning_sync_at"] = warning_cache.get("last_synced_at")
        _state["last_warning_sync_status"] = "ok"
        _state["last_warning_sync_error"] = None
        _state["last_warning_count"] = int(warning_cache.get("warning_count") or 0)
        _mark_hub_status(reachable=True)
        return {
            "warning_count": _state["last_warning_count"],
            "last_synced_at": _state["last_warning_sync_at"],
        }
    except Exception as exc:  # noqa: BLE001
        detail = f"warning_sync_failed: {exc}"
        _state["last_warning_sync_status"] = "error"
        _state["last_warning_sync_error"] = detail
        if any(token in str(exc).lower() for token in ("connect", "timed out", "refused", "network", "host")):
            _mark_hub_status(reachable=False, error=detail)
        logger.warning("Edge warning sync failed: %s", exc)
        return {
            "warning_count": int(_state.get("last_warning_count") or 0),
            "error": detail,
        }


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def _run_pipeline(*, force_retrain: bool = False) -> Dict[str, Any]:
    """Fetch → GNN → publish. Returns summary dict."""
    _state["is_running"] = True
    try:
        window_end   = _utcnow()
        window_start = window_end - timedelta(hours=settings.window_hours)

        connector = get_connector()
        records   = connector.fetch(window_start, window_end)
        logger.info("Fetched %d entity records for window [%s → %s]", len(records), window_start.isoformat(), window_end.isoformat())

        results = run_gnn(
            records,
            window_start,
            window_end,
            force_retrain=force_retrain,
            run_index=int(_state.get("run_count") or 0) + 1,
        )
        logger.info("GNN scored %d entities", len(results))
        hash_index_summary = update_hash_index(results, observed_at=window_end)
        _state["last_hash_index_entries"] = int(hash_index_summary.get("entry_count") or 0)

        hub_resp = publish(results, window_start, window_end)
        if hub_resp.get("skipped"):
            _state["last_publish_status"] = "skipped"
        else:
            _state["last_publish_status"] = "ok"
            _mark_hub_status(reachable=True)

        high_risk = [r for r in results if r.risk_score >= settings.risk_threshold]
        _state["last_run_at"]     = _utcnow().isoformat()
        _state["last_run_status"] = "ok"
        _state["last_error"]      = None
        _state["last_accepted"]   = hub_resp.get("accepted", 0)
        _state["last_high_risk"]  = len(high_risk)
        _state["last_scored"]     = len(results)
        _state["run_count"]      += 1
        _state["last_results"]    = results
        _emit_heartbeat()
        _sync_warning_inbox()

        return {
            "entities_scored":  len(results),
            "high_risk_count":  len(high_risk),
            "hub_accepted":     hub_resp.get("accepted", 0),
            "window_start":     window_start.isoformat(),
            "window_end":       window_end.isoformat(),
            "hash_index_entries": _state["last_hash_index_entries"],
            "warning_count": int(_state["last_warning_count"] or 0),
        }
    except Exception as exc:
        _state["last_run_status"] = "error"
        _state["last_error"] = str(exc)
        if _state["last_publish_status"] != "ok":
            _state["last_publish_status"] = "error"
        if any(token in str(exc).lower() for token in ("connect", "timed out", "refused", "network", "host")):
            _mark_hub_status(reachable=False, error=f"pipeline_failed: {exc}")
        raise
    finally:
        _state["is_running"] = False
        _save_state_to_disk()


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
    _load_state_from_disk()
    _probe_hub_on_startup()
    _emit_heartbeat()
    _sync_warning_inbox()
    _save_state_to_disk()
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
        "status":            "busy" if _state["is_running"] else "idle",
        "partner_id":        settings.partner_id,
        "partner_name":      settings.partner_name,
        "hub_url":           settings.hub_url,
        "data_source":       settings.data_source,
        "run_interval_s":    settings.run_interval_s,
        "retrain_every":     settings.retrain_every,
        "risk_threshold":    settings.risk_threshold,
        "model_version":     settings.model_version,
        "agent_version":     settings.agent_version,
        "last_run_at":       _state["last_run_at"],
        "last_run_status":   _state["last_run_status"],
        "last_error":        _state["last_error"],
        "last_scored":       _state["last_scored"],
        "last_high_risk":    _state["last_high_risk"],
        "last_accepted":     _state["last_accepted"],
        "run_count":         _state["run_count"],
        "hub_reachable":     _state["hub_reachable"],
        "hub_last_checked_at": _state["hub_last_checked_at"],
        "hub_last_error":    _state["hub_last_error"],
        "last_publish_status": _state["last_publish_status"],
        "last_heartbeat_at": _state["last_heartbeat_at"],
        "last_heartbeat_status": _state["last_heartbeat_status"],
        "last_warning_sync_at": _state["last_warning_sync_at"],
        "last_warning_sync_status": _state["last_warning_sync_status"],
        "last_warning_sync_error": _state["last_warning_sync_error"],
        "last_warning_count": _state["last_warning_count"],
        "last_hash_index_entries": _state["last_hash_index_entries"],
        "startup_warning":   _state["startup_warning"],
        "artifact":          current_artifact_info(),
    }


@app.post("/run", summary="Trigger an immediate GNN run and publish cycle", status_code=200)
async def trigger_run(force_retrain: bool = False) -> Dict[str, Any]:
    if _state["is_running"]:
        raise HTTPException(status_code=409, detail="A GNN run is already in progress")
    try:
        summary = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _run_pipeline(force_retrain=force_retrain),
        )
        return {"status": "ok", **summary}
    except Exception as exc:
        _state["last_error"] = str(exc)
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


@app.get("/warnings", summary="Resolved warning inbox for the local agency SOC")
def warning_inbox(
    status: Optional[str] = "open",
    locally_resolved: Optional[bool] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    payload = load_warning_cache()
    warnings = list(payload.get("warnings") or [])
    filtered: List[Dict[str, Any]] = []
    for warning in warnings:
        if status and str(warning.get("status") or "") != status:
            continue
        if locally_resolved is not None and bool(warning.get("locally_resolved")) is not locally_resolved:
            continue
        filtered.append(warning)
        if len(filtered) >= limit:
            break
    return {
        "partner_id": settings.partner_id,
        "last_synced_at": payload.get("last_synced_at"),
        "warning_count": len(filtered),
        "warnings": filtered,
    }


@app.post("/warnings/sync", summary="Fetch the latest warning inbox from the hub")
async def trigger_warning_sync(status: str = "open") -> Dict[str, Any]:
    try:
        summary = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _sync_warning_inbox(status=status),
        )
        return {"status": "ok", **summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/warnings/{warning_id}/ack", summary="Acknowledge a warning back to the hub")
async def acknowledge_local_warning(
    warning_id: str,
    payload: WarningAckRequest,
) -> Dict[str, Any]:
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: send_warning_acknowledgement(
                warning_id,
                status=payload.status,
                detail=dict(payload.detail or {}),
                timeout_s=settings.startup_health_timeout_s,
            ),
        )
        record_warning_ack(
            warning_id,
            status=result.get("status") or payload.status,
            detail=dict(payload.detail or {}),
            acknowledged_at=result.get("acknowledged_at"),
        )
        _state["last_warning_sync_status"] = "ok"
        _state["last_warning_sync_error"] = None
        return {"status": "ok", **result}
    except Exception as exc:
        _state["last_warning_sync_status"] = "error"
        _state["last_warning_sync_error"] = str(exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
