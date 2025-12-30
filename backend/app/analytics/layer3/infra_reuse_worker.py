# backend/app/analytics/layer3/infra_reuse_worker.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from app.campaign.models import Campaign
from app.ledger.infra_clusters import InfraCluster
from app.analytics.layer3.claim_types import CAMPAIGN_REUSES_INFRA
from app.db.base import utcnow


def run_infra_reuse_claims(
    *,
    db: Session,
    window_key: str,
    window_start: datetime,
    window_end: datetime,
) -> int:
    """
    Detect campaigns that reuse the same infra clusters.
    Writes campaign_claim rows only (no graph writes here).

    Deterministic.
    Idempotent via unique index.
    """

    # Step 1: load infra clusters in window
    clusters = (
        db.query(InfraCluster)
        .filter(InfraCluster.last_seen >= window_start)
        .filter(InfraCluster.first_seen <= window_end)
        .all()
    )

    # cluster_id -> campaigns
    infra_to_campaigns: Dict[str, List[str]] = {}

    for c in clusters:
        # campaigns already materialized elsewhere
        rows = db.execute(
            """
            SELECT DISTINCT campaign_id
            FROM campaign_entity
            WHERE entity_key = :key
            """,
            {"key": f"infra_cluster:{c.cluster_id}"},
        ).fetchall()

        for (cid,) in rows:
            infra_to_campaigns.setdefault(c.cluster_id, []).append(str(cid))

    created = 0

    for infra_id, campaigns in infra_to_campaigns.items():
        if len(campaigns) < 2:
            continue

        # pairwise campaign claims
        for i in range(len(campaigns)):
            for j in range(i + 1, len(campaigns)):
                a = campaigns[i]
                b = campaigns[j]

                db.execute(
                    """
                    INSERT INTO campaign_claim (
                        id,
                        claim_type,
                        subject_campaign_id,
                        object_campaign_id,
                        window_key,
                        window_start,
                        window_end,
                        confidence,
                        reason_codes,
                        infra_cluster_ids,
                        details_json
                    )
                    VALUES (
                        :id,
                        :claim_type,
                        :a,
                        :b,
                        :window_key,
                        :window_start,
                        :window_end,
                        :confidence,
                        :reason_codes,
                        :infra_ids,
                        :details
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    {
                        "id": str(uuid.uuid4()),
                        "claim_type": CAMPAIGN_REUSES_INFRA,
                        "a": a,
                        "b": b,
                        "window_key": window_key,
                        "window_start": window_start,
                        "window_end": window_end,
                        "confidence": 0.75,  # MVP fixed score
                        "reason_codes": ["INFRA_CLUSTER_REUSE"],
                        "infra_ids": [infra_id],
                        "details": {
                            "shared_infra_cluster": infra_id,
                            "window": window_key,
                        },
                    },
                )
                created += 1

    return created
