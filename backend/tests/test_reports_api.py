from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import AuthPrincipal
from app.api.reports import _ensure_legal_access, download_report, generate_report
from app.reports.schemas import ReportRequest


def _service_principal() -> AuthPrincipal:
    return AuthPrincipal(
        principal_type="service",
        actor_id="api-key",
        role="service",
        access_level="central",
        scopes=["*"],
    )


def _central_user() -> AuthPrincipal:
    return AuthPrincipal(
        principal_type="user",
        actor_id="u-1",
        user_id="u-1",
        username="central",
        role="central_operator",
        access_level="central",
        scopes=["ai.read", "legal.read"],
        mfa_authenticated=True,
        mfa_at="2026-03-24T10:00:00+00:00",
    )


def test_ensure_legal_access_rejects_service_principal():
    with pytest.raises(HTTPException) as exc:
        _ensure_legal_access(_service_principal())
    assert exc.value.status_code == 403
    assert exc.value.detail == "legal_report_requires_user_session"


def test_generate_report_allows_central_user(monkeypatch):
    monkeypatch.setattr(
        "app.api.reports.build_report",
        lambda *, db, payload: {"report_type": payload.report_type, "title": "ok"},
    )

    out = generate_report(
        payload=ReportRequest(report_type="legal_evidence_bundle", campaign_id="cmp-1", format="json"),
        principal=_central_user(),
        db=object(),
    )

    assert out["report_type"] == "legal_evidence_bundle"


def test_download_report_returns_pdf(monkeypatch):
    monkeypatch.setattr(
        "app.api.reports.build_report",
        lambda *, db, payload: {"report_type": payload.report_type, "report_id": "rep-1", "title": "PDF report"},
    )
    monkeypatch.setattr("app.api.reports.build_report_filename", lambda report: "sentinel-report")
    monkeypatch.setattr("app.api.reports.render_report_pdf", lambda report: b"%PDF-1.7 mock")

    response = download_report(
        payload=ReportRequest(report_type="entity_investigation", entity_key="ip:1.1.1.1", format="pdf"),
        principal=_central_user(),
        db=object(),
    )

    assert response.media_type == "application/pdf"
    assert response.headers["Content-Disposition"] == 'attachment; filename="sentinel-report.pdf"'
    assert response.body.startswith(b"%PDF-1.7")
