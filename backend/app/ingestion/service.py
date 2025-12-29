# app/ingestion/service.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import compute_event_hash, hmac_verify, stable_json_dumps
from app.ingestion.canonicalize import build_hash_canonical_object
from app.ingestion.normalizers import normalize_event
from app.ingestion.pseudonymize import pseudonymize_payload_and_anchors
from app.ingestion.schemas import CanonicalEvent
from app.ingestion.validators import validate_event
from app.ledger.repository import LedgerRepository

# Phase 1.6 — OpenSearch (best-effort)
from app.search.bootstrap import ensure_events_index
from app.search.indexer import index_event, to_index_doc
from app.search.opensearch import get_client

# Phase 2.2 — Graph delta log in Postgres (best-effort)
from app.graph.projector import project_event_to_delta
from app.graph.repository import GraphDeltaRepository

# Phase 2.5 — Redpanda/Kafka internal buses (best-effort)
from app.streaming.messages import build_event_message, build_graph_delta_message
from app.streaming.producer import get_producer


@dataclass(frozen=True)
class IngestResult:
    event_hash: str
    status: str  # accepted | duplicate
    accepted_at: str  # ISO UTC
    source_id: str
    source_type: str
    classification: str
    signature_valid: bool


# --- Anchor sanitization (prevents person_h:person_h:demo1 etc.) ---
_PREFIXED_KEYS = {"person_h", "phone_h", "account_h"}


def _strip_known_prefix(key: str, value: Any) -> Any:
    """
    If anchor key is in _PREFIXED_KEYS and the value is like "person_h:demo1",
    strip the "person_h:" portion and return "demo1".

    Leaves non-strings and other keys unchanged.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value

    v = value.strip()
    if v == "":
        return value

    if key in _PREFIXED_KEYS:
        prefix = f"{key}:"
        if v.startswith(prefix):
            return v[len(prefix) :].strip()

    return value


def sanitize_anchors(anchors: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enforces: anchors contain RAW identifiers only (no internal graph prefixes).
    Complexity: O(a) where a = number of anchors.
    """
    out: Dict[str, Any] = {}
    for k, v in (anchors or {}).items():
        out[k] = _strip_known_prefix(k, v)
    return out


