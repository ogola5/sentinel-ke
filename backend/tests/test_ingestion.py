from __future__ import annotations

from datetime import datetime, timezone

from app.ingestion.schemas import CanonicalEvent
from app.ingestion.service import IngestionService


class _DummySource:
    source_id = "safaricom"
    source_type = "telco"
    section_code = "telecom"
    classification_level = "RESTRICTED"


class _DummyLedger:
    def get_source_by_api_key(self, source_api_key: str):
        del source_api_key
        return _DummySource()

    def ensure_source_active(self, source) -> None:
        del source

    def insert_event_append_only(self, **kwargs):
        del kwargs
        return "event-hash-1", "accepted"

    def audit(self, **kwargs) -> None:
        del kwargs


class _DummyGraphRepo:
    def insert_delta(self, **kwargs) -> None:
        del kwargs


class _DummyCampaignEngine:
    def __init__(self, db):
        self.db = db

    def apply_signals(self, **kwargs) -> None:
        del kwargs


class _DummyProducer:
    def __init__(self, sink: list[dict]):
        self._sink = sink

    def publish(self, *, topic: str, key: str, value):
        self._sink.append({"topic": topic, "key": key, "value": value})


def _build_event() -> CanonicalEvent:
    return CanonicalEvent(
        event_type="DDOS_SIGNAL_EVENT",
        occurred_at=datetime.now(timezone.utc),
        payload={"service_id": "safaricom-mpesa", "req_rate": 1200.0},
        anchors={"service_id": "safaricom-mpesa"},
    )


def _prepare_service(monkeypatch, published_sink: list[dict] | None) -> IngestionService:
    service = IngestionService(db=object())
    service.ledger = _DummyLedger()
    service.graph_repo = _DummyGraphRepo()

    monkeypatch.setattr("app.campaign.engine.CampaignEngine", _DummyCampaignEngine)
    monkeypatch.setattr("app.campaign.detectors.build_signals_from_event", lambda **kwargs: [])
    monkeypatch.setattr("app.ingestion.service.normalize_event", lambda event: event)
    monkeypatch.setattr("app.ingestion.service.validate_event", lambda event: None)
    monkeypatch.setattr(
        "app.ingestion.service.pseudonymize_payload_and_anchors",
        lambda payload, salt=None: (payload, {}),
    )
    monkeypatch.setattr(
        "app.ingestion.service.project_event_to_delta",
        lambda event, event_hash: type("Delta", (), {"nodes": [], "edges": []})(),
    )
    monkeypatch.setattr("app.ingestion.service.get_client", lambda: (_ for _ in ()).throw(RuntimeError("no-os")))
    monkeypatch.setattr("app.ingestion.service.index_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.ingestion.service.ensure_events_index", lambda *args, **kwargs: "idx")
    monkeypatch.setattr("app.ingestion.service.build_event_message", lambda **kwargs: {"kind": "event"})
    monkeypatch.setattr("app.ingestion.service.build_graph_delta_message", lambda **kwargs: {"kind": "graph"})
    monkeypatch.setattr("app.ingestion.service.settings.kafka_enabled", True)
    monkeypatch.setattr("app.ingestion.service.settings.kafka_events_topic", "sentinel.events.v1")
    monkeypatch.setattr("app.ingestion.service.settings.kafka_graph_topic", "sentinel.graph.delta.v1")

    if published_sink is None:
        monkeypatch.setattr("app.ingestion.service.get_producer", lambda: None)
    else:
        monkeypatch.setattr(
            "app.ingestion.service.get_producer",
            lambda: _DummyProducer(published_sink),
        )
    return service


def test_ingest_event_publishes_to_event_and_graph_topics(monkeypatch):
    published: list[dict] = []
    service = _prepare_service(monkeypatch, published)

    out = service.ingest_event(
        event=_build_event(),
        source_api_key="safaricom-secret-key",
    )

    assert out.status == "accepted"
    assert [row["topic"] for row in published] == [
        "sentinel.events.v1",
        "sentinel.graph.delta.v1",
    ]


def test_ingest_event_succeeds_when_kafka_producer_unavailable(monkeypatch):
    service = _prepare_service(monkeypatch, None)
    out = service.ingest_event(
        event=_build_event(),
        source_api_key="safaricom-secret-key",
    )
    assert out.status == "accepted"
