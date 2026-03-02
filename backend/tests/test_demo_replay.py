from datetime import datetime, timezone

from app.demo import replay


def test_percentile_handles_empty_and_values():
    assert replay._percentile([], 95) is None
    vals = [10.0, 20.0, 30.0, 40.0]
    assert replay._percentile(vals, 50) == 30.0
    assert replay._percentile(vals, 95) == 40.0


def test_to_canonical_event_maps_row_fields():
    row = {
        "event_type": "DDOS_SIGNAL_EVENT",
        "occurred_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        "classification": "RESTRICTED",
        "schema_version": "v1",
        "anchors_json": {"service_id": "svc-a"},
        "payload_json": {"service_id": "svc-a", "request_rate": 1234},
    }
    out = replay._to_canonical_event(row, shift_to_now=False)
    assert out["event_type"] == "DDOS_SIGNAL_EVENT"
    assert out["classification"] == "RESTRICTED"
    assert out["anchors"]["service_id"] == "svc-a"
    assert out["payload"]["request_rate"] == 1234


def test_replay_events_aggregates_stats(monkeypatch):
    rows = [
        {"event_type": "DDOS_SIGNAL_EVENT", "anchors_json": {}, "payload_json": {}},
        {"event_type": "WEB_ATTACK_EVENT", "anchors_json": {}, "payload_json": {}},
        {"event_type": "SIM_SWAP_EVENT", "anchors_json": {}, "payload_json": {}},
    ]

    outcomes = iter(
        [
            (True, 200, 21.0, None),
            (False, 429, 35.0, None),
            (False, 0, 41.0, "timeout"),
        ]
    )

    def _fake_post_event(**kwargs):  # noqa: ANN003
        del kwargs
        return next(outcomes)

    monkeypatch.setattr(replay, "_post_event", _fake_post_event)
    stats = replay.replay_events(
        rows=rows,
        base_url="http://localhost:8000",
        api_key="k",
        concurrency=2,
        rate_per_sec=0.0,
        timeout_sec=5,
    )

    assert stats.total_events == 3
    assert stats.sent == 3
    assert stats.accepted_2xx == 1
    assert stats.rejected_non_2xx == 1
    assert stats.failures == 1
    assert stats.latency_p95_ms is not None
