from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthPrincipal,
    get_db,
    pagination_params,
    require_central_access,
    require_request_principal,
    require_scope,
    require_step_up,
)
from app.defense.schemas import (
    BackupAttestationRequest,
    CryptoSnapshotRequest,
    IncidentRunActionBatchRequest,
    IncidentRunCreateRequest,
    RestoreDrillRequest,
    ThreatAlertRefreshRequest,
    VulnerabilityUpsertRequest,
)
from app.defense.service import DefenseService


router = APIRouter(prefix="/v1/defense", tags=["defense"])
log = logging.getLogger("sentinel.api.defense")


def _map_error(detail: str) -> HTTPException:
    if detail in {"incident_run_not_found"}:
        return HTTPException(status_code=404, detail=detail)
    if detail in {"principal_section_code_missing", "current_password_required"}:
        return HTTPException(status_code=403, detail=detail)
    return HTTPException(status_code=422, detail=detail)


@router.post("/vulnerabilities", dependencies=[Depends(require_scope("defense.write"))])
def upsert_vulnerability(
    payload: VulnerabilityUpsertRequest,
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).upsert_vulnerability(payload=payload, principal=principal)
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_upsert_vulnerability_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/vulnerabilities", dependencies=[Depends(require_scope("defense.read"))])
def list_vulnerabilities(
    pagination: dict = Depends(pagination_params),
    status: str | None = Query(default=None),
    section_code: str | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).list_vulnerabilities(
            principal=principal,
            status=status,
            section_code=section_code,
            limit=pagination["limit"],
            offset=pagination["offset"],
        )
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_list_vulnerabilities_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/vulnerabilities/score-sla", dependencies=[Depends(require_scope("defense.write"))])
def score_patch_sla(
    section_code: str | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).score_patch_sla(principal=principal, section_code=section_code)
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_score_patch_sla_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/backups/attest", dependencies=[Depends(require_scope("defense.write"))])
def upsert_backup_attestation(
    payload: BackupAttestationRequest,
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).upsert_backup_attestation(payload=payload, principal=principal)
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_upsert_backup_attestation_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/backups/attest", dependencies=[Depends(require_scope("defense.read"))])
def list_backup_attestations(
    pagination: dict = Depends(pagination_params),
    section_code: str | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).list_backup_attestations(
            principal=principal,
            section_code=section_code,
            limit=pagination["limit"],
            offset=pagination["offset"],
        )
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_list_backup_attestations_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/backups/restore-drills", dependencies=[Depends(require_scope("defense.write"))])
def create_restore_drill(
    payload: RestoreDrillRequest,
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).create_restore_drill(payload=payload, principal=principal)
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_create_restore_drill_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/backups/restore-drills", dependencies=[Depends(require_scope("defense.read"))])
def list_restore_drills(
    pagination: dict = Depends(pagination_params),
    section_code: str | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).list_restore_drills(
            principal=principal,
            section_code=section_code,
            limit=pagination["limit"],
            offset=pagination["offset"],
        )
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_list_restore_drills_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/incidents/runs", dependencies=[Depends(require_scope("defense.write"))])
def create_incident_run(
    payload: IncidentRunCreateRequest,
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).create_incident_run(payload=payload, principal=principal)
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_create_incident_run_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/incidents/runs", dependencies=[Depends(require_scope("defense.read"))])
def list_incident_runs(
    pagination: dict = Depends(pagination_params),
    section_code: str | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).list_incident_runs(
            principal=principal,
            section_code=section_code,
            limit=pagination["limit"],
            offset=pagination["offset"],
        )
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_list_incident_runs_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/incidents/runs/{run_id}/actions", dependencies=[Depends(require_scope("defense.write"))])
def execute_incident_actions(
    run_id: str,
    payload: IncidentRunActionBatchRequest,
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).execute_run_actions(run_id=run_id, payload=payload, principal=principal)
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_execute_incident_actions_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/threat-alerts", dependencies=[Depends(require_scope("defense.read"))])
def list_threat_alerts(
    pagination: dict = Depends(pagination_params),
    alert_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    section_code: str | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).list_threat_alerts(
            principal=principal,
            section_code=section_code,
            alert_type=alert_type,
            severity=severity,
            limit=pagination["limit"],
            offset=pagination["offset"],
        )
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_list_threat_alerts_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/threat-alerts/refresh", dependencies=[Depends(require_scope("defense.write"))])
def refresh_threat_alerts(
    payload: ThreatAlertRefreshRequest,
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).refresh_threat_alerts(payload=payload, principal=principal)
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_refresh_threat_alerts_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/crypto/posture", dependencies=[Depends(require_scope("defense.read"))])
def current_crypto_posture(
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    del principal
    return DefenseService(db).current_crypto_posture()


@router.post(
    "/crypto/posture/snapshot",
    dependencies=[Depends(require_scope("defense.write")), Depends(require_step_up())],
)
def snapshot_crypto_posture(
    payload: CryptoSnapshotRequest,
    principal: AuthPrincipal = Depends(require_central_access),
    db: Session = Depends(get_db),
):
    try:
        return DefenseService(db).snapshot_crypto_posture(payload=payload, principal=principal)
    except ValueError as e:
        raise _map_error(str(e))
    except Exception:
        log.exception("defense_snapshot_crypto_posture_failed")
        raise HTTPException(status_code=500, detail="internal_error")
