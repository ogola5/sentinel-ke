from __future__ import annotations

from app.core.http_hardening import normalize_request_id


def test_normalize_request_id_keeps_valid_value():
    assert normalize_request_id("Abc_123-xyz") == "Abc_123-xyz"


def test_normalize_request_id_rejects_invalid_chars():
    rid = normalize_request_id("bad request id")
    assert rid != "bad request id"
    assert len(rid) == 32
