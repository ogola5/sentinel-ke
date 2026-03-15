from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import requests
from sqlalchemy.orm import Session

from app.core.security import compute_event_hash, sha256_hex, stable_json_dumps
from app.legal.models import LegalEvidenceAnchor, LegalEvidenceBundle


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _as_timeout(name: str, default: float) -> float:
    raw = _env(name, str(default))
    try:
        return float(raw)
    except ValueError:
        return default


def _as_int(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class MinioReceipt:
    backend: str
    status: str
    bucket: str | None
    object_key: str | None
    version_id: str | None
    etag: str | None
    error: str | None = None


@dataclass(frozen=True)
class ImmudbReceipt:
    backend: str
    status: str
    key: str | None
    tx_id: str | None
    verified: bool
    error: str | None = None


class MinioEvidenceAnchorClient:
    """
    MinIO anchoring modes:
    - disabled: skip
    - stub: deterministic local receipt (simulated, not immutable)
    - webhook: POST receipt payload to configured URL
    """

    def __init__(self) -> None:
        self.mode = _env("MINIO_ANCHOR_MODE", "disabled").lower()
        self.bucket = _env("MINIO_ANCHOR_BUCKET", "sentinel-legal-evidence")
        self.webhook_url = _env("MINIO_ANCHOR_WEBHOOK_URL", "")
        self.timeout = _as_timeout("MINIO_ANCHOR_TIMEOUT_SEC", 5.0)
        self.s3_endpoint = _env("MINIO_S3_ENDPOINT", "")
        self.s3_region = _env("MINIO_S3_REGION", "us-east-1")
        self.s3_access_key = _env("MINIO_S3_ACCESS_KEY", "")
        self.s3_secret_key = _env("MINIO_S3_SECRET_KEY", "")
        self.s3_secure = _env_bool("MINIO_S3_SECURE", False)
        self.s3_create_bucket = _env_bool("MINIO_S3_CREATE_BUCKET_IF_MISSING", False)
        self.retention_days = max(1, _as_int("MINIO_OBJECT_LOCK_RETENTION_DAYS", 365))
        self.legal_hold = _env_bool("MINIO_OBJECT_LEGAL_HOLD", True)

    def anchor(
        self,
        *,
        bundle_id: str,
        root_hash: str,
        chain_hash: str,
        payload_hash: str,
        payload_json: Dict[str, Any] | None = None,
    ) -> MinioReceipt:
        object_key = f"legal-bundles/{bundle_id}/{root_hash}.json"
        version_id = f"stub-{chain_hash[:16]}"
        etag = payload_hash[:32]

        if self.mode == "disabled":
            return MinioReceipt(
                backend="minio_disabled",
                status="skipped",
                bucket=self.bucket,
                object_key=object_key,
                version_id=None,
                etag=None,
            )

        if self.mode == "stub":
            return MinioReceipt(
                backend="minio_stub",
                status="simulated",
                bucket=self.bucket,
                object_key=object_key,
                version_id=version_id,
                etag=etag,
            )

        if self.mode == "s3":
            if not self.s3_endpoint:
                return MinioReceipt(
                    backend="minio_s3",
                    status="failed",
                    bucket=self.bucket,
                    object_key=object_key,
                    version_id=None,
                    etag=None,
                    error="missing_minio_s3_endpoint",
                )
            if not self.s3_access_key or not self.s3_secret_key:
                return MinioReceipt(
                    backend="minio_s3",
                    status="failed",
                    bucket=self.bucket,
                    object_key=object_key,
                    version_id=None,
                    etag=None,
                    error="missing_minio_s3_credentials",
                )
            return self._anchor_s3(
                bundle_id=bundle_id,
                root_hash=root_hash,
                chain_hash=chain_hash,
                payload_hash=payload_hash,
                object_key=object_key,
                payload_json=payload_json or {},
            )

        if self.mode != "webhook":
            return MinioReceipt(
                backend="minio_unknown",
                status="failed",
                bucket=self.bucket,
                object_key=object_key,
                version_id=None,
                etag=None,
                error=f"unsupported_minio_anchor_mode:{self.mode}",
            )

        if not self.webhook_url:
            return MinioReceipt(
                backend="minio_webhook",
                status="failed",
                bucket=self.bucket,
                object_key=object_key,
                version_id=None,
                etag=None,
                error="missing_minio_anchor_webhook_url",
            )

        body = {
            "bucket": self.bucket,
            "object_key": object_key,
            "root_hash": root_hash,
            "chain_hash": chain_hash,
            "payload_hash": payload_hash,
            "retention_mode": "COMPLIANCE",
            "object_lock": True,
        }
        try:
            res = requests.post(self.webhook_url, json=body, timeout=self.timeout)
            if res.status_code >= 300:
                return MinioReceipt(
                    backend="minio_webhook",
                    status="failed",
                    bucket=self.bucket,
                    object_key=object_key,
                    version_id=None,
                    etag=None,
                    error=f"minio_webhook_status_{res.status_code}",
                )
            data = res.json() if res.content else {}
            return MinioReceipt(
                backend="minio_webhook",
                status="anchored",
                bucket=self.bucket,
                object_key=object_key,
                version_id=str(data.get("version_id") or version_id),
                etag=str(data.get("etag") or etag),
            )
        except Exception as e:
            return MinioReceipt(
                backend="minio_webhook",
                status="failed",
                bucket=self.bucket,
                object_key=object_key,
                version_id=None,
                etag=None,
                error=f"minio_webhook_error:{e}",
            )

    def _anchor_s3(
        self,
        *,
        bundle_id: str,
        root_hash: str,
        chain_hash: str,
        payload_hash: str,
        object_key: str,
        payload_json: Dict[str, Any],
    ) -> MinioReceipt:
        try:
            import boto3  # type: ignore
            from botocore.client import Config  # type: ignore
            from botocore.exceptions import ClientError  # type: ignore
        except Exception as e:
            return MinioReceipt(
                backend="minio_s3",
                status="failed",
                bucket=self.bucket,
                object_key=object_key,
                version_id=None,
                etag=None,
                error=f"missing_boto3_dependency:{e}",
            )

        endpoint = self.s3_endpoint
        if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
            endpoint = ("https://" if self.s3_secure else "http://") + endpoint

        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=self.s3_access_key,
            aws_secret_access_key=self.s3_secret_key,
            region_name=self.s3_region,
            config=Config(signature_version="s3v4"),
        )

        try:
            s3.head_bucket(Bucket=self.bucket)
        except ClientError as e:
            if not self.s3_create_bucket:
                return MinioReceipt(
                    backend="minio_s3",
                    status="failed",
                    bucket=self.bucket,
                    object_key=object_key,
                    version_id=None,
                    etag=None,
                    error=f"bucket_not_accessible:{e}",
                )
            try:
                s3.create_bucket(Bucket=self.bucket)
            except ClientError as ce:
                return MinioReceipt(
                    backend="minio_s3",
                    status="failed",
                    bucket=self.bucket,
                    object_key=object_key,
                    version_id=None,
                    etag=None,
                    error=f"bucket_create_failed:{ce}",
                )

        body = {
            "bundle_id": bundle_id,
            "root_hash": root_hash,
            "chain_hash": chain_hash,
            "payload_hash": payload_hash,
            "anchored_at": _now_utc().isoformat(),
            "payload": payload_json,
        }
        body_raw = stable_json_dumps(body).encode("utf-8")

        put_kwargs: Dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": object_key,
            "Body": body_raw,
            "ContentType": "application/json",
        }

        retention_until = _now_utc() + timedelta(days=self.retention_days)
        put_kwargs["ObjectLockMode"] = "COMPLIANCE"
        put_kwargs["ObjectLockRetainUntilDate"] = retention_until
        if self.legal_hold:
            put_kwargs["ObjectLockLegalHoldStatus"] = "ON"

        try:
            res = s3.put_object(**put_kwargs)
            return MinioReceipt(
                backend="minio_s3",
                status="anchored",
                bucket=self.bucket,
                object_key=object_key,
                version_id=str(res.get("VersionId") or ""),
                etag=str(res.get("ETag") or "").strip('"') or None,
            )
        except ClientError as e:
            return MinioReceipt(
                backend="minio_s3",
                status="failed",
                bucket=self.bucket,
                object_key=object_key,
                version_id=None,
                etag=None,
                error=f"s3_put_failed:{e}",
            )


