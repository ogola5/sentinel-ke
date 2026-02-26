"""
GET /v1/crypto/posture  — live cryptographic posture report

Public endpoint (no auth required). Returns:
  - Active PQC mode and algorithm identifiers
  - NIST standard references (FIPS 203 / 204 / 197 / 198-1)
  - Library availability (kyber-py, dilithium-py, cryptography)
  - Current token format (v1 HMAC-only vs v2 HMAC+ML-DSA-65)
  - MFA encryption scheme (aes256gcm_v1 vs kyber768_hybrid_v1)
  - Public keys for external signature verification (ML-KEM-768 EK, ML-DSA-65 PK)
  - NIST compliance checklist

GET /v1/crypto/posture/self-test  — runs a live encrypt/decrypt round-trip
  for each available algorithm and reports timing (requires section access).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import require_section_access
from app.core.config import settings

router = APIRouter(prefix="/v1/crypto", tags=["crypto-posture"])


@router.get(
    "/posture",
    summary="Cryptographic posture report",
    description=(
        "Returns the current post-quantum cryptographic configuration, "
        "NIST compliance status, and public keys for external verification. "
        "No authentication required."
    ),
)
def get_posture() -> JSONResponse:
    from app.core.pqc import get_pqc_posture  # noqa: PLC0415

    master: bytes | None = None
    try:
        if settings.auth_mfa_secret_key:
            master = settings.auth_mfa_secret_key.encode("utf-8")
    except Exception:  # noqa: BLE001
        pass

    posture = get_pqc_posture(master_secret=master)
    return JSONResponse(content=posture)


@router.get(
    "/posture/self-test",
    summary="PQC self-test with timing",
    description=(
        "Runs a live encrypt/sign/verify round-trip for each available "
        "PQC algorithm. Requires section-level access."
    ),
    dependencies=[Depends(require_section_access)],
)
def run_self_test() -> dict:
    from app.core.pqc import (  # noqa: PLC0415
        _CRYPTO_AVAILABLE,
        _DILITHIUM_AVAILABLE,
        _KYBER_AVAILABLE,
        _aes_gcm_decrypt,
        _aes_gcm_encrypt,
        _hkdf_derive,
        dilithium_sign,
        dilithium_verify,
        encrypt_secret,
        decrypt_secret,
        pqc_mode_from_settings,
    )

    mode = pqc_mode_from_settings()
    results: dict = {"mode": mode, "tests": {}}

    master = b"sentinel-ke-self-test-master-secret-32b"

    # --- AES-256-GCM round-trip ---
    if _CRYPTO_AVAILABLE:
        t0 = time.perf_counter()
        key = _hkdf_derive(master, info=b"test")
        ct = _aes_gcm_encrypt(b"sentinel-ke-test-plaintext", key)
        pt = _aes_gcm_decrypt(ct, key)
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        results["tests"]["AES-256-GCM"] = {
            "pass": pt == b"sentinel-ke-test-plaintext",
            "ciphertext_bytes": len(ct),
            "elapsed_ms": elapsed,
            "standard": "FIPS 197",
        }

    # --- ML-KEM-768 (Kyber) hybrid round-trip ---
    if _KYBER_AVAILABLE and _CRYPTO_AVAILABLE:
        t0 = time.perf_counter()
        bundle = encrypt_secret("totp-secret-demo", master_secret=master.decode(), mode="hybrid")
        recovered = decrypt_secret(bundle, master_secret=master.decode())
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        results["tests"]["ML-KEM-768-hybrid"] = {
            "pass": recovered == "totp-secret-demo",
            "scheme": bundle.split(".")[0],
            "bundle_bytes": len(bundle),
            "elapsed_ms": elapsed,
            "standard": "FIPS 203",
        }

    # --- ML-DSA-65 (Dilithium) sign/verify ---
    if _DILITHIUM_AVAILABLE:
        msg = b"sentinel-ke-token-body-self-test"
        t0 = time.perf_counter()
        sig = dilithium_sign(msg, master_secret=master)
        valid = dilithium_verify(msg, sig, master_secret=master)
        tamper_valid = dilithium_verify(b"tampered", sig, master_secret=master)
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        results["tests"]["ML-DSA-65"] = {
            "pass": valid and not tamper_valid,
            "signature_bytes": len(sig),
            "verify_valid_msg": valid,
            "verify_tampered_msg": tamper_valid,
            "elapsed_ms": elapsed,
            "standard": "FIPS 204",
        }

    all_passed = all(t.get("pass", False) for t in results["tests"].values())
    results["overall"] = "PASS" if all_passed else "FAIL"
    return results
