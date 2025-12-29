from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.ledger.infra_clusters import InfraCluster, InfraClusterMember
from app.ledger.infra_evidence import InfraClusterEvidence
from app.graph.neo4j_driver import get_driver  # uses your existing driver helper


# ----------------------------
# Mapping helpers
# ----------------------------

def _split_entity_key(entity_key: str) -> Tuple[str, str]:
    """
    entity_key is stored as stable key like:
      ip:41.90.1.2
      domain:example.com
      provider:AS1234

    Returns: (kind, raw_value)
    """
    if not entity_key or ":" not in entity_key:
        raise ValueError(f"invalid entity_key: {entity_key!r}")
    kind, raw = entity_key.split(":", 1)
    kind = kind.strip().lower()
    raw = raw.strip()
    if not kind or not raw:
        raise ValueError(f"invalid entity_key: {entity_key!r}")
    return kind, raw


def _neo4j_label_for_kind(kind: str) -> str:
    if kind == "ip":
        return "IP"
    if kind == "domain":
        return "Domain"
    if kind == "provider":
        return "Provider"
    raise ValueError(f"unsupported infra member kind: {kind!r}")


def _neo4j_key_field_for_label(label: str) -> str:
    # Keep this consistent with how you model entity uniqueness in Neo4j.
    # If you already use `key` everywhere, replace these with `key`.
    if label == "IP":
        return "ip"
    if label == "Domain":
        return "domain"
    if label == "Provider":
        return "provider_id"
    raise ValueError(f"unsupported label: {label!r}")


def _dt(v: Optional[datetime]) -> Optional[str]:
    return v.isoformat() if v else None


# ----------------------------
# Projector
# ----------------------------

@dataclass(frozen=True)
class ProjectInfraResult:
    clusters_projected: int
    members_projected: int
    edges_projected: int


