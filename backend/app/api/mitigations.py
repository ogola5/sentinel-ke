from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination_params
from app.analytics.mitigations import Mitigation

router = APIRouter(prefix="/v1/mitigations", tags=["mitigations"])


@router.get("")
def list_mitigations(
    kind: str | None = Query(default=None),
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    q = db.query(Mitigation)
    if kind:
        q = q.filter(Mitigation.kind == kind)

    rows = (
        q.order_by(Mitigation.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )

    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "kind": r.kind,
                "ref_id": r.ref_id,
                "stakeholders": r.stakeholders,
                "payload": r.payload,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/export")
def export_iocs(
    kind: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(Mitigation)
    if kind:
        q = q.filter(Mitigation.kind == kind)

    rows = q.order_by(Mitigation.created_at.desc()).limit(500).all()

    ips: set[str] = set()
    domains: set[str] = set()
    providers: set[str] = set()
    endpoints: set[str] = set()
    actions: list = []

    for r in rows:
        payload = r.payload or {}
        for ip in payload.get("ips", []):
            ips.add(str(ip))
        for d in payload.get("domains", []):
            domains.add(str(d))
        for p in payload.get("providers", []):
            providers.add(str(p))
        for e in payload.get("endpoints", []):
            endpoints.add(str(e))
        for act in payload.get("actions", []):
            actions.append(act)

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "count": len(rows),
        "iocs": {
            "ips": sorted(list(ips)),
            "domains": sorted(list(domains)),
            "providers": sorted(list(providers)),
            "endpoints": sorted(list(endpoints)),
        },
        "actions": actions,
    }
