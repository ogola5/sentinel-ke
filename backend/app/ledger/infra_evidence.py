# # backend/app/ledger/infra_evidence.py
# from __future__ import annotations

# from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index
# from sqlalchemy.dialects.postgresql import JSONB

# from app.ledger.models import Base, utcnow


# class InfraClusterEvidence(Base):
#     """
#     Stores judge-safe explanations: "why these IPs are linked"
#     Keep it small, deterministic, and referenceable from UI.

#     Example reason_code:
#       - ASN_MATCH
#       - ENDPOINT_OVERLAP
#       - SERVICE_OVERLAP
#       - TIME_COOCCURRENCE
#       - UA_SIMILARITY
#       - DOMAIN_REUSE
#       - PREFIX_HEURISTIC
#     """
#     __tablename__ = "infra_cluster_evidence"

#     evidence_id = Column(String, primary_key=True)  # uuid-ish string
#     cluster_id = Column(
#         String,
#         ForeignKey("infra_cluster.cluster_id", ondelete="CASCADE"),
#         nullable=False,
#     )

#     reason_code = Column(String, nullable=False)
#     score = Column(Float, nullable=False, default=0.0)

#     details_json = Column(JSONB, nullable=False, default=dict)
#     created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

#     __table_args__ = (
#         Index("ix_infra_evidence_cluster", "cluster_id"),
#         Index("ix_infra_evidence_reason", "reason_code"),
#     )


# backend/app/ledger/infra_evidence.py
from __future__ import annotations

from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB

from app.ledger.models import Base, utcnow


class InfraClusterEvidence(Base):
    """
    Judge-safe explanations: "why these members are linked".

    NOTE:
      - a_entity_key / b_entity_key are optional (cluster-level evidence allowed)
      - event_hashes is optional; keep small (cap in writer)
    """
    __tablename__ = "infra_cluster_evidence"

    evidence_id = Column(String, primary_key=True)  # uuid-ish string
    cluster_id = Column(
        String,
        ForeignKey("infra_cluster.cluster_id", ondelete="CASCADE"),
        nullable=False,
    )

    # Optional pair context (member-to-member). Store stable entity keys like "ip:1.2.3.4"
    a_entity_key = Column(String, nullable=True)
    b_entity_key = Column(String, nullable=True)

    reason_code = Column(String, nullable=False)
    score = Column(Float, nullable=False, default=0.0)

    # Optional reference material (keep small, deterministic)
    event_hashes = Column(JSONB, nullable=False, default=list)  # list[str]
    source_ids = Column(JSONB, nullable=False, default=list)    # list[str]

    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_infra_evidence_cluster", "cluster_id"),
        Index("ix_infra_evidence_reason", "reason_code"),
        Index("ix_infra_evidence_pair", "a_entity_key", "b_entity_key"),
    )
