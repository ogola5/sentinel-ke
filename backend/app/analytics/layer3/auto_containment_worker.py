from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.ai_models import AIPrediction
from app.core.config import settings
from app.defense.executor import dispatch_containment_action
from app.defense.models import ContainmentAction, IncidentPlaybookRun


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entity_parts(entity_key: str, entity_type: str) -> Tuple[str, str]:
    raw = str(entity_key or "").strip()
    if ":" in raw:
        prefix, value = raw.split(":", 1)
        return prefix.strip().lower(), value.strip()
    return str(entity_type or "").strip().lower(), raw


def _select_action(
    *,
    entity_key: str,
    entity_type: str,
    allowed_actions: Sequence[str],
) -> Optional[Tuple[str, str]]:
    allowed = {str(a).strip().lower() for a in allowed_actions if str(a).strip()}
    prefix, value = _entity_parts(entity_key, entity_type)

    if prefix == "ip" and "block_ip" in allowed and value:
        return "block_ip", value
    if prefix in {"device_id", "endpoint", "service_id"} and "isolate_host" in allowed:
        return "isolate_host", str(entity_key)
    return None


def _latest_section_for_entity(db: Session, entity_key: str) -> Optional[str]:
    row = db.execute(
        text(
            """
            SELECT el.section_code
            FROM event_entity_index ee
            JOIN event_log el ON el.event_hash = ee.event_hash
            WHERE ee.entity_key = :entity_key
            ORDER BY el.occurred_at DESC
            LIMIT 1
            """
        ),
        {"entity_key": str(entity_key)},
    ).fetchone()
    if not row:
        return None
    sec = str(row[0] or "").strip()
    return sec or None


def _get_or_create_run(
    db: Session,
    *,
    incident_key: str,
    section_code: Optional[str],
) -> IncidentPlaybookRun:
    row = (
        db.query(IncidentPlaybookRun)
        .filter(IncidentPlaybookRun.incident_key == incident_key)
        .filter(IncidentPlaybookRun.section_code == section_code)
        .order_by(IncidentPlaybookRun.created_at.desc())
        .first()
    )
    if row:
        return row
    row = IncidentPlaybookRun(
        incident_key=incident_key,
        section_code=section_code,
        severity="critical",
        status="running",
        created_by="ai-auto-containment",
        metadata_json={
            "automation": True,
            "source": "ai_inference_worker",
            "created_at": _now().isoformat(),
        },
    )
    db.add(row)
    db.flush()
    return row


def run_once(
    *,
    db: Session,
    prediction_type: str,
    window_key: str,
    window_end: datetime,
) -> Dict[str, object]:
    """
    Policy-gated auto-containment from latest AI predictions.

    Designed as a safe "last mile" accelerator:
    - opt-in (`AI_AUTO_CONTAINMENT_ENABLED=true`)
    - threshold + kill-chain gates
    - allow-list of action types
    - max actions per run
    - dry-run mode for demos/tests
    """
    if not bool(settings.ai_auto_containment_enabled):
        return {"status": "disabled", "executed": 0, "skipped": 0}

    allowed = [x.strip().lower() for x in settings.ai_auto_containment_allowed_actions if x.strip()]
    if not allowed:
        return {"status": "no_allowed_actions", "executed": 0, "skipped": 0}

    q = (
        db.query(AIPrediction)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.window_end == window_end)
        .order_by(AIPrediction.score.desc())
    )

    max_actions = max(0, int(settings.ai_auto_containment_max_actions_per_run))
    min_score = float(settings.ai_auto_containment_min_score)
    require_impact = bool(settings.ai_auto_containment_require_impact_stage)
    dry_run = bool(settings.ai_auto_containment_dry_run)

    considered = executed = skipped = failed = 0
    for pred in q:
        if max_actions and (executed + failed) >= max_actions:
            break
        considered += 1

        if bool(pred.abstained) or float(pred.score or 0.0) < min_score:
            skipped += 1
            continue
        if require_impact and str(pred.kill_chain_stage or "").lower() not in {"impact", "actions-on-objectives"}:
            skipped += 1
            continue

        selection = _select_action(
            entity_key=str(pred.entity_key),
            entity_type=str(pred.entity_type),
            allowed_actions=allowed,
        )
        if not selection:
            skipped += 1
            continue
        action_type, target = selection
        section_code = _latest_section_for_entity(db, str(pred.entity_key))
        incident_key = (
            f"auto:{prediction_type}:{window_key}:{window_end.isoformat()}:"
            f"{section_code or 'unknown'}"
        )
        run = _get_or_create_run(db, incident_key=incident_key, section_code=section_code)

        # Dedupe same action for same target inside the same auto run.
        existing = (
            db.query(ContainmentAction)
            .filter(ContainmentAction.run_id == run.id)
            .filter(ContainmentAction.action_type == action_type)
            .filter(ContainmentAction.target == target)
            .first()
        )
        if existing:
            skipped += 1
            continue

        details = {
            "auto_containment": True,
            "prediction_id": str(pred.id),
            "prediction_score": float(pred.score or 0.0),
            "kill_chain_stage": pred.kill_chain_stage,
            "window_key": window_key,
            "window_end": window_end.isoformat(),
            "dry_run": dry_run,
        }
        if dry_run:
            status = "queued"
            details["webhook_status"] = "dry_run"
        else:
            wh_status, wh_details = dispatch_containment_action(
                db=db,
                action_type=action_type,
                target=target,
                section_code=section_code,
            )
            details["webhook_status"] = wh_status
            details["webhook_details"] = wh_details
            status = "executed" if wh_status in {"delivered", "no_webhook"} else "failed"

        db.add(
            ContainmentAction(
                run_id=run.id,
                section_code=section_code,
                action_type=action_type,
                target=target,
                status=status,
                executed_by="ai-auto-containment",
                details_json=details,
            )
        )
        if status == "failed":
            failed += 1
        else:
            executed += 1

    db.commit()
    return {
        "status": "ok",
        "considered": considered,
        "executed": executed,
        "failed": failed,
        "skipped": skipped,
        "min_score": min_score,
        "dry_run": dry_run,
    }
