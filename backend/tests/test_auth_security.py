from __future__ import annotations

import pytest

from app.auth.security import (
    build_signed_token,
    fingerprint_digest,
    generate_salt,
    hash_password,
    parse_signed_token,
    verify_password,
    verify_token_claims,
)


def test_password_hash_and_verify_roundtrip():
    salt = generate_salt()
    h = hash_password("StrongPass!2026", salt, pepper="pepper")
    assert verify_password("StrongPass!2026", salt, h, pepper="pepper")
    assert not verify_password("wrong", salt, h, pepper="pepper")


def test_signed_token_roundtrip_and_claims():
    payload = {
        "iss": "issuer-a",
        "aud": "api-a",
        "typ": "access",
        "sub": "u1",
        "sid": "s1",
        "jti": "j1",
        "iat": 1_700_000_000,
        "nbf": 1_700_000_000,
        "exp": 4_102_444_800,
    }
    token = build_signed_token(payload, "secret-123")
    decoded = parse_signed_token(token, "secret-123")
    assert decoded["sub"] == "u1"
    verify_token_claims(
        decoded,
        expected_type="access",
        issuer="issuer-a",
        audience="api-a",
    )


def test_signed_token_rejects_tampering():
    payload = {
        "iss": "issuer-a",
        "aud": "api-a",
        "typ": "access",
        "sub": "u1",
        "sid": "s1",
        "jti": "j1",
        "iat": 1_700_000_000,
        "nbf": 1_700_000_000,
        "exp": 4_102_444_800,
    }
    token = build_signed_token(payload, "secret-123")
    bad = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(ValueError) as e:
        parse_signed_token(bad, "secret-123")
    assert str(e.value) == "token_signature_invalid"


def test_fingerprint_digest_is_stable_and_optional():
    assert fingerprint_digest(None) == ""
    assert fingerprint_digest("") == ""
    assert fingerprint_digest("device-1") == fingerprint_digest("device-1")
