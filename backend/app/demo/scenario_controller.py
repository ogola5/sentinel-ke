import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import require_central_access
from app.demo.run_demo import run_demo


def _demo_enabled() -> bool:
    explicit = os.getenv("DEMO_ENDPOINTS_ENABLED", "").lower()
    if explicit in ("1", "true", "yes"):
        return True
    if explicit in ("0", "false", "no"):
        return False
    from app.core.config import settings
    return getattr(settings, "app_env", "production").lower() == "development"


router = APIRouter(
    prefix="/v1/demo/scenario",
    tags=["demo"],
    dependencies=[Depends(require_central_access)],
)


def _normalize_scenario_name(scenario_name: str) -> str:
    raw = str(scenario_name or "").strip().lower()
    return "fraud" if raw == "sim_swap" else raw


VALID_SCENARIOS = [
    "ddos",
    "malware",
    "vpn",
    "sim_swap",
    "fraud",
    "ddos_vpn",
    "ddos_vpn_fraud",
    "federated_vpn",
    "federated_sim_swap",
    "federated_malware",
    "all",
]


@router.post("/start/{scenario_name}")
async def start_scenario(
    scenario_name: str,
    background_tasks: BackgroundTasks,
):
    """Triggers a specific data scenario through the canonical ingest path."""
    if not _demo_enabled():
        raise HTTPException(status_code=403, detail="demo_endpoints_disabled")
    if scenario_name not in VALID_SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Invalid scenario. Use: {VALID_SCENARIOS}")

    normalized = _normalize_scenario_name(scenario_name)
    background_tasks.add_task(run_demo, scenario=normalized, seed=True)
    return {
        "accepted": True,
        "status": "scheduled",
        "scenario": scenario_name,
        "normalized_scenario": normalized,
        "message": "Scenario replay accepted. Refresh Operations and Events after ingest completes.",
    }

@router.post("/reset")
async def reset_demo():
    """Wipes and re-seeds basic source registry."""
    if not _demo_enabled():
        raise HTTPException(status_code=403, detail="demo_endpoints_disabled")
    from app.ledger.seed_sources import seed
    seed()
    return {"status": "reset_complete"}

@router.post("/replay")
async def trigger_replay(
    background_tasks: BackgroundTasks,
    scenario_name: str = "all",
):
    """Replays the selected scenario through the canonical ingest path."""
    if not _demo_enabled():
        raise HTTPException(status_code=403, detail="demo_endpoints_disabled")
    if scenario_name not in VALID_SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Invalid scenario. Use: {VALID_SCENARIOS}")
    normalized = _normalize_scenario_name(scenario_name)
    background_tasks.add_task(run_demo, scenario=normalized, seed=False)
    return {
        "accepted": True,
        "status": "replay_started",
        "scenario": scenario_name,
        "normalized_scenario": normalized,
    }
