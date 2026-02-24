from types import SimpleNamespace

from app.legal.service import LegalAuthorizationService


def test_certificate_to_dict_shape():
    row = SimpleNamespace(
        certificate_id="c-1",
        bundle_id="b-1",
        framework="evidence_act_sec_106b",
        jurisdiction="KE",
        statement_hash="h1",
        signed_by="analyst-1",
        signature_method="sha256_attestation",
        signature="sig-1",
        metadata_json={"k": "v"},
        created_at=SimpleNamespace(isoformat=lambda: "2026-02-24T10:00:00+00:00"),
    )
    out = LegalAuthorizationService._certificate_to_dict(row)
    assert out["certificate_id"] == "c-1"
    assert out["bundle_id"] == "b-1"
    assert out["jurisdiction"] == "KE"
