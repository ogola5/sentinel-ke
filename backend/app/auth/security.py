from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.security import stable_json_dumps


TOKEN_VERSION = "v1"
SIGNING_ALG = "HMAC-SHA3-512"
PASSWORD_KDF = "PBKDF2-HMAC-SHA3-512"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - (len(value) % 4)) % 4)
    return base64.urlsafe_b64decode(value + padding)


def generate_salt(byte_len: int = 18) -> str:
    return _b64url_encode(secrets.token_bytes(byte_len))


def hash_password(
    password: str,
    salt: str,
    *,
    pepper: str = "",
    iterations: int = 450_000,
    dklen: int = 64,
) -> str:
    material = f"{password}{pepper}".encode("utf-8")
    key = hashlib.pbkdf2_hmac(
        "sha3_512",
        material,
        salt.encode("utf-8"),
        iterations,
        dklen=dklen,
    )
    digest = _b64url_encode(key)
    return f"pbkdf2_sha3_512${iterations}${dklen}${digest}"


def validate_password_strength(password: str, *, min_length: int = 12) -> None:
    if len(password or "") < min_length:
        raise ValueError("weak_password_length")
    has_upper = any(ch.isupper() for ch in password)
    has_lower = any(ch.islower() for ch in password)
    has_digit = any(ch.isdigit() for ch in password)
    has_symbol = any(not ch.isalnum() for ch in password)
    if not (has_upper and has_lower and has_digit and has_symbol):
        raise ValueError("weak_password_complexity")


def verify_password(password: str, salt: str, stored_hash: str, *, pepper: str = "") -> bool:
    try:
        algo, iterations_s, dklen_s, _digest = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha3_512":
            return False
        computed = hash_password(
            password,
            salt,
            pepper=pepper,
            iterations=int(iterations_s),
            dklen=int(dklen_s),
        )
        return hmac.compare_digest(computed, stored_hash)
    except Exception:
        return False


def hash_refresh_token(refresh_token: str) -> str:
    return hashlib.sha3_512(refresh_token.encode("utf-8")).hexdigest()


def new_token_id() -> str:
    return uuid.uuid4().hex


def build_signed_token(payload: Dict[str, Any], secret: str) -> str:
    if not secret:
        raise ValueError("auth_token_secret_missing")
    body = _b64url_encode(stable_json_dumps(payload).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha3_512).digest()
    return f"{TOKEN_VERSION}.{body}.{_b64url_encode(sig)}"


def parse_signed_token(token: str, secret: str) -> Dict[str, Any]:
    if not token:
        raise ValueError("token_missing")
    try:
        version, body, signature = token.split(".", 2)
    except ValueError:
        raise ValueError("token_format_invalid")
    if version != TOKEN_VERSION:
        raise ValueError("token_version_unsupported")
    if not secret:
        raise ValueError("auth_token_secret_missing")
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha3_512).digest()
    try:
        provided = _b64url_decode(signature)
    except Exception:
        raise ValueError("token_signature_invalid")
    if not hmac.compare_digest(expected, provided):
        raise ValueError("token_signature_invalid")
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        raise ValueError("token_payload_invalid")
    if not isinstance(payload, dict):
        raise ValueError("token_payload_invalid")
    return payload


def verify_token_claims(
    payload: Dict[str, Any],
    *,
    expected_type: str,
    issuer: str,
    audience: str,
    now_dt: Optional[datetime] = None,
) -> None:
    now_ts = int((now_dt or utcnow()).timestamp())

    token_type = str(payload.get("typ") or "")
    if token_type != expected_type:
        raise ValueError("token_type_mismatch")

    if str(payload.get("iss") or "") != issuer:
        raise ValueError("token_issuer_invalid")
    if str(payload.get("aud") or "") != audience:
        raise ValueError("token_audience_invalid")

    exp = int(payload.get("exp") or 0)
    iat = int(payload.get("iat") or 0)
    nbf = int(payload.get("nbf") or iat)
    if exp <= now_ts:
        raise ValueError("token_expired")
    if nbf > now_ts:
        raise ValueError("token_not_yet_valid")


def fingerprint_digest(value: Optional[str]) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    return hashlib.sha3_256(v.encode("utf-8")).hexdigest()


def _derive_master_key(master_secret: str) -> bytes:
    seed = (master_secret or "").strip()
    if not seed:
        raise ValueError("auth_mfa_secret_key_missing")
    return hashlib.sha3_512(seed.encode("utf-8")).digest()


def _stream_xor(data: bytes, *, key: bytes, nonce: bytes) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hashlib.sha3_512(key + nonce + counter.to_bytes(4, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(a ^ b for a, b in zip(data, out[: len(data)]))


def encrypt_mfa_secret(secret: str, *, master_secret: str) -> str:
    key = _derive_master_key(master_secret)
    nonce = secrets.token_bytes(16)
    plaintext = secret.encode("utf-8")
    ciphertext = _stream_xor(plaintext, key=key, nonce=nonce)
    tag = hmac.new(key, nonce + ciphertext, hashlib.sha3_256).digest()
    token = nonce + ciphertext + tag
    return base64.urlsafe_b64encode(token).decode("ascii")


def decrypt_mfa_secret(token: str, *, master_secret: str) -> str:
    key = _derive_master_key(master_secret)
    try:
        blob = base64.urlsafe_b64decode(token.encode("ascii"))
    except Exception as exc:
        raise ValueError("mfa_secret_invalid") from exc
    if len(blob) < 16 + 32:
        raise ValueError("mfa_secret_invalid")
    nonce = blob[:16]
    tag = blob[-32:]
    ciphertext = blob[16:-32]
    expected = hmac.new(key, nonce + ciphertext, hashlib.sha3_256).digest()
    if not hmac.compare_digest(expected, tag):
        raise ValueError("mfa_secret_invalid")
    plaintext = _stream_xor(ciphertext, key=key, nonce=nonce)
    return plaintext.decode("utf-8")
