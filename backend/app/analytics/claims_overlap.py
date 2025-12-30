# backend/app/analytics/claims_overlap.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.campaign.models import Campaign, CampaignEntity, CampaignEvent
from app.ledger.infra_clusters import InfraCluster, InfraClusterMember
from app.ledger.infra_evidence import InfraClusterEvidence


@dataclass(frozen=True)
class OverlapClaimDraft:
    subject_campaign_id: str
    object_campaign_id: str
    window: str
    window_start: datetime
    window_end: datetime
    confidence: float
    reason_codes: List[str]
    evidence_hashes: List[str]
    infra_cluster_ids: List[str]
    details: Dict


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _bucket_end(now: datetime, minutes: int = 10) -> datetime:
    # floor to bucket boundary for idempotency
    epoch = int(now.timestamp())
    step = minutes * 60
    floored = (epoch // step) * step
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def _cap_list(xs: List[str], n: int) -> List[str]:
    out = []
    seen = set()
    for x in xs:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
        if len(out) >= n:
            break
    return out


def build_campaign_infra_overlap_claims(
    *,
    db: Session,
    window: str = "Wmid",
    bucket_minutes: int = 10,
    max_claims: int = 1000,
    max_evidence: int = 80,
) -> List[OverlapClaimDraft]:
    """
    Layer-3 MVP: campaign overlap via infra cluster reuse.

    Inputs: campaign_entity + infra_cluster_member intersections.
    Outputs: claim drafts with evidence hashes + reason codes.

    Deterministic, replayable if run on the same bucket_end.
    """
    now = _utcnow()
    end = _bucket_end(now, minutes=bucket_minutes)

    if window == "Wshort":
        start = end - timedelta(minutes=10)
    elif window == "Wmid":
        start = end - timedelta(hours=24)
    elif window == "Wlong":
        start = end - timedelta(days=30)
    else:
        raise ValueError("invalid window")

    # 1) Pull recent campaigns
    campaigns = (
        db.query(Campaign)
        .filter(and_(Campaign.last_seen >= start, Campaign.last_seen <= end))
        .all()
    )
    if not campaigns:
        return []

    campaign_ids = [c.id for c in campaigns]

    # 2) Pull campaign entities for those campaigns
    ents = (
        db.query(CampaignEntity)
        .filter(CampaignEntity.campaign_id.in_(campaign_ids))
        .all()
    )
    # Build: entity_key -> set[campaign_id]
    entity_to_campaigns: Dict[str, Set[str]] = {}
    for e in ents:
        entity_to_campaigns.setdefault(e.entity_key, set()).add(str(e.campaign_id))

    # 3) Pull infra clusters in window
    clusters = (
        db.query(InfraCluster)
        .filter(and_(InfraCluster.last_seen >= start, InfraCluster.last_seen <= end))
        .all()
    )
    if not clusters:
        return []

    cluster_ids = [c.cluster_id for c in clusters]
    cluster_by_id = {c.cluster_id: c for c in clusters}

    # 4) Pull infra members and map cluster -> campaigns (via entity intersection)
    members = (
        db.query(InfraClusterMember)
        .filter(InfraClusterMember.cluster_id.in_(cluster_ids))
        .all()
    )

    cluster_to_campaigns: Dict[str, Set[str]] = {}
    cluster_to_shared_entities: Dict[Tuple[str, str], Set[str]] = {}  # (cluster_id, campaign_id) -> entity_keys

    for m in members:
        cset = entity_to_campaigns.get(m.entity_key)
        if not cset:
            continue
        cluster_to_campaigns.setdefault(m.cluster_id, set()).update(cset)
        for cid in cset:
            cluster_to_shared_entities.setdefault((m.cluster_id, cid), set()).add(m.entity_key)

    # 5) Pull infra evidence for clusters to bind event hashes + reasons
    evid_rows = (
        db.query(InfraClusterEvidence)
        .filter(InfraClusterEvidence.cluster_id.in_(cluster_ids))
        .all()
    )
    cluster_reason_codes: Dict[str, List[str]] = {}
    cluster_event_hashes: Dict[str, List[str]] = {}
    for ev in evid_rows:
        cluster_reason_codes.setdefault(ev.cluster_id, []).append(ev.reason_code)
        # event_hashes is JSONB list[str]
        for h in (ev.event_hashes or []):
            cluster_event_hashes.setdefault(ev.cluster_id, []).append(str(h))

    # 6) Pull campaign event hashes for proof timeline (cap for size)
    camp_events = (
        db.query(CampaignEvent)
        .filter(CampaignEvent.campaign_id.in_(campaign_ids))
        .filter(and_(CampaignEvent.occurred_at >= start, CampaignEvent.occurred_at <= end))
        .all()
    )
    campaign_event_hashes: Dict[str, List[str]] = {}
    for ce in camp_events:
        campaign_event_hashes.setdefault(str(ce.campaign_id), []).append(ce.event_hash)

    # 7) Generate overlap claims (campaign pairs per cluster)
    drafts: List[OverlapClaimDraft] = []
    seen_pairs: Set[Tuple[str, str, str]] = set()  # (a,b,window_end_iso) to keep deterministic top-k

    # exclusivity: cluster reused by many campaigns => less confident
    cluster_popularity: Dict[str, int] = {k: len(v) for k, v in cluster_to_campaigns.items()}

    for cluster_id, cids in cluster_to_campaigns.items():
        if len(cids) < 2:
            continue

        cids_sorted = sorted(cids)
        pop = max(1, cluster_popularity.get(cluster_id, 1))
        exclusivity_penalty = min(0.35, 0.05 * (pop - 1))  # more sharing => lower confidence

        base_cluster_conf = float(getattr(cluster_by_id[cluster_id], "confidence", 0.5) or 0.5)

        # pairwise
        for i in range(len(cids_sorted)):
            for j in range(i + 1, len(cids_sorted)):
                a = cids_sorted[i]
                b = cids_sorted[j]

                # deterministic ordering for identity (subject < object)
                subj, obj = (a, b) if a < b else (b, a)

                pair_key = (subj, obj, end.isoformat())
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                shared_a = cluster_to_shared_entities.get((cluster_id, subj), set())
                shared_b = cluster_to_shared_entities.get((cluster_id, obj), set())
                shared_entities = sorted(list(shared_a.union(shared_b)))

                overlap_strength = min(1.0, len(shared_entities) / 10.0)  # saturate at 10
                conf = base_cluster_conf * (0.55 + 0.45 * overlap_strength) - exclusivity_penalty
                conf = max(0.05, min(0.95, conf))

                reasons = ["INFRA_CLUSTER_REUSE"]
                reasons += cluster_reason_codes.get(cluster_id, [])[:3]
                reasons = _cap_list(reasons, 8)

                ev_hashes = []
                ev_hashes += cluster_event_hashes.get(cluster_id, [])
                ev_hashes += campaign_event_hashes.get(subj, [])[:20]
                ev_hashes += campaign_event_hashes.get(obj, [])[:20]
                ev_hashes = _cap_list([str(x) for x in ev_hashes if x], max_evidence)

                drafts.append(
                    OverlapClaimDraft(
                        subject_campaign_id=subj,
                        object_campaign_id=obj,
                        window=window,
                        window_start=start,
                        window_end=end,
                        confidence=conf,
                        reason_codes=reasons,
                        evidence_hashes=ev_hashes,
                        infra_cluster_ids=[cluster_id],
                        details={
                            "cluster_id": cluster_id,
                            "cluster_kind": getattr(cluster_by_id[cluster_id], "kind", None),
                            "cluster_confidence": base_cluster_conf,
                            "cluster_popularity": pop,
                            "shared_entities_sample": shared_entities[:25],
                        },
                    )
                )

                if len(drafts) >= max_claims:
                    return drafts

    # sort for determinism: highest confidence first
    drafts.sort(key=lambda d: (-d.confidence, d.subject_campaign_id, d.object_campaign_id))
    return drafts
