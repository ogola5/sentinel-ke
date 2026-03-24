from __future__ import annotations

import json
import os
import sys
import types
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

config_stub = types.ModuleType("app.config")
config_stub.settings = SimpleNamespace(
    partner_id="cbk-ke",
    national_salt="national-demo-salt",
    hash_index_path="/tmp/hash-index.json",
    warning_cache_path="/tmp/warning-cache.json",
    hash_index_retention_days=14,
)
sys.modules["app.config"] = config_stub

from app.warning_resolver import (  # noqa: E402
    load_warning_cache,
    record_warning_ack,
    sync_warning_cache,
    update_hash_index,
)


def test_hash_index_updates_and_warning_resolves(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.warning_resolver.settings",
        SimpleNamespace(
            partner_id="cbk-ke",
            national_salt="national-demo-salt",
            hash_index_path=str(tmp_path / "hash-index.json"),
            warning_cache_path=str(tmp_path / "warning-cache.json"),
            hash_index_retention_days=14,
        ),
    )

    results = [
        SimpleNamespace(
            entity_key="phone_h:+254700000001",
            entity_type="phone_h",
            risk_score=0.91,
            uncertainty=0.09,
            fraud_family="SIM_SWAP",
            chain_score=0.84,
            risk_flags=["CAMPAIGN_ENTITY"],
        )
    ]
    summary = update_hash_index(results)
    assert summary["updated"] == 1
    assert summary["entry_count"] == 1

    warning_cache = sync_warning_cache(
        [
            {
                "id": "warn-1",
                "entity_key_hash": next(iter(json.loads((tmp_path / "hash-index.json").read_text())["entries"].keys())),
                "status": "open",
                "title": "Cross-agency SIM swap warning",
            }
        ]
    )
    assert warning_cache["warning_count"] == 1
    resolved = warning_cache["warnings"][0]
    assert resolved["locally_resolved"] is True
    assert resolved["local_match_count"] == 1
    assert resolved["local_matches"][0]["entity_key"] == "phone_h:+254700000001"


def test_warning_ack_is_recorded_locally(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.warning_resolver.settings",
        SimpleNamespace(
            partner_id="cbk-ke",
            national_salt="national-demo-salt",
            hash_index_path=str(tmp_path / "hash-index.json"),
            warning_cache_path=str(tmp_path / "warning-cache.json"),
            hash_index_retention_days=14,
        ),
    )
    sync_warning_cache(
        [
            {
                "id": "warn-2",
                "entity_key_hash": "abc123",
                "status": "open",
                "title": "Warning",
            }
        ]
    )

    record_warning_ack("warn-2", status="received", detail={"ticket": "CBK-88"}, acknowledged_at="2026-03-24T12:00:00+00:00")
    payload = load_warning_cache()

    assert payload["warnings"][0]["partner_ack_status"] == "received"
    assert payload["warnings"][0]["partner_ack_detail"] == {"ticket": "CBK-88"}
    assert payload["warnings"][0]["partner_acknowledged_at"] == "2026-03-24T12:00:00+00:00"
