from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict

from sqlalchemy.orm import Session

from app.core.config import settings

log = logging.getLogger("sentinel.post_prediction_pipeline")


def run_post_prediction_pipeline(
    *,
    db: Session,
    prediction_type: str,
    window_key: str,
    window_end: datetime,
    model_version: str,
    seed_legal_bundles: bool = False,
) -> Dict[str, object]:
    out: Dict[str, object] = {
        "path_scores_upserted": 0,
        "decision_fusions_upserted": 0,
        "drift_status": "not_run",
        "drift_reports_upserted": 0,
        "containment": {"status": "not_run", "executed": 0, "failed": 0, "skipped": 0},
        "legal_bundle_seed": {"status": "not_run", "created_count": 0},
    }

    if prediction_type != "risk_gnn":
        return out

    try:
        from app.analytics.layer3.path_risk_worker import run_once as run_path_risk  # noqa: PLC0415

        out["path_scores_upserted"] = int(
            run_path_risk(
                db=db,
                prediction_type=prediction_type,
                window_key=window_key,
                window_end=window_end,
            )
            or 0
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("post_pipeline_path_risk_failed err=%s", exc)

    try:
        from app.analytics.layer3.decision_fusion_worker import run_once as run_fusion  # noqa: PLC0415

        out["decision_fusions_upserted"] = int(
            run_fusion(
                db=db,
                prediction_type=prediction_type,
                window_key=window_key,
                window_end=window_end,
            )
            or 0
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("post_pipeline_decision_fusion_failed err=%s", exc)

    try:
        from app.analytics.layer3.drift_worker import run_once as run_drift  # noqa: PLC0415

        drift_out = run_drift(
            db=db,
            prediction_type=prediction_type,
            window_key=window_key,
            model_version=model_version,
        )
        out["drift_status"] = str(drift_out.get("status") or "unknown")
        out["drift_reports_upserted"] = int(drift_out.get("upserted") or 0)
    except Exception as exc:  # noqa: BLE001
        log.warning("post_pipeline_drift_failed err=%s", exc)

    if bool(settings.ai_auto_containment_enabled):
        try:
            from app.analytics.layer3.auto_containment_worker import run_once as run_auto_containment  # noqa: PLC0415

            out["containment"] = run_auto_containment(
                db=db,
                prediction_type=prediction_type,
                window_key=window_key,
                window_end=window_end,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("post_pipeline_auto_containment_failed err=%s", exc)

    if seed_legal_bundles and bool(settings.legal_auto_bundle_enabled):
        try:
            from app.legal.bundle_seed import seed_evidence_bundles_once  # noqa: PLC0415

            out["legal_bundle_seed"] = seed_evidence_bundles_once(
                db=db,
                exported_by="ai-post-pipeline",
                include_stix=True,
                limit=max(1, int(settings.legal_auto_bundle_limit)),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("post_pipeline_legal_bundle_failed err=%s", exc)

    return out
