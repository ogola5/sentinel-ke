from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.campaign.claims import CampaignClaim

# Minimal Layer-3 worker: emit one claim type when campaigns share the same infra cluster.
# Deterministic, idempotent, no windows/cursors/Neo4j.


CLAIM_TYPE = "SHARED_INFRA_CLUSTER"
WINDOW = "ALL_TIME"
REASON_CODES = ["SHARED_INFRA_CLUSTER"]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _pairwise(items: List[str]):
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            yield items[i], items[j]


def run_shared_infra_claims(
    *,
    db: Session,
    confidence: float = 0.75,
) -> int:
    """
    Inserts campaign_claim rows when two or more campaigns reference the same infra_cluster.

    Returns: number of new rows inserted.
    """
    # cluster_id, first_seen, last_seen, campaigns[]
    rows = db.execute(
        text(
            """
            SELECT
              ic.cluster_id,
              ic.first_seen,
              ic.last_seen,
              array_agg(DISTINCT ce.campaign_id) AS campaigns
            FROM infra_cluster AS ic
            JOIN campaign_entity AS ce
              ON ce.entity_key = ('infra_cluster:' || ic.cluster_id)
            GROUP BY ic.cluster_id, ic.first_seen, ic.last_seen
            HAVING COUNT(DISTINCT ce.campaign_id) >= 2
            """
        )
    ).fetchall()

    created = 0
    now = _now_utc()

    for cluster_id, first_seen, last_seen, campaigns in rows:
        if not campaigns or len(campaigns) < 2:
            continue

        # stable ordering prevents duplicate symmetric pairs
        campaign_ids = sorted(str(c) for c in set(campaigns))
        window_start = first_seen or now
        window_end = last_seen or window_start

        for subj, obj in _pairwise(campaign_ids):
            stmt = (
                insert(CampaignClaim)
                .values(
                    id=uuid.uuid4(),
                    claim_type=CLAIM_TYPE,
                    subject_campaign_id=subj,
                    object_campaign_id=obj,
                    window=WINDOW,
                    window_start=window_start,
                    window_end=window_end,
                    confidence=confidence,
                    reason_codes=REASON_CODES,
                    evidence_hashes=[],
                    infra_cluster_ids=[cluster_id],
                    details_json={"shared_infra_cluster": cluster_id},
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        "claim_type",
                        "subject_campaign_id",
                        "object_campaign_id",
                        "window",
                        "window_end",
                    ]
                )
            )
            res = db.execute(stmt)
            created += res.rowcount or 0

    db.commit()
    return created


def main():
    from app.ledger.db import SessionLocal

    db = SessionLocal()
    try:
        n = run_shared_infra_claims(db=db)
        print(f"shared_infra_claims inserted={n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
