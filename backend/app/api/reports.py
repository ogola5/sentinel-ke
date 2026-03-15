from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import AuthPrincipal, get_db, require_request_principal
from app.reports.schemas import ReportRequest
from app.reports.service import (
    build_report,
    build_report_filename,
    render_report_html,
    render_report_pdf,
    report_catalog,
)


router = APIRouter(prefix="/v1/reports", tags=["reports"])


def _ensure_legal_access(principal: AuthPrincipal) -> None:
    scopes = set(principal.scopes or [])
    if principal.access_level == "central":
        return
    if "*" in scopes or "legal.write" in scopes or "legal.read" in scopes:
        return
    raise HTTPException(status_code=403, detail="legal_report_requires_central_or_legal_scope")


@router.get("/catalog")
def get_report_catalog():
    return report_catalog()


@router.post("/generate")
def generate_report(
    payload: ReportRequest,
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        if payload.report_type == "legal_evidence_bundle":
            _ensure_legal_access(principal)
        return build_report(db=db, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"report_generation_failed:{exc}")


@router.post("/download")
def download_report(
    payload: ReportRequest,
    principal: AuthPrincipal = Depends(require_request_principal),
    db: Session = Depends(get_db),
):
    try:
        if payload.report_type == "legal_evidence_bundle":
            _ensure_legal_access(principal)
        report = build_report(db=db, payload=payload)
        filename = build_report_filename(report)
        if payload.format == "html":
            content = render_report_html(report)
            return Response(
                content=content,
                media_type="text/html; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}.html"'},
            )
        if payload.format == "pdf":
            content = render_report_pdf(report)
            return Response(
                content=content,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
            )
        body = json.dumps(report, indent=2, sort_keys=False, default=str)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"report_download_failed:{exc}")
