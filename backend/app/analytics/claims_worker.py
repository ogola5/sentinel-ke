# backend/app/analytics/claims_worker.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List

from sqlalchemy.orm import Session

from app.ledger.db import SessionLocal
from app.analytics.claims_overlap import build_campaign_infra_overlap_claims
from app.campaign.claims import CampaignClaim
from app.graph.models import GraphDeltaLog
from app.graph.claim_projection import project_claim_to_delta
from app.ledger.models import utcnow


def _to_uuid(s: str):
    # campaign.id is UUID(as_uuid=True). SQLAlchemy will coerce string UUIDs in most cases.
    return s


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _dedupe_claims(drafts):
    # drafts already sorted; dedupe by (subj,obj,window_end,claim_type)
    seen = set()
    out = []
    for d in drafts:
        k = (d.subject_campaign_id, d.object_campaign_id, d.window, d.window_end.isoformat())
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    return out


def upsert_claims_and_log_deltas(
    *,
    db: Session,
    window: str = "Wmid",
    bucket_minutes: int = 10,
    max_claims: int = 1000,
) -> int:
    drafts = build_campaign_infra_overlap_claims(
        db=db,
        window=window,
        bucket_minutes=bucket_minutes,
        max_claims=max_claims,
    )
    drafts = _dedupe_claims(drafts)
    if not drafts:
        return 0

    processed = 0

    for d in drafts:
        # Upsert by unique constraint: (claim_type, subject, object, window, window_end)
        existing = (
            db.query(CampaignClaim)
            .filter(CampaignClaim.claim_type == "CAMPAIGN_INFRA_REUSE_OVERLAP")
            .filter(CampaignClaim.subject_campaign_id == _to_uuid(d.subject_campaign_id))
            .filter(CampaignClaim.object_campaign_id == _to_uuid(d.object_campaign_id))
            .filter(CampaignClaim.window == d.window)
            .filter(CampaignClaim.window_end == d.window_end)
            .first()
        )

        if existing:
            existing.confidence = float(d.confidence)
            existing.reason_codes = list(d.reason_codes or [])
            existing.evidence_hashes = list(d.evidence_hashes or [])
            existing.infra_cluster_ids = list(d.infra_cluster_ids or [])
            existing.details_json = dict(d.details or {})
            existing.updated_at = utcnow()
            claim = existing
        else:
            claim = CampaignClaim(
                claim_type="CAMPAIGN_INFRA_REUSE_OVERLAP",
                subject_campaign_id=_to_uuid(d.subject_campaign_id),
                object_campaign_id=_to_uuid(d.object_campaign_id),
                window=d.window,
                window_start=d.window_start,
                window_end=d.window_end,
                confidence=float(d.confidence),
                reason_codes=list(d.reason_codes or []),
                evidence_hashes=list(d.evidence_hashes or []),
                infra_cluster_ids=list(d.infra_cluster_ids or []),
                details_json=dict(d.details or {}),
            )
            db.add(claim)

        db.flush()  # ensure claim.id exists

        # Create GraphDeltaLog entry for Neo4j projection
        delta = project_claim_to_delta(db=db, claim=claim)
        row = GraphDeltaLog(
            event_hash=delta.event_hash,
            nodes_json=[n.__dict__ for n in delta.nodes],
            edges_json=[e.__dict__ for e in delta.edges],
            created_at=utcnow(),
        )
        db.add(row)

        processed += 1

    db.commit()
    return processed


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--window", default="Wmid", choices=["Wshort", "Wmid", "Wlong"])
    p.add_argument("--bucket-minutes", type=int, default=10)
    p.add_argument("--max-claims", type=int, default=1000)
    args = p.parse_args()

    db = SessionLocal()
    try:
        n = upsert_claims_and_log_deltas(
            db=db,
            window=args.window,
            bucket_minutes=args.bucket_minutes,
            max_claims=args.max_claims,
        )
        print(f"claims_worker processed={n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