class IngestionService:
    """
    Evidence-grade ingestion pipeline.

    Guarantees:
    - deterministic hashing
    - append-only ledger (source of truth)
    - idempotency (duplicate detection)
    - best-effort OpenSearch indexing
    - best-effort graph delta logging (Postgres)
    - best-effort Kafka publishing (Redpanda)
    """

    def __init__(self, db: Session, *, pseudonym_salt: Optional[str] = None):
        self.db = db
        self.ledger = LedgerRepository(db)
        self.graph_repo = GraphDeltaRepository(db)
        self.pseudonym_salt = pseudonym_salt

    def ingest_event(
        self,
        *,
        event: CanonicalEvent,
        source_api_key: str,
        signature_hex: Optional[str] = None,
        signing_secret: Optional[str] = None,
        enforce_signature: bool = False,
    ) -> IngestResult:
        received_at = datetime.now(timezone.utc)

        # 1) Resolve + validate source
        source = self.ledger.get_source_by_api_key(source_api_key)
        if not source:
            raise PermissionError("Invalid source API key")
        self.ledger.ensure_source_active(source)

        # 2) Normalize + validate envelope
        event = normalize_event(event)
        validate_event(event)

        # 3) Pseudonymize sensitive fields (mutate event payload/anchors safely)
        payload_out, anchors_out = pseudonymize_payload_and_anchors(
            event.payload.copy(),
            salt=self.pseudonym_salt,
        )

        merged_anchors = dict(event.anchors or {})
        merged_anchors.update(anchors_out or {})

        # 3.1) SANITIZE anchors (fixes person_h:person_h:demo1, phone_h:phone_h:..., etc.)
        merged_anchors = sanitize_anchors(merged_anchors)

        event.payload = payload_out
        event.anchors = merged_anchors

        # 4) Classification resolution
        classification = (event.classification or source.classification_level).upper()

        # 5) Signature verification (optional)
        signature_valid = False
        if signature_hex and signing_secret:
            canonical_obj = build_hash_canonical_object(event, source_id=source.source_id)
            msg = stable_json_dumps(canonical_obj).encode("utf-8")
            signature_valid = hmac_verify(signing_secret, msg, signature_hex)

        if enforce_signature and not signature_valid:
            raise PermissionError("Invalid event signature")

        # 6) Deterministic event hash (includes source_id, uses SANITIZED anchors)
        canonical_for_hash = build_hash_canonical_object(event, source_id=source.source_id)
        event_hash = compute_event_hash(canonical_for_hash)

        # 7) Append-only ledger write (SOURCE OF TRUTH)
        event_hash, status = self.ledger.insert_event_append_only(
            event_hash=event_hash,
            event_type=event.event_type,
            source_id=source.source_id,
            classification=classification,
            occurred_at=event.occurred_at,
            schema_version=event.schema_version,
            signature_valid=signature_valid,
            anchors=event.anchors,
            payload=event.payload,
        )
        # ------------------------------
        # DEV MODE: synchronous campaigns
        # ------------------------------
        from app.campaign.engine import CampaignEngine
        from app.campaign.detectors import build_signals_from_event

        if status == "accepted":
            signals = build_signals_from_event(
                event_hash=event_hash,
                event_doc={
                    "event_type": event.event_type,
                    "anchors": event.anchors,
                    "payload": event.payload,
                },
            )

            CampaignEngine(self.db).apply_signals(
                event_hash=event_hash,
                occurred_at=event.occurred_at,
                signals=signals,
            )


        # 8) Audit (always)
        self.ledger.audit(
            actor_type="source",
            actor_id=source.source_id,
            action=f"ingest.{status}",
            target=event_hash,
        )

        # Everything below is best-effort and runs ONLY on "accepted"
        if status == "accepted":
            # 9) OpenSearch indexing (best-effort)
            try:
                os_client = get_client()
                index_name = ensure_events_index(os_client)

                doc = to_index_doc(
                    event_hash=event_hash,
                    event_type=event.event_type,
                    source_id=source.source_id,
                    source_type=source.source_type,
                    classification=classification,
                    schema_version=event.schema_version,
                    signature_valid=signature_valid,
                    occurred_at=event.occurred_at,
                    received_at=received_at,
                    anchors=event.anchors,
                    payload=event.payload,
                )
                index_event(os_client, index_name, doc)
            except Exception:
                pass

            # 10) Graph delta generation + Postgres logging (best-effort)
            nodes_payload = []
            edges_payload = []
            try:
                delta = project_event_to_delta(event=event, event_hash=event_hash)
                nodes_payload = [n.__dict__ for n in delta.nodes]
                edges_payload = [e.__dict__ for e in delta.edges]

                self.graph_repo.insert_delta(
                    event_hash=event_hash,
                    nodes=nodes_payload,
                    edges=edges_payload,
                )
            except Exception:
                nodes_payload = []
                edges_payload = []

            # 11) Kafka publish to Redpanda (best-effort)
            try:
                if settings.kafka_enabled:
                    event_doc = {
                        "event_type": event.event_type,
                        "occurred_at": event.occurred_at.isoformat(),
                        "received_at": received_at.isoformat(),
                        "confidence": event.confidence,
                        "schema_version": event.schema_version,
                        "anchors": event.anchors,  # sanitized
                        "payload": event.payload,
                        "classification": classification,
                        "signature_valid": signature_valid,
                    }

                    msg = build_event_message(
                        event_hash=event_hash,
                        source={
                            "source_id": source.source_id,
                            "source_type": source.source_type,
                            "classification": classification,
                        },
                        event=event_doc,
                    )
                    get_producer.publish(
                        topic=settings.kafka_events_topic,
                        key=event_hash,
                        value=msg,
                    )

                    gmsg = build_graph_delta_message(
                        event_hash=event_hash,
                        nodes=nodes_payload,
                        edges=edges_payload,
                    )
                    get_producer.publish(
                        topic=settings.kafka_graph_topic,
                        key=event_hash,
                        value=gmsg,
                    )
            except Exception:
                pass

        return IngestResult(
            event_hash=event_hash,
            status=status,
            accepted_at=received_at.isoformat(),
            source_id=source.source_id,
            source_type=source.source_type,
            classification=classification,
            signature_valid=signature_valid,
        )
