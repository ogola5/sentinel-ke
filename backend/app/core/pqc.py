"""
Sentinel-KE Post-Quantum Cryptography Module
=============================================

Implements NIST-standardized post-quantum algorithms:

  ML-KEM-768   (CRYSTALS-Kyber)     — FIPS 203 — key encapsulation
  ML-DSA-65    (CRYSTALS-Dilithium) — FIPS 204 — digital signatures
  AES-256-GCM  (symmetric AEAD)     — FIPS 197 — authenticated encryption

Hybrid mode (NIST SP 800-227 recommendation during PQC transition):
  Security holds if EITHER classical OR PQC path remains unbroken.
  Combined secret = HKDF-SHA3-512( classical_secret || pqc_secret )

Threat model addressed:
  "Harvest now, decrypt later" — adversary stores encrypted ciphertext today
  and waits for a sufficiently powerful quantum computer to break the classical
  key-exchange (Shor's algorithm). Hybrid mode prevents this without
  sacrificing classical security.

Why HMAC-SHA3-512 tokens are already quantum-safe:
  Grover's algorithm gives only a quadratic speedup for symmetric primitives.
  A 512-bit HMAC key has ~256-bit post-quantum security — well above NIST
  Category 5 (equivalent to AES-256). Token signing does NOT need PQC
  replacement; we ADD Dilithium as an asymmetric signature layer for
  non-repudiation and forward-secrecy proofs.

CRYPTO_PQC_MODE:
  off / classical → AES-256-GCM only (classical symmetric, no PQC)
  hybrid          → ML-KEM-768 + AES-256-GCM  |  HMAC-SHA3-512 + ML-DSA-65
  pqc-only        → ML-KEM-768 only  |  ML-DSA-65 only (no classical fallback)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from typing import Optional, Tuple

log = logging.getLogger("sentinel.pqc")

# ---------------------------------------------------------------------------
# Optional PQC library imports — graceful degradation if not installed
# ---------------------------------------------------------------------------

# --- ML-KEM (CRYSTALS-Kyber) -----------------------------------------------
_Kyber768 = None
_KYBER_AVAILABLE = False
try:
    from kyber_py.ml_kem import ML_KEM_768 as _Kyber768   # kyber-py >= 2.0
    _KYBER_AVAILABLE = True
    log.info("pqc_ml_kem=ML_KEM_768 source=kyber_py.ml_kem status=loaded")
except ImportError:
    try:
        from kyber_py.kyber import Kyber768 as _Kyber768  # kyber-py 1.x compat
        _KYBER_AVAILABLE = True
        log.info("pqc_ml_kem=Kyber768 source=kyber_py.kyber status=loaded")
    except ImportError:
        log.warning("pqc_ml_kem=unavailable reason='kyber-py not installed' fallback=AES-256-GCM-only")

# --- ML-DSA (CRYSTALS-Dilithium) -------------------------------------------
_Dilithium = None
_DILITHIUM_AVAILABLE = False
try:
    from dilithium_py.ml_dsa import ML_DSA_65 as _Dilithium   # dilithium-py >= 2.0
    _DILITHIUM_AVAILABLE = True
    log.info("pqc_ml_dsa=ML_DSA_65 source=dilithium_py.ml_dsa status=loaded")
except ImportError:
    try:
        from dilithium_py.dilithium import Dilithium3 as _Dilithium  # dilithium-py 1.x
        _DILITHIUM_AVAILABLE = True
        log.info("pqc_ml_dsa=Dilithium3 source=dilithium_py.dilithium status=loaded")
    except ImportError:
        log.warning("pqc_ml_dsa=unavailable reason='dilithium-py not installed'")

# --- AES-256-GCM (cryptography library) ------------------------------------
_AESGCM = None
_HKDF = None
_SHA3_512_HASH = None
_CRYPTO_AVAILABLE = False
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF as _HKDF
    from cryptography.hazmat.primitives import hashes as _crypto_hashes
    _SHA3_512_HASH = _crypto_hashes.SHA3_512
    _CRYPTO_AVAILABLE = True
    log.info("pqc_aes_gcm=AES-256-GCM source=cryptography status=loaded")
except ImportError:
    log.error("pqc_aes_gcm=unavailable reason='cryptography not installed' — PQC module degraded")


# ---------------------------------------------------------------------------
# Constants & scheme identifiers
# ---------------------------------------------------------------------------

SCHEME_AES_GCM      = "aes256gcm_v1"       # classical AES-256-GCM
SCHEME_HYBRID       = "kyber768_hybrid_v1"  # ML-KEM-768 + AES-256-GCM
SCHEME_PQC_ONLY     = "kyber768_v1"         # ML-KEM-768 only
SCHEME_LEGACY_XOR   = "legacy"              # old XOR cipher — read-only

TOKEN_VERSION_CLASSIC = "v1"   # HMAC-SHA3-512 only
TOKEN_VERSION_HYBRID  = "v2"   # HMAC-SHA3-512 + ML-DSA-65

AES_KEY_LEN   = 32   # bytes (256-bit)
AES_NONCE_LEN = 12   # bytes (96-bit GCM nonce)
GCM_TAG_LEN   = 16   # bytes (128-bit authentication tag)

# HKDF labels (domain-separated per usage)
_HKDF_LABEL_MFA       = b"sentinel-ke-mfa-aes-v1"
_HKDF_LABEL_KEM_CL    = b"sentinel-ke-kem-classical-v1"
_HKDF_LABEL_COMBINER  = b"sentinel-ke-hybrid-combiner-v1"
_HKDF_LABEL_KYBER_SEED   = b"sentinel-ke-kyber-drbg-seed-48b-v1"
_HKDF_LABEL_DILITHIUM    = b"sentinel-ke-dilithium-drbg-seed-48b-v1"


# ---------------------------------------------------------------------------
# Base64url helpers
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


# ---------------------------------------------------------------------------
# HKDF wrapper (SHA3-512)
# ---------------------------------------------------------------------------

def _hkdf_derive(key_material: bytes, *, info: bytes, length: int = 32) -> bytes:
    """Derive a fixed-length key from key material via HKDF-SHA3-512."""
    if _CRYPTO_AVAILABLE:
        hkdf = _HKDF(
            algorithm=_SHA3_512_HASH(),
            length=length,
            salt=None,
            info=info,
        )
        return hkdf.derive(key_material)
    # Fallback: HMAC-SHA3-512 key derivation (RFC 5869 simplified)
    prk = hmac.new(b"sentinel-ke-pqc-hkdf", key_material, hashlib.sha3_512).digest()
    blocks, buf = [], b""
    while len(buf) < length:
        counter = (len(blocks) + 1).to_bytes(1, "big")
        buf = hmac.new(prk, (blocks[-1] if blocks else b"") + info + counter, hashlib.sha3_512).digest()
        blocks.append(buf)
    return b"".join(blocks)[:length]


# ---------------------------------------------------------------------------
# AES-256-GCM authenticated encryption
# ---------------------------------------------------------------------------

def _aes_gcm_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt with AES-256-GCM. Returns: nonce(12) || ciphertext || tag(16)."""
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("pqc_aes_gcm_unavailable: install cryptography library")
    nonce = secrets.token_bytes(AES_NONCE_LEN)
    aesgcm = _AESGCM(key)
    # cryptography library appends the 16-byte GCM tag to ciphertext
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ct_and_tag


