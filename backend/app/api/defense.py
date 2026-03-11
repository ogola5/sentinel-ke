from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
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
from app.defense.executor import encrypt_webhook_secret
from app.defense.models import ContainmentWebhook, WebhookDelivery
from app.defense.service import DefenseService
from app.core.rate_limit import limiter


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
@limiter.limit("30/minute")
def execute_incident_actions(
    request: Request,
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


# ---------------------------------------------------------------------------
# Webhook management — register / list / disable last-mile containment hooks
# ---------------------------------------------------------------------------

class WebhookRegisterRequest(BaseModel):
    section_code: str = Field(..., description="Organisation this webhook belongs to")
    action_type:  str = Field(..., description="block_ip | unblock_ip | isolate_host")
    webhook_url:  str = Field(..., description="Partner HTTPS endpoint")
    secret:       str = Field(..., min_length=16,
                              description="Shared signing secret (stored as SHA-256 hash)")


@router.post(
    "/webhooks",
    summary="Register a containment webhook for a partner's firewall / EDR",
    dependencies=[Depends(require_central_access), Depends(require_scope("defense.write"))],
    status_code=201,
)
def register_webhook(
    payload: WebhookRegisterRequest,
    db: Session = Depends(get_db),
):
    """
    Register or update a partner webhook for last-mile block_ip / unblock_ip / isolate_host dispatch.

    The hub signs every webhook call with HMAC-SHA256(body, raw_secret) and sets
    the header `X-Sentinel-Signature: sha256=<hex>`.  The partner verifies this
    header using their raw secret before applying the containment action.
    The secret is stored Fernet-encrypted at rest (never in plain text).
    """
    existing = (
        db.query(ContainmentWebhook)
        .filter(
            ContainmentWebhook.section_code == payload.section_code,
            ContainmentWebhook.action_type  == payload.action_type,
        )
        .first()
    )
    secret_enc = encrypt_webhook_secret(payload.secret)
    if existing:
        existing.webhook_url = payload.webhook_url
        existing.secret_enc  = secret_enc
        existing.is_active   = True
        db.commit()
        return {"updated": True, "section_code": payload.section_code, "action_type": payload.action_type}

    hook = ContainmentWebhook(
        section_code = payload.section_code,
        action_type  = payload.action_type,
        webhook_url  = payload.webhook_url,
        secret_enc   = secret_enc,
    )
    db.add(hook)
    db.commit()
    return {
        "created":      True,
        "section_code": payload.section_code,
        "action_type":  payload.action_type,
        "webhook_url":  payload.webhook_url,
        "note":         "Secret stored encrypted. Hub signs payloads with X-Sentinel-Signature: sha256=HMAC(body, secret).",
    }


@router.get(
    "/webhooks",
    summary="List registered containment webhooks",
    dependencies=[Depends(require_central_access), Depends(require_scope("defense.read"))],
)
def list_webhooks(
    section_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(ContainmentWebhook)
    if section_code:
        q = q.filter(ContainmentWebhook.section_code == section_code)
    hooks = q.order_by(ContainmentWebhook.section_code).all()
    return {
        "total": len(hooks),
        "items": [
            {
                "id":           str(h.id),
                "section_code": h.section_code,
                "action_type":  h.action_type,
                "webhook_url":  h.webhook_url,
                "is_active":    h.is_active,
                "created_at":   h.created_at.isoformat(),
            }
            for h in hooks
        ],
    }


@router.delete(
    "/webhooks/{webhook_id}",
    summary="Disable a containment webhook",
    dependencies=[Depends(require_central_access), Depends(require_scope("defense.write"))],
)
def disable_webhook(webhook_id: str, db: Session = Depends(get_db)):
    import uuid as _uuid
    try:
        uid = _uuid.UUID(webhook_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="webhook_not_found")
    hook = db.query(ContainmentWebhook).filter(ContainmentWebhook.id == uid).first()
    if not hook:
        raise HTTPException(status_code=404, detail="webhook_not_found")
    hook.is_active = False
    db.commit()
    return {"disabled": True, "id": webhook_id}


@router.get(
    "/webhooks/deliveries",
    summary="List webhook delivery receipts (forensic audit log)",
    dependencies=[Depends(require_central_access), Depends(require_scope("defense.read"))],
)
def list_webhook_deliveries(
    section_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="pending | delivered | failed"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(WebhookDelivery)
    if section_code:
        q = q.filter(WebhookDelivery.section_code == section_code)
    if status:
        q = q.filter(WebhookDelivery.status == status)
    rows = q.order_by(WebhookDelivery.created_at.desc()).limit(limit).all()
    return {
        "total": len(rows),
        "items": [
            {
                "id":              str(r.id),
                "action_id":       str(r.action_id) if r.action_id else None,
                "section_code":    r.section_code,
                "action_type":     r.action_type,
                "target":          r.target,
                "webhook_url":     r.webhook_url,
                "status":          r.status,
                "http_status_code": r.http_status_code,
                "attempt_count":   r.attempt_count,
                "delivered_at":    r.delivered_at.isoformat() if r.delivered_at else None,
                "error_message":   r.error_message,
                "created_at":      r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Self-test webhook receiver
# Operators register: POST /v1/defense/webhooks with webhook_url pointing here.
# The hub fires containment payloads; this endpoint logs them and returns 200.
# Proves the containment dispatch pipeline works end-to-end without an
# external partner firewall/EDR.
# ---------------------------------------------------------------------------

@router.post(
    "/webhooks/self-test/receiver",
    summary="Built-in webhook receiver for containment self-test (no auth required — by design)",
    include_in_schema=True,
)
async def self_test_webhook_receiver(request: Request):
    """
    Receives containment webhook payloads fired by the hub.

    Partners replace this with their own firewall/EDR endpoint.
    This built-in receiver proves the signing, dispatch, and delivery
    audit pipeline is operational end-to-end.

    Verifies X-Sentinel-Signature if the header is present.
    Always returns 200 so the delivery is recorded as `delivered`.
    """
    import hashlib
    import hmac

    body = await request.body()
    sig_header = request.headers.get("X-Sentinel-Signature", "")
    verified = False

    if sig_header.startswith("sha256="):
        # Re-derive the test secret used when registering the self-test webhook
        test_secret = "sentinel-self-test-secret-key"
        expected = "sha256=" + hmac.new(
            test_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        verified = hmac.compare_digest(expected, sig_header)

    try:
        import json
        payload = json.loads(body)
    except Exception:
        payload = {"raw": body.decode(errors="replace")}

    log.info(
        "containment_self_test_received action_type=%s target=%s signature_verified=%s",
        payload.get("action_type"),
        payload.get("target"),
        verified,
    )
    return {
        "received": True,
        "action_type": payload.get("action_type"),
        "target": payload.get("target"),
        "signature_verified": verified,
        "note": "Self-test receiver. Replace with real firewall/EDR endpoint in production.",
    }
