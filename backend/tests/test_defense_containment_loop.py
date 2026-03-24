from __future__ import annotations

from app.defense.service import _write_containment_event
from app.ledger.models import EventEntityIndex, EventLog, SourceRegistry


class _FakeQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *args, **kwargs):  # noqa: ANN002, ARG002
        return self

    def first(self):
        return self.db.source_row


class _FakeDB:
    def __init__(self):
        self.source_row = None
        self.events = {}
        self.added = []

    def query(self, model):  # noqa: ANN001, ARG002
        return _FakeQuery(self)

    def get(self, model, pk):  # noqa: ANN001
        return self.events.get(pk)

    def add(self, obj):  # noqa: ANN001
        self.added.append(obj)
        if isinstance(obj, SourceRegistry):
            self.source_row = obj
        if isinstance(obj, EventLog):
            self.events[obj.event_hash] = obj

    def flush(self):
        return None


def test_write_containment_event_is_idempotent_and_indexes_ip():
    db = _FakeDB()

    _write_containment_event(
        db,
        action_type="block_ip",
        target="41.90.0.10",
        section_code="telecom",
        run_id="run-1",
        executed_by="analyst-1",
    )
    _write_containment_event(
        db,
        action_type="block_ip",
        target="41.90.0.10",
        section_code="telecom",
        run_id="run-1",
        executed_by="analyst-1",
    )

    sources = [obj for obj in db.added if isinstance(obj, SourceRegistry)]
    events = [obj for obj in db.added if isinstance(obj, EventLog)]
    entities = [obj for obj in db.added if isinstance(obj, EventEntityIndex)]

    assert len(sources) == 1
    assert len(events) == 1
    assert len(entities) == 1
    assert events[0].event_type == "CONTAINMENT_APPLIED"
    assert events[0].payload_json["action_type"] == "block_ip"
    assert entities[0].entity_key == "ip:41.90.0.10"
