from __future__ import annotations

from app.legal.anchoring import (
    ImmudbEvidenceAnchorClient,
    MinioEvidenceAnchorClient,
    merge_anchor_status,
)


def test_minio_stub_anchor_is_deterministic(monkeypatch):
    monkeypatch.setenv("MINIO_ANCHOR_MODE", "stub")
    monkeypatch.setenv("MINIO_ANCHOR_BUCKET", "evidence-test")

    client = MinioEvidenceAnchorClient()
    r1 = client.anchor(
        bundle_id="bundle-1",
        root_hash="root123",
        chain_hash="chain456",
        payload_hash="abcde" * 20,
    )
    r2 = client.anchor(
        bundle_id="bundle-1",
        root_hash="root123",
        chain_hash="chain456",
        payload_hash="abcde" * 20,
    )
    assert r1.status == "simulated"
    assert r1.backend == "minio_stub"
    assert r1.bucket == "evidence-test"
    assert r1.object_key == r2.object_key
    assert r1.version_id == r2.version_id
    assert r1.etag == r2.etag


def test_immudb_stub_anchor_generates_tx(monkeypatch):
    monkeypatch.setenv("IMMUDB_ANCHOR_MODE", "stub")
    client = ImmudbEvidenceAnchorClient()
    out = client.anchor(
        bundle_id="bundle-xyz",
        root_hash="root-h",
        chain_hash="chain-h",
        payload_hash="payload-h",
    )
    assert out.status == "simulated"
    assert out.backend == "immudb_stub"
    assert out.verified is True
    assert out.key == "legal_bundle:bundle-xyz"
    assert out.tx_id is not None and out.tx_id.isdigit()


def test_minio_s3_mode_requires_endpoint_and_credentials(monkeypatch):
    monkeypatch.setenv("MINIO_ANCHOR_MODE", "s3")
    monkeypatch.delenv("MINIO_S3_ENDPOINT", raising=False)
    monkeypatch.delenv("MINIO_S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("MINIO_S3_SECRET_KEY", raising=False)
    client = MinioEvidenceAnchorClient()
    out = client.anchor(
        bundle_id="bundle-2",
        root_hash="root-2",
        chain_hash="chain-2",
        payload_hash="payload-2",
    )
    assert out.status == "failed"
    assert out.backend == "minio_s3"
    assert out.error == "missing_minio_s3_endpoint"


def test_immudb_http_mode_requires_base_url(monkeypatch):
    monkeypatch.setenv("IMMUDB_ANCHOR_MODE", "http")
    monkeypatch.delenv("IMMUDB_HTTP_BASE_URL", raising=False)
    client = ImmudbEvidenceAnchorClient()
    out = client.anchor(
        bundle_id="bundle-3",
        root_hash="root-3",
        chain_hash="chain-3",
        payload_hash="payload-3",
    )
    assert out.status == "failed"
    assert out.backend == "immudb_http"
    assert out.error == "missing_immudb_http_base_url"


def test_anchor_status_merge():
    assert merge_anchor_status("anchored", "anchored") == "anchored"
    assert merge_anchor_status("anchored", "failed") == "partial"
    assert merge_anchor_status("failed", "anchored") == "partial"
    assert merge_anchor_status("skipped", "skipped") == "skipped"
    assert merge_anchor_status("failed", "failed") == "failed"