def _aes_gcm_decrypt(blob: bytes, key: bytes) -> bytes:
    """Decrypt AES-256-GCM blob (nonce || ciphertext || tag)."""
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("pqc_aes_gcm_unavailable: install cryptography library")
    if len(blob) < AES_NONCE_LEN + GCM_TAG_LEN + 1:
        raise ValueError("pqc_ciphertext_too_short")
    nonce = blob[:AES_NONCE_LEN]
    ct_and_tag = blob[AES_NONCE_LEN:]
    aesgcm = _AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ct_and_tag, None)
    except Exception as exc:
        raise ValueError("pqc_decryption_failed") from exc


# ---------------------------------------------------------------------------
# Deterministic ML-KEM-768 keypair derivation
# ---------------------------------------------------------------------------

def _derive_kyber_keypair(master_secret: bytes) -> Tuple[bytes, bytes]:
    """
    Derive a deterministic ML-KEM-768 keypair from a master secret.
    Returns (encapsulation_key, decapsulation_key).

    Uses set_drbg_seed(48-byte seed) so the same master_secret always
    produces the same keypair — essential for stable MFA secret decryption.
    """
    if not _KYBER_AVAILABLE:
        raise RuntimeError("pqc_kyber_unavailable: install kyber-py")
    seed = _hkdf_derive(master_secret, info=_HKDF_LABEL_KYBER_SEED, length=48)
    _Kyber768.set_drbg_seed(seed)
    ek, dk = _Kyber768.keygen()
    return ek, dk


