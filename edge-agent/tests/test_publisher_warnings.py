from __future__ import annotations

import os
import sys
import types
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

config_stub = types.ModuleType("app.config")
config_stub.settings = SimpleNamespace(
    hub_url="https://hub.example",
    hub_api_key="partner-key",
    national_salt="national-demo-salt",
    risk_threshold=0.6,
    partner_id="cbk-ke",
    model_version="edge-gnn-v1",
)
sys.modules["app.config"] = config_stub

from app import publisher  # noqa: E402


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_warning_inbox_uses_api_key_header(monkeypatch):
    captured = {}

    def _fake_get(url, params=None, headers=None, timeout=None):  # noqa: ANN001
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResponse({"warnings": [{"id": "w-1"}]})

    monkeypatch.setattr(
        publisher,
        "settings",
        SimpleNamespace(hub_url="https://hub.example", hub_api_key="partner-key"),
    )
    monkeypatch.setattr(publisher.httpx, "get", _fake_get)

    out = publisher.fetch_warning_inbox(status="open", limit=20, timeout_s=7)

    assert out["warnings"] == [{"id": "w-1"}]
    assert captured["url"] == "https://hub.example/v1/federation/warnings/inbox"
    assert captured["params"] == {"status": "open", "limit": 20}
    assert captured["headers"] == {"X-API-Key": "partner-key"}
    assert captured["timeout"] == 7


def test_acknowledge_warning_posts_signed_body(monkeypatch):
    captured = {}

    def _fake_signed_post(path, payload, *, timeout_s):  # noqa: ANN001
        captured["path"] = path
        captured["payload"] = payload
        captured["timeout_s"] = timeout_s
        return {"accepted": True, "warning_id": "w-2", "status": payload["status"]}

    monkeypatch.setattr(publisher, "_signed_post", _fake_signed_post)

    out = publisher.acknowledge_warning("w-2", status="resolved", detail={"ticket": "CBK-12"}, timeout_s=11)

    assert out["status"] == "resolved"
    assert captured["path"] == "/v1/federation/warnings/w-2/ack"
    assert captured["payload"] == {"status": "resolved", "detail": {"ticket": "CBK-12"}}
    assert captured["timeout_s"] == 11
