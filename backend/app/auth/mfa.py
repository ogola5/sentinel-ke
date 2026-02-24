from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote


def generate_totp_secret(byte_len: int = 20) -> str:
    raw = secrets.token_bytes(byte_len)
    return base64.b32encode(raw).decode("ascii").replace("=", "")


def _decode_secret(secret: str) -> bytes:
    s = (secret or "").strip().replace(" ", "").upper()
    if not s:
        raise ValueError("mfa_secret_missing")
    pad = "=" * ((8 - (len(s) % 8)) % 8)
    try:
        return base64.b32decode(s + pad, casefold=True)
    except Exception as exc:
        raise ValueError("mfa_secret_invalid") from exc


def _totp_counter(ts: int, step: int) -> int:
    return int(ts // step)


def totp_code(
    secret: str,
    *,
    at_ts: Optional[int] = None,
    step: int = 30,
    digits: int = 6,
) -> str:
    key = _decode_secret(secret)
    ts = int(time.time() if at_ts is None else at_ts)
    counter = _totp_counter(ts, step)
    counter_bytes = struct.pack(">Q", counter)
    mac = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    binary = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    code = binary % (10**digits)
    return str(code).zfill(digits)


def verify_totp(
    secret: str,
    code: str,
    *,
    at_ts: Optional[int] = None,
    window: int = 1,
    step: int = 30,
    digits: int = 6,
) -> bool:
    candidate = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(candidate) != digits:
        return False

    base_ts = int(time.time() if at_ts is None else at_ts)
    for drift in range(-window, window + 1):
        ts = base_ts + drift * step
        expected = totp_code(secret, at_ts=ts, step=step, digits=digits)
        if hmac.compare_digest(expected, candidate):
            return True
    return False


def build_provisioning_uri(*, issuer: str, username: str, secret: str) -> str:
    label = quote(f"{issuer}:{username}")
    issuer_q = quote(issuer)
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer_q}&algorithm=SHA1&digits=6&period=30"
