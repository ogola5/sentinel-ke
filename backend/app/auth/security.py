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


TOKEN_VERSION_V1 = "v1"   # HMAC-SHA3-512 only (backward compat)
TOKEN_VERSION_V2 = "v2"   # HMAC-SHA3-512 + ML-DSA-65 (PQC hybrid)
TOKEN_VERSION = TOKEN_VERSION_V1  # default; overridden by pqc_mode at runtime
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


def _active_token_version() -> str:
    """Return v2 when ML-DSA-65 is available AND hybrid/pqc-only mode is set."""
    try:
        from app.core.pqc import _DILITHIUM_AVAILABLE, pqc_mode_from_settings  # noqa: PLC0415
        if _DILITHIUM_AVAILABLE and pqc_mode_from_settings() in ("hybrid", "pqc-only"):
            return TOKEN_VERSION_V2
    except Exception:  # noqa: BLE001
        pass
    return TOKEN_VERSION_V1


def build_signed_token(payload: Dict[str, Any], secret: str) -> str:
    """
    Build a signed token.
    v1: HMAC-SHA3-512 only.
    v2: HMAC-SHA3-512 (classical) + ML-DSA-65 (PQC) — active when CRYPTO_PQC_MODE=hybrid.
    """
    if not secret:
        raise ValueError("auth_token_secret_missing")

    version = _active_token_version()
    body = _b64url_encode(stable_json_dumps(payload).encode("utf-8"))
    hmac_sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha3_512).digest()
    base = f"{version}.{body}.{_b64url_encode(hmac_sig)}"

    if version == TOKEN_VERSION_V2:
        try:
            from app.core.pqc import build_pqc_token_segment  # noqa: PLC0415
            dil_seg = build_pqc_token_segment(body, master_secret=secret.encode("utf-8"))
            if dil_seg:
                return f"{base}.{dil_seg}"
        except Exception:  # noqa: BLE001
            pass  # Dilithium unavailable — emit v1-compatible 3-segment token

    return base


def parse_signed_token(token: str, secret: str) -> Dict[str, Any]:
    """
    Verify and parse a signed token.
    Accepts both v1 (3 segments) and v2 (4 segments) tokens.
    Always verifies HMAC-SHA3-512. When v2 + hybrid mode, also verifies ML-DSA-65.
    """
    if not token:
        raise ValueError("token_missing")

    parts = token.split(".")
    if len(parts) not in (3, 4):
        raise ValueError("token_format_invalid")

    version, body, hmac_sig_b64 = parts[0], parts[1], parts[2]
    dil_sig_b64 = parts[3] if len(parts) == 4 else None

    if version not in (TOKEN_VERSION_V1, TOKEN_VERSION_V2):
        raise ValueError("token_version_unsupported")
    if not secret:
        raise ValueError("auth_token_secret_missing")

    # Always verify classical HMAC-SHA3-512
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha3_512).digest()
    try:
        provided = _b64url_decode(hmac_sig_b64)
    except Exception as exc:
        raise ValueError("token_signature_invalid") from exc
    if not hmac.compare_digest(expected, provided):
        raise ValueError("token_signature_invalid")

    # If v2 + Dilithium segment present, verify ML-DSA-65 (non-blocking: warn, don't reject)
    if version == TOKEN_VERSION_V2 and dil_sig_b64:
        try:
            from app.core.pqc import verify_pqc_token_segment  # noqa: PLC0415
            if not verify_pqc_token_segment(body, dil_sig_b64, master_secret=secret.encode("utf-8")):
                import logging  # noqa: PLC0415
                logging.getLogger("sentinel.auth").warning("token_pqc_sig_invalid jti=unknown — HMAC valid; treating as v1")
        except Exception:  # noqa: BLE001
            pass  # PQC library unavailable — fall through on HMAC alone

    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception as exc:
        raise ValueError("token_payload_invalid") from exc
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


def encrypt_mfa_secret(secret: str, *, master_secret: str) -> str:
    """
    Encrypt a TOTP secret for storage.

    Uses the PQC module which selects the appropriate scheme based on
    CRYPTO_PQC_MODE:
      hybrid / pqc-only → ML-KEM-768 + AES-256-GCM  (kyber768_hybrid_v1)
      off / classical    → AES-256-GCM only           (aes256gcm_v1)

    The returned bundle is prefixed with its scheme identifier, enabling
    forward-compatible decryption as the scheme evolves.
    """
    if not (master_secret or "").strip():
        raise ValueError("auth_mfa_secret_key_missing")
    from app.core.pqc import encrypt_secret, pqc_mode_from_settings  # noqa: PLC0415
    return encrypt_secret(secret, master_secret=master_secret, mode=pqc_mode_from_settings())


def decrypt_mfa_secret(bundle: str, *, master_secret: str) -> str:
    """
    Decrypt a TOTP secret bundle produced by encrypt_mfa_secret().

    Handles all three known schemes transparently:
      kyber768_hybrid_v1 — ML-KEM-768 + AES-256-GCM  (current PQC hybrid)
      aes256gcm_v1       — AES-256-GCM only           (classical)
      legacy (no prefix) — custom XOR cipher           (pre-PQC; backward compat)
    """
    if not (master_secret or "").strip():
        raise ValueError("auth_mfa_secret_key_missing")
    from app.core.pqc import decrypt_secret  # noqa: PLC0415
    try:
        return decrypt_secret(bundle, master_secret=master_secret)
    except ValueError as exc:
        raise ValueError("mfa_secret_invalid") from exc
