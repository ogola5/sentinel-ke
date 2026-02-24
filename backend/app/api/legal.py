from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination_params
from app.legal.schemas import (
    ApprovalPayloadRequest,
    LegalAuthorizationRequest,
    LegalEvidenceExportRequest,
    LegalOrderCreate,
    LegalOrderRevoke,
    LegalScanPlanRequest,
)
from app.legal.service import LegalAuthorizationService, build_approval_message

router = APIRouter(prefix="/v1/legal", tags=["legal"])
log = logging.getLogger("sentinel.api.legal")


@router.post("/orders")
def create_legal_order(payload: LegalOrderCreate, db: Session = Depends(get_db)):
    try:
        return LegalAuthorizationService(db).create_order(payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except IntegrityError:
        # Unique order_number collision or other DB constraint.
        raise HTTPException(status_code=409, detail="legal_order_conflict")
    except Exception:
        log.exception("create_legal_order_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/orders/{order_id}/revoke")
def revoke_legal_order(order_id: str, payload: LegalOrderRevoke, db: Session = Depends(get_db)):
    try:
        return LegalAuthorizationService(db).revoke_order(order_id, payload)
    except ValueError as e:
        detail = str(e)
        if detail == "legal_order_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=422, detail=detail)
    except Exception:
        log.exception("revoke_legal_order_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/orders")
def list_legal_orders(
    pagination: dict = Depends(pagination_params),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return LegalAuthorizationService(db).list_orders(
        status=status,
        limit=pagination["limit"],
        offset=pagination["offset"],
    )


@router.post("/authorize")
def authorize_operation(payload: LegalAuthorizationRequest, db: Session = Depends(get_db)):
    try:
        return LegalAuthorizationService(db).authorize(payload)
    except ValueError as e:
        detail = str(e)
        if detail == "legal_order_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=422, detail=detail)
    except Exception:
        log.exception("authorize_operation_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/approval/payload")
def approval_payload(payload: ApprovalPayloadRequest):
    message, digest = build_approval_message(payload)
    return {"message": message, "digest_sha256": digest}


@router.post("/grants/verify")
def verify_grant(
    action_type: str,
    target: str,
    model_action: str | None = None,
    model_version: str | None = None,
    x_legal_grant_token: str | None = Header(default=None, alias="X-Legal-Grant-Token"),
    mark_used: bool = False,
    actor_id: str = "api",
    db: Session = Depends(get_db),
):
    if not x_legal_grant_token:
        raise HTTPException(status_code=401, detail="missing_legal_grant_token")
    try:
        return LegalAuthorizationService(db).verify_grant_token(
            execution_token=x_legal_grant_token,
            action_type=action_type,
            target=target,
            model_action=model_action,
            model_version=model_version,
            mark_used=mark_used,
            actor_id=actor_id,
        )
    except ValueError as e:
        detail = str(e)
        if detail == "grant_token_not_found":
            # Avoid token enumeration.
            raise HTTPException(status_code=403, detail="grant_not_allowed")
        if detail in {"legal_order_not_found", "order_not_active", "outside_order_window"}:
            raise HTTPException(status_code=403, detail=detail)
        if detail in {
            "grant_not_allowed",
            "grant_expired",
            "grant_action_mismatch",
            "grant_target_mismatch",
            "grant_model_scope_mismatch",
            "grant_token_already_used",
        }:
            raise HTTPException(status_code=403, detail=detail)
        raise HTTPException(status_code=422, detail=detail)
    except Exception:
        log.exception("verify_grant_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/grants")
def list_legal_grants(
    pagination: dict = Depends(pagination_params),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return LegalAuthorizationService(db).list_grants(
        status=status,
        limit=pagination["limit"],
        offset=pagination["offset"],
    )


@router.post("/scan-plan")
def build_scan_plan(payload: LegalScanPlanRequest, db: Session = Depends(get_db)):
    try:
        return LegalAuthorizationService(db).build_greedy_scan_plan(payload)
    except ValueError as e:
        detail = str(e)
        if detail == "legal_order_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=422, detail=detail)
    except Exception:
        log.exception("build_scan_plan_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/evidence/export")
def export_legal_evidence(payload: LegalEvidenceExportRequest, db: Session = Depends(get_db)):
    try:
        return LegalAuthorizationService(db).export_evidence_bundle(payload)
    except ValueError as e:
        detail = str(e)
        if detail in {"legal_order_not_found", "campaign_not_found"}:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=422, detail=detail)
    except Exception:
        log.exception("export_legal_evidence_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/evidence/bundles")
def list_evidence_bundles(
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    return LegalAuthorizationService(db).list_evidence_bundles(
        limit=pagination["limit"],
        offset=pagination["offset"],
    )


@router.get("/evidence/bundles/{bundle_id}")
def get_evidence_bundle(bundle_id: str, db: Session = Depends(get_db)):
    try:
        return LegalAuthorizationService(db).get_evidence_bundle(bundle_id)
    except ValueError as e:
        if str(e) == "legal_evidence_bundle_not_found":
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        log.exception("get_evidence_bundle_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/evidence/bundles/{bundle_id}/anchor")
def get_evidence_anchor(bundle_id: str, db: Session = Depends(get_db)):
    try:
        return LegalAuthorizationService(db).get_evidence_anchor(bundle_id)
    except ValueError as e:
        detail = str(e)
        if detail in {"legal_evidence_bundle_not_found", "legal_evidence_anchor_not_found"}:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=422, detail=detail)
    except Exception:
        log.exception("get_evidence_anchor_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/evidence/bundles/{bundle_id}/anchor/refresh")
def refresh_evidence_anchor(
    bundle_id: str,
    actor_id: str = "api",
    db: Session = Depends(get_db),
):
    try:
        return LegalAuthorizationService(db).refresh_evidence_anchor(bundle_id=bundle_id, actor_id=actor_id)
    except ValueError as e:
        detail = str(e)
        if detail == "legal_evidence_bundle_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=422, detail=detail)
    except Exception:
        log.exception("refresh_evidence_anchor_failed")
        raise HTTPException(status_code=500, detail="internal_error")