class ImmudbEvidenceAnchorClient:
    """
    immudb anchoring modes:
    - disabled: skip
    - stub: deterministic local receipt (simulated, not immutable)
    - webhook: POST key/value to configured URL
    """

    def __init__(self) -> None:
        self.mode = _env("IMMUDB_ANCHOR_MODE", "disabled").lower()
        self.webhook_url = _env("IMMUDB_ANCHOR_WEBHOOK_URL", "")
        self.http_base = _env("IMMUDB_HTTP_BASE_URL", "")
        self.http_anchor_path = _env("IMMUDB_HTTP_ANCHOR_PATH", "/api/v2/anchor")
        self.http_token = _env("IMMUDB_HTTP_TOKEN", "")
        self.timeout = _as_timeout("IMMUDB_ANCHOR_TIMEOUT_SEC", 5.0)

    def anchor(
        self,
        *,
        bundle_id: str,
        root_hash: str,
        chain_hash: str,
        payload_hash: str,
    ) -> ImmudbReceipt:
        key = f"legal_bundle:{bundle_id}"
        value = f"{root_hash}:{chain_hash}:{payload_hash}"
        stub_tx = str(int(sha256_hex(value.encode("utf-8"))[:10], 16))

        if self.mode == "disabled":
            return ImmudbReceipt(
                backend="immudb_disabled",
                status="skipped",
                key=key,
                tx_id=None,
                verified=False,
            )

        if self.mode == "stub":
            return ImmudbReceipt(
                backend="immudb_stub",
                status="simulated",
                key=key,
                tx_id=stub_tx,
                verified=True,
            )

        if self.mode == "http":
            if not self.http_base:
                return ImmudbReceipt(
                    backend="immudb_http",
                    status="failed",
                    key=key,
                    tx_id=None,
                    verified=False,
                    error="missing_immudb_http_base_url",
                )
            return self._anchor_http(
                key=key,
                value=value,
                bundle_id=bundle_id,
                root_hash=root_hash,
                chain_hash=chain_hash,
                payload_hash=payload_hash,
            )

        if self.mode != "webhook":
            return ImmudbReceipt(
                backend="immudb_unknown",
                status="failed",
                key=key,
                tx_id=None,
                verified=False,
                error=f"unsupported_immudb_anchor_mode:{self.mode}",
            )

        if not self.webhook_url:
            return ImmudbReceipt(
                backend="immudb_webhook",
                status="failed",
                key=key,
                tx_id=None,
                verified=False,
                error="missing_immudb_anchor_webhook_url",
            )

        body = {
            "key": key,
            "value": value,
            "bundle_id": bundle_id,
            "root_hash": root_hash,
            "chain_hash": chain_hash,
            "payload_hash": payload_hash,
        }
        try:
            res = requests.post(self.webhook_url, json=body, timeout=self.timeout)
            if res.status_code >= 300:
                return ImmudbReceipt(
                    backend="immudb_webhook",
                    status="failed",
                    key=key,
                    tx_id=None,
                    verified=False,
                    error=f"immudb_webhook_status_{res.status_code}",
                )
            data = res.json() if res.content else {}
            return ImmudbReceipt(
                backend="immudb_webhook",
                status="anchored",
                key=key,
                tx_id=str(data.get("tx_id") or stub_tx),
                verified=bool(data.get("verified", True)),
            )
        except Exception as e:
            return ImmudbReceipt(
                backend="immudb_webhook",
                status="failed",
                key=key,
                tx_id=None,
                verified=False,
                error=f"immudb_webhook_error:{e}",
            )

    def _anchor_http(
        self,
        *,
        key: str,
        value: str,
        bundle_id: str,
        root_hash: str,
        chain_hash: str,
        payload_hash: str,
    ) -> ImmudbReceipt:
        url = f"{self.http_base.rstrip('/')}/{self.http_anchor_path.lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        if self.http_token:
            headers["Authorization"] = f"Bearer {self.http_token}"

        body = {
            "key": key,
            "value": value,
            "bundle_id": bundle_id,
            "root_hash": root_hash,
            "chain_hash": chain_hash,
            "payload_hash": payload_hash,
        }
        try:
            res = requests.post(url, json=body, headers=headers, timeout=self.timeout)
            if res.status_code >= 300:
                return ImmudbReceipt(
                    backend="immudb_http",
                    status="failed",
                    key=key,
                    tx_id=None,
                    verified=False,
                    error=f"immudb_http_status_{res.status_code}",
                )
            data = res.json() if res.content else {}
            tx_id = str(data.get("tx_id") or "")
            verified = bool(data.get("verified", True))
            if not tx_id:
                return ImmudbReceipt(
                    backend="immudb_http",
                    status="failed",
                    key=key,
                    tx_id=None,
                    verified=False,
                    error="immudb_http_missing_tx_id",
                )
            return ImmudbReceipt(
                backend="immudb_http",
                status="anchored",
                key=key,
                tx_id=tx_id,
                verified=verified,
            )
        except Exception as e:
            return ImmudbReceipt(
                backend="immudb_http",
                status="failed",
                key=key,
                tx_id=None,
                verified=False,
                error=f"immudb_http_error:{e}",
            )