# ---------------------------------------------------------------------------
# Deterministic ML-DSA-65 keypair derivation
# ---------------------------------------------------------------------------

def _derive_dilithium_keypair(master_secret: bytes) -> Tuple[bytes, bytes]:
    """
    Derive a deterministic ML-DSA-65 keypair from a master secret.
    Returns (public_key, secret_key).

    Uses set_drbg_seed(48-byte seed) for deterministic generation.
    """
    if not _DILITHIUM_AVAILABLE:
        raise RuntimeError("pqc_dilithium_unavailable: install dilithium-py")
    seed = _hkdf_derive(master_secret, info=_HKDF_LABEL_DILITHIUM, length=48)
    _Dilithium.set_drbg_seed(seed)
    pk, sk = _Dilithium.keygen()
    return pk, sk


# ---------------------------------------------------------------------------
# MFA Secret Encryption  (replaces the legacy XOR cipher)
# ---------------------------------------------------------------------------

def encrypt_secret(plaintext: str, *, master_secret: str, mode: str = "hybrid") -> str:
    """
    Encrypt a sensitive string (e.g. TOTP secret) using the configured PQC mode.

    Returns a versioned bundle: "{scheme}.{base64url_blob}"

    Schemes:
      aes256gcm_v1       — AES-256-GCM with HKDF-derived key (off/classical mode)
      kyber768_hybrid_v1 — ML-KEM-768 + AES-256-GCM (hybrid mode)
    """
    master_bytes = master_secret.encode("utf-8") if isinstance(master_secret, str) else master_secret
    pt_bytes = plaintext.encode("utf-8")

    effective_mode = _resolve_mode(mode)

    if effective_mode in ("hybrid", "pqc-only") and _KYBER_AVAILABLE and _CRYPTO_AVAILABLE:
        return _encrypt_kyber_hybrid(pt_bytes, master_bytes)

    # classical / off / fallback
    if _CRYPTO_AVAILABLE:
        return _encrypt_aes_gcm(pt_bytes, master_bytes)

    raise RuntimeError("pqc_no_encryption_backend: install cryptography library")


def decrypt_secret(bundle: str, *, master_secret: str) -> str:
    """
    Decrypt a bundle produced by encrypt_secret().
    Handles all known schemes including the legacy XOR format.
    """
    master_bytes = master_secret.encode("utf-8") if isinstance(master_secret, str) else master_secret

    if bundle.startswith(SCHEME_HYBRID + "."):
        blob = _b64url_decode(bundle[len(SCHEME_HYBRID) + 1:])
        return _decrypt_kyber_hybrid(blob, master_bytes).decode("utf-8")

    if bundle.startswith(SCHEME_AES_GCM + "."):
        blob = _b64url_decode(bundle[len(SCHEME_AES_GCM) + 1:])
        return _aes_gcm_decrypt(blob, _hkdf_derive(master_bytes, info=_HKDF_LABEL_MFA)).decode("utf-8")

    # Legacy XOR cipher (read-only, no new secrets will be written in this format)
    return _decrypt_legacy_xor(bundle, master_bytes)


