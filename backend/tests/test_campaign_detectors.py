from __future__ import annotations

from app.campaign.detectors import build_signals_from_event


def test_build_signals_from_dfir_ioc_event_creates_indicator_cluster():
    out = build_signals_from_event(
        event_hash="evt-1",
        event_doc={
            "event_type": "DFIR_FINDING_EVENT",
            "anchors": {
                "ip": "198.51.100.10",
                "domain": "bad.example",
                "url": "http://bad.example/dropper.exe",
            },
            "payload": {
                "finding_type": "botnet_c2_indicator",
            },
        },
    )

    assert any(sig.type == "IOC_INDICATOR_CLUSTER" for sig in out)
    sig = next(sig for sig in out if sig.type == "IOC_INDICATOR_CLUSTER")
    assert sig.primary_key == "ip:198.51.100.10"
    assert ("Domain", "domain:bad.example", "indicator") in sig.entities