class InfraNeo4jProjector:
    """
    Layer-2 projector: Postgres infra_cluster* -> Neo4j

    - MERGE InfraCluster node
    - MERGE member entity nodes (IP/Domain/Provider)
    - MERGE membership edge
    - OPTIONAL: MERGE Campaign node + USES_INFRA edge using cluster.summary_json['campaign_id']
    """

    def __init__(self, db: Session):
        self.db = db
        self.driver = get_driver()

    def ensure_schema(self) -> None:
        """
        Create constraints if missing. Safe to run repeatedly.
        Adjust property names if your Neo4j schema uses different keys.
        """
        statements = [
            # InfraCluster identity
            "CREATE CONSTRAINT infra_cluster_id IF NOT EXISTS "
            "FOR (c:InfraCluster) REQUIRE c.cluster_id IS UNIQUE",

            # IP/Domain/Provider identities (adjust if you already enforce elsewhere)
            "CREATE CONSTRAINT ip_unique IF NOT EXISTS FOR (n:IP) REQUIRE n.ip IS UNIQUE",
            "CREATE CONSTRAINT domain_unique IF NOT EXISTS FOR (n:Domain) REQUIRE n.domain IS UNIQUE",
            "CREATE CONSTRAINT provider_unique IF NOT EXISTS FOR (n:Provider) REQUIRE n.provider_id IS UNIQUE",

            # Campaign identity (optional)
            "CREATE CONSTRAINT campaign_id IF NOT EXISTS FOR (c:Campaign) REQUIRE c.campaign_id IS UNIQUE",
        ]
        with self.driver.session() as s:
            for cy in statements:
                s.run(cy)

    def project_cluster(self, cluster_id: str) -> ProjectInfraResult:
        cluster = (
            self.db.query(InfraCluster)
            .filter(InfraCluster.cluster_id == cluster_id)
            .first()
        )
        if not cluster:
            raise ValueError("cluster not found")

        members = (
            self.db.query(InfraClusterMember)
            .filter(InfraClusterMember.cluster_id == cluster_id)
            .all()
        )

        evidence = (
            self.db.query(InfraClusterEvidence)
            .filter(InfraClusterEvidence.cluster_id == cluster_id)
            .all()
        )

        return self._write_to_neo4j([cluster], members, evidence)

    def project_recent(self, *, limit: int = 200, kind: Optional[str] = None) -> ProjectInfraResult:
        q = self.db.query(InfraCluster)
        if kind:
            q = q.filter(InfraCluster.kind == kind)
        clusters = q.order_by(InfraCluster.created_at.desc()).limit(limit).all()
        if not clusters:
            return ProjectInfraResult(0, 0, 0)

        cluster_ids = [c.cluster_id for c in clusters]

        members = (
            self.db.query(InfraClusterMember)
            .filter(InfraClusterMember.cluster_id.in_(cluster_ids))
            .all()
        )

        evidence = (
            self.db.query(InfraClusterEvidence)
            .filter(InfraClusterEvidence.cluster_id.in_(cluster_ids))
            .all()
        )

        return self._write_to_neo4j(clusters, members, evidence)

    def _write_to_neo4j(
        self,
        clusters: List[InfraCluster],
        members: List[InfraClusterMember],
        evidence: List[InfraClusterEvidence],
    ) -> ProjectInfraResult:
        # Pre-group for O(n)
        mem_by_cluster: Dict[str, List[InfraClusterMember]] = {}
        for m in members:
            mem_by_cluster.setdefault(m.cluster_id, []).append(m)

        ev_by_cluster: Dict[str, List[InfraClusterEvidence]] = {}
        for e in evidence:
            ev_by_cluster.setdefault(e.cluster_id, []).append(e)

        clusters_projected = 0
        members_projected = 0
        edges_projected = 0

        with self.driver.session() as s:
            # schema is safe; do it once per run
            self.ensure_schema()

            for c in clusters:
                clusters_projected += 1

                # --- MERGE cluster node ---
                cluster_props = {
                    "cluster_id": c.cluster_id,
                    "kind": c.kind,
                    "confidence": float(c.confidence or 0.0),
                    "member_count": int(c.member_count or 0),
                    "first_seen": _dt(c.first_seen),
                    "last_seen": _dt(c.last_seen),
                    "window_start": _dt(c.window_start),
                    "window_end": _dt(c.window_end),
                    "created_at": _dt(c.created_at),
                    "summary_json": c.summary_json or {},
                }

                s.run(
                    """
                    MERGE (cl:InfraCluster {cluster_id: $cluster_id})
                    SET cl.kind = $kind,
                        cl.confidence = $confidence,
                        cl.member_count = $member_count,
                        cl.first_seen = $first_seen,
                        cl.last_seen = $last_seen,
                        cl.window_start = $window_start,
                        cl.window_end = $window_end,
                        cl.created_at = $created_at,
                        cl.summary_json = $summary_json
                    """,
                    **cluster_props,
                )

                # --- OPTIONAL Campaign -> Infra link ---
                campaign_id = None
                try:
                    if isinstance(c.summary_json, dict):
                        campaign_id = c.summary_json.get("campaign_id")
                except Exception:
                    campaign_id = None

                if campaign_id:
                    s.run(
                        """
                        MERGE (ca:Campaign {campaign_id: $campaign_id})
                        MERGE (cl:InfraCluster {cluster_id: $cluster_id})
                        MERGE (ca)-[r:USES_INFRA]->(cl)
                        SET r.first_seen = coalesce(r.first_seen, $first_seen),
                            r.last_seen = $last_seen,
                            r.kind = $kind,
                            r.confidence = $confidence
                        """,
                        campaign_id=str(campaign_id),
                        cluster_id=c.cluster_id,
                        first_seen=_dt(c.first_seen),
                        last_seen=_dt(c.last_seen),
                        kind=c.kind,
                        confidence=float(c.confidence or 0.0),
                    )
                    edges_projected += 1

                # --- membership edges ---
                cluster_members = mem_by_cluster.get(c.cluster_id, [])
                cluster_ev = ev_by_cluster.get(c.cluster_id, [])

                # compress evidence ids + top reasons (small, judge-safe)
                evidence_ids = [e.evidence_id for e in cluster_ev][:200]
                top_reasons = []
                for e in sorted(cluster_ev, key=lambda x: float(x.score or 0.0), reverse=True)[:20]:
                    top_reasons.append(
                        {"reason_code": e.reason_code, "score": float(e.score or 0.0)}
                    )

                for m in cluster_members:
                    kind, raw = _split_entity_key(m.entity_key)
                    label = _neo4j_label_for_kind(kind)
                    key_field = _neo4j_key_field_for_label(label)

                    # MERGE member node + edge
                    s.run(
                        f"""
                        MERGE (n:{label} {{{key_field}: $raw}})
                        MERGE (cl:InfraCluster {{cluster_id: $cluster_id}})
                        MERGE (cl)-[r:INCLUDES]->(n)
                        SET r.first_seen = coalesce(r.first_seen, $first_seen),
                            r.last_seen = $last_seen,
                            r.event_count = $event_count,
                            r.entity_key = $entity_key,
                            r.evidence_ids = $evidence_ids,
                            r.top_reasons = $top_reasons
                        """,
                        raw=raw,
                        cluster_id=c.cluster_id,
                        first_seen=_dt(m.first_seen) or _dt(c.first_seen),
                        last_seen=_dt(m.last_seen) or _dt(c.last_seen),
                        event_count=int(m.event_count or 0),
                        entity_key=m.entity_key,
                        evidence_ids=evidence_ids,
                        top_reasons=top_reasons,
                    )

                    members_projected += 1
                    edges_projected += 1

        return ProjectInfraResult(
            clusters_projected=clusters_projected,
            members_projected=members_projected,
            edges_projected=edges_projected,
        )