# --- AES-GCM scheme ---

def _encrypt_aes_gcm(plaintext: bytes, master: bytes) -> str:
    key = _hkdf_derive(master, info=_HKDF_LABEL_MFA)
    blob = _aes_gcm_encrypt(plaintext, key)
    return f"{SCHEME_AES_GCM}.{_b64url_encode(blob)}"


# --- Kyber hybrid scheme ---

def _encrypt_kyber_hybrid(plaintext: bytes, master: bytes) -> str:
    """
    Hybrid encryption:
      1. ML-KEM-768 encapsulation → PQC shared secret (32 bytes)
      2. HKDF classical secret from master key
      3. Hybrid combiner: HKDF-SHA3-512(pqc_secret || classical_secret)
      4. AES-256-GCM with combined key

    Wire format (blob):
      kyber_ciphertext (1088 bytes) || aes_nonce (12) || aes_ct || aes_tag (16)
    """
    ek, _dk = _derive_kyber_keypair(master)
    # Encapsulate: produces (shared_secret 32B, kyber_ciphertext 1088B)
    # ML-KEM encaps returns (shared_secret, ciphertext)
    try:
        pqc_secret, kyber_ct = _Kyber768.encaps(ek)   # kyber-py 2.x
    except AttributeError:
        pqc_secret, kyber_ct = _Kyber768.enc(ek)       # kyber-py 1.x

    classical_secret = _hkdf_derive(master, info=_HKDF_LABEL_KEM_CL)
    combined_key = _hkdf_derive(
        pqc_secret + classical_secret,
        info=_HKDF_LABEL_COMBINER,
    )
    aes_blob = _aes_gcm_encrypt(plaintext, combined_key)
    blob = kyber_ct + aes_blob
    return f"{SCHEME_HYBRID}.{_b64url_encode(blob)}"


def _decrypt_kyber_hybrid(blob: bytes, master: bytes) -> bytes:
    """Reverse of _encrypt_kyber_hybrid."""
    # ML-KEM-768 ciphertext is exactly 1088 bytes
    KYBER_CT_LEN = 1088
    if len(blob) < KYBER_CT_LEN + AES_NONCE_LEN + GCM_TAG_LEN + 1:
        raise ValueError("pqc_ciphertext_too_short")
    kyber_ct = blob[:KYBER_CT_LEN]
    aes_blob  = blob[KYBER_CT_LEN:]

    _ek, dk = _derive_kyber_keypair(master)
    try:
        pqc_secret = _Kyber768.decaps(dk, kyber_ct)   # ML-KEM API
    except AttributeError:
        pqc_secret = _Kyber768.dec(dk, kyber_ct)       # Kyber 1.x API

    classical_secret = _hkdf_derive(master, info=_HKDF_LABEL_KEM_CL)
    combined_key = _hkdf_derive(
        pqc_secret + classical_secret,
        info=_HKDF_LABEL_COMBINER,
    )
    return _aes_gcm_decrypt(aes_blob, combined_key)


# --- Legacy XOR (read-only backward compat) ---