def merge_anchor_status(minio_status: str, immudb_status: str) -> str:
    a = minio_status == "anchored"
    b = immudb_status == "anchored"
    if a and b:
        return "anchored"
    if a or b:
        return "partial"
    if minio_status == "simulated" or immudb_status == "simulated":
        return "simulated"
    if minio_status == "skipped" and immudb_status == "skipped":
        return "skipped"
    return "failed"


class LegalEvidenceAnchoringService:
    def __init__(self, db: Session):
        self.db = db
        self.minio = MinioEvidenceAnchorClient()
        self.immudb = ImmudbEvidenceAnchorClient()

    def anchor_bundle(self, *, bundle: LegalEvidenceBundle, force: bool = False) -> Dict[str, Any]:
        existing = (
            self.db.query(LegalEvidenceAnchor)
            .filter(LegalEvidenceAnchor.bundle_id == bundle.bundle_id)
            .first()
        )
        if existing and not force:
            return self._anchor_to_dict(existing)

        payload_json = dict(bundle.payload_json or {})
        payload_hash = sha256_hex(stable_json_dumps(payload_json).encode("utf-8"))

        minio_receipt = self.minio.anchor(
            bundle_id=bundle.bundle_id,
            root_hash=bundle.root_hash,
            chain_hash=bundle.chain_hash,
            payload_hash=payload_hash,
            payload_json=payload_json,
        )
        immudb_receipt = self.immudb.anchor(
            bundle_id=bundle.bundle_id,
            root_hash=bundle.root_hash,
            chain_hash=bundle.chain_hash,
            payload_hash=payload_hash,
        )

        anchor_status = merge_anchor_status(minio_receipt.status, immudb_receipt.status)
        created_at = _now_utc()
        receipt_material = {
            "bundle_id": bundle.bundle_id,
            "root_hash": bundle.root_hash,
            "chain_hash": bundle.chain_hash,
            "payload_hash": payload_hash,
            "minio": minio_receipt.__dict__,
            "immudb": immudb_receipt.__dict__,
            "anchor_status": anchor_status,
            "created_at": created_at.isoformat(),
        }
        receipt_hash = compute_event_hash(receipt_material)

        if existing:
            row = existing
            row.minio_backend = minio_receipt.backend
            row.minio_bucket = minio_receipt.bucket
            row.minio_object_key = minio_receipt.object_key
            row.minio_version_id = minio_receipt.version_id
            row.minio_etag = minio_receipt.etag
            row.immudb_backend = immudb_receipt.backend
            row.immudb_key = immudb_receipt.key
            row.immudb_tx_id = immudb_receipt.tx_id
            row.immudb_verified = bool(immudb_receipt.verified)
            row.anchor_status = anchor_status
            row.anchor_receipt_hash = receipt_hash
            row.error_json = {
                "minio_error": minio_receipt.error,
                "immudb_error": immudb_receipt.error,
            }
            row.metadata_json = {
                "payload_hash": payload_hash,
                "root_hash": bundle.root_hash,
                "chain_hash": bundle.chain_hash,
                "minio_status": minio_receipt.status,
                "immudb_status": immudb_receipt.status,
                "mode": {
                    "minio": self.minio.mode,
                    "immudb": self.immudb.mode,
                },
            }
            row.created_at = created_at
        else:
            row = LegalEvidenceAnchor(
                anchor_id=str(uuid.uuid4()),
                bundle_id=bundle.bundle_id,
                minio_backend=minio_receipt.backend,
                minio_bucket=minio_receipt.bucket,
                minio_object_key=minio_receipt.object_key,
                minio_version_id=minio_receipt.version_id,
                minio_etag=minio_receipt.etag,
                immudb_backend=immudb_receipt.backend,
                immudb_key=immudb_receipt.key,
                immudb_tx_id=immudb_receipt.tx_id,
                immudb_verified=bool(immudb_receipt.verified),
                anchor_status=anchor_status,
                anchor_receipt_hash=receipt_hash,
                error_json={
                    "minio_error": minio_receipt.error,
                    "immudb_error": immudb_receipt.error,
                },
                metadata_json={
                    "payload_hash": payload_hash,
                    "root_hash": bundle.root_hash,
                    "chain_hash": bundle.chain_hash,
                    "minio_status": minio_receipt.status,
                    "immudb_status": immudb_receipt.status,
                    "mode": {
                        "minio": self.minio.mode,
                        "immudb": self.immudb.mode,
                    },
                },
                created_at=created_at,
            )
            self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self._anchor_to_dict(row)

    def get_anchor(self, *, bundle_id: str) -> Dict[str, Any]:
        row = (
            self.db.query(LegalEvidenceAnchor)
            .filter(LegalEvidenceAnchor.bundle_id == bundle_id)
            .first()
        )
        if not row:
            raise ValueError("legal_evidence_anchor_not_found")
        return self._anchor_to_dict(row)

    @staticmethod
    def _anchor_to_dict(row: LegalEvidenceAnchor) -> Dict[str, Any]:
        anchor_status = row.anchor_status
        if anchor_status == "anchored" and (
            str(row.minio_backend or "").endswith("_stub")
            or str(row.immudb_backend or "").endswith("_stub")
        ):
            anchor_status = "simulated"
        return {
            "anchor_id": row.anchor_id,
            "bundle_id": row.bundle_id,
            "anchor_status": anchor_status,
            "anchor_receipt_hash": row.anchor_receipt_hash,
            "minio": {
                "backend": row.minio_backend,
                "bucket": row.minio_bucket,
                "object_key": row.minio_object_key,
                "version_id": row.minio_version_id,
                "etag": row.minio_etag,
            },
            "immudb": {
                "backend": row.immudb_backend,
                "key": row.immudb_key,
                "tx_id": row.immudb_tx_id,
                "verified": row.immudb_verified,
            },
            "errors": row.error_json or {},
            "metadata": row.metadata_json or {},
            "created_at": row.created_at.isoformat(),
        }