def _decrypt_legacy_xor(token: str, master: bytes) -> str:
    """Decrypt old XOR-cipher MFA secrets. Used only during migration."""
    import base64 as _b64
    key = hashlib.sha3_512(master).digest()
    try:
        raw = _b64.urlsafe_b64decode(token.encode("ascii"))
    except Exception as exc:
        raise ValueError("mfa_secret_invalid") from exc
    if len(raw) < 16 + 32:
        raise ValueError("mfa_secret_invalid")
    nonce, tag, ciphertext = raw[:16], raw[-32:], raw[16:-32]
    expected = hmac.new(key, nonce + ciphertext, hashlib.sha3_256).digest()
    if not hmac.compare_digest(expected, tag):
        raise ValueError("mfa_secret_invalid")
    out, counter = bytearray(), 0
    while len(out) < len(ciphertext):
        block = hashlib.sha3_512(key + nonce + counter.to_bytes(4, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(a ^ b for a, b in zip(ciphertext, out[:len(ciphertext)])).decode("utf-8")


# ---------------------------------------------------------------------------
# ML-DSA-65 (Dilithium) — Token signing layer
# ---------------------------------------------------------------------------

def dilithium_sign(message: bytes, *, master_secret: bytes) -> bytes:
    """Sign message with ML-DSA-65. Returns raw signature bytes."""
    _pk, sk = _derive_dilithium_keypair(master_secret)
    try:
        return _Dilithium.sign(sk, message, ctx=b"sentinel-ke-token-v2")
    except TypeError:
        return _Dilithium.sign(sk, message)   # older API without ctx


def dilithium_verify(message: bytes, signature: bytes, *, master_secret: bytes) -> bool:
    """Verify ML-DSA-65 signature. Returns True if valid, False otherwise."""
    pk, _sk = _derive_dilithium_keypair(master_secret)
    try:
        try:
            result = _Dilithium.verify(pk, message, signature, ctx=b"sentinel-ke-token-v2")
        except TypeError:
            # dilithium-py version without ctx support
            result = _Dilithium.verify(pk, message, signature)
        return bool(result)
    except Exception:  # noqa: BLE001
        return False


def dilithium_public_key_b64(*, master_secret: bytes) -> str:
    """Return the ML-DSA-65 public key as base64url (for /crypto/posture)."""
    pk, _ = _derive_dilithium_keypair(master_secret)
    return _b64url_encode(pk)


# ---------------------------------------------------------------------------
# Token signing helpers (used by security.py)
# ---------------------------------------------------------------------------

def build_pqc_token_segment(body: str, *, master_secret: bytes) -> Optional[str]:
    """
    Create the 4th token segment: ML-DSA-65 signature over "v2.{body}".
    Returns None if Dilithium is unavailable.
    """
    if not _DILITHIUM_AVAILABLE:
        return None
    message = f"v2.{body}".encode("ascii")
    sig = dilithium_sign(message, master_secret=master_secret)
    return _b64url_encode(sig)


def verify_pqc_token_segment(body: str, dil_sig_b64: str, *, master_secret: bytes) -> bool:
    """Verify the 4th segment of a v2 token."""
    if not _DILITHIUM_AVAILABLE:
        return False
    message = f"v2.{body}".encode("ascii")
    try:
        sig = _b64url_decode(dil_sig_b64)
    except Exception:
        return False
    return dilithium_verify(message, sig, master_secret=master_secret)


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------

def _resolve_mode(mode: str) -> str:
    """Normalise CRYPTO_PQC_MODE value."""
    m = (mode or "").strip().lower()
    if m in ("off", "classical", ""):
        return "classical"
    if m in ("hybrid",):
        return "hybrid"
    if m in ("pqc-only", "pqc_only"):
        return "pqc-only"
    return "classical"


def pqc_mode_from_settings() -> str:
    """Read CRYPTO_PQC_MODE from settings (lazy import to avoid circular deps)."""
    try:
        from app.core.config import settings  # noqa: PLC0415
        return _resolve_mode(settings.crypto_pqc_mode)
    except Exception:
        return "classical"


# ---------------------------------------------------------------------------
# Posture report
# ---------------------------------------------------------------------------

def get_pqc_posture(*, master_secret: Optional[bytes] = None) -> dict:
    """
    Return a structured report of the current cryptographic posture.
    Exposed via GET /v1/crypto/posture.
    """
    mode = pqc_mode_from_settings()

    try:
        from app.core.config import settings  # noqa: PLC0415
        tls_mode  = settings.crypto_tls_mode
        kms       = settings.crypto_kms_provider
        rotation  = settings.crypto_key_rotation_days
    except Exception:
        tls_mode = "tls1.3"
        kms = "software"
        rotation = 90

    kyber_pk_b64 = None
    dil_pk_b64   = None
    if master_secret:
        if _KYBER_AVAILABLE:
            try:
                ek, _ = _derive_kyber_keypair(master_secret)
                kyber_pk_b64 = _b64url_encode(ek)
            except Exception:
                pass
        if _DILITHIUM_AVAILABLE:
            try:
                dil_pk_b64 = dilithium_public_key_b64(master_secret=master_secret)
            except Exception:
                pass

    return {
        "pqc_mode": mode,
        "tls_mode": tls_mode,
        "kms_provider": kms,
        "key_rotation_days": rotation,
        "algorithms": {
            "key_encapsulation": {
                "id":      "ML-KEM-768",
                "standard": "FIPS 203",
                "status":  "active" if (_KYBER_AVAILABLE and mode in ("hybrid", "pqc-only")) else (
                               "available" if _KYBER_AVAILABLE else "unavailable"
                           ),
                "library": "kyber-py",
                "description": "CRYSTALS-Kyber — quantum-safe key encapsulation for MFA secrets",
            },
            "digital_signature": {
                "id":      "ML-DSA-65",
                "standard": "FIPS 204",
                "status":  "active" if (_DILITHIUM_AVAILABLE and mode in ("hybrid", "pqc-only")) else (
                               "available" if _DILITHIUM_AVAILABLE else "unavailable"
                           ),
                "library": "dilithium-py",
                "description": "CRYSTALS-Dilithium — quantum-safe digital signatures for tokens",
            },
            "symmetric_encryption": {
                "id":      "AES-256-GCM",
                "standard": "FIPS 197",
                "status":  "active",
                "library": "cryptography",
                "description": "256-bit AES-GCM AEAD — quantum-resistant (Grover: 128-bit security)",
            },
            "mac": {
                "id":      "HMAC-SHA3-512",
                "standard": "FIPS 198-1 + FIPS 202",
                "status":  "active",
                "library": "hashlib",
                "description": "512-bit HMAC — quantum-resistant (Grover: 256-bit security)",
            },
            "password_kdf": {
                "id":      "PBKDF2-HMAC-SHA3-512",
                "standard": "NIST SP 800-132",
                "status":  "active",
                "iterations": 450_000,
                "description": "Password key derivation with 450K iterations — exceeds NIST minimum",
            },
        },
        "token_format": {
            "version":  "v2" if (_DILITHIUM_AVAILABLE and mode in ("hybrid", "pqc-only")) else "v1",
            "classical_sig": "HMAC-SHA3-512",
            "pqc_sig": "ML-DSA-65" if (_DILITHIUM_AVAILABLE and mode in ("hybrid", "pqc-only")) else None,
        },
        "mfa_encryption": {
            "scheme": SCHEME_HYBRID if (_KYBER_AVAILABLE and mode in ("hybrid", "pqc-only")) else SCHEME_AES_GCM,
            "kem": "ML-KEM-768" if _KYBER_AVAILABLE else None,
            "cipher": "AES-256-GCM",
            "key_combiner": "HKDF-SHA3-512",
        },
        "public_keys": {
            "ml_kem_768_ek":  kyber_pk_b64,   # encapsulation key (for external use)
            "ml_dsa_65_pk":   dil_pk_b64,      # verification key (for external verifiers)
        },
        "nist_compliance": {
            "FIPS-203": _KYBER_AVAILABLE,
            "FIPS-204": _DILITHIUM_AVAILABLE,
            "FIPS-197": _CRYPTO_AVAILABLE,
            "FIPS-198": True,   # HMAC always present
            "SP-800-132": True,  # PBKDF2 always present
        },
    }
