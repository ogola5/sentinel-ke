from __future__ import annotations

from scripts import demo_federation_show as demo
from scripts import seed_demo_agencies as seed


def test_demo_partner_hashes_match_federation_demo_hmac():
    entity = "phone:+254700123456"
    salt = "national-demo-salt"
    hashes = seed.build_demo_partner_hashes([entity], salt=salt)
    assert hashes[entity] == demo._hmac_hash(entity, salt)  # noqa: SLF001


def test_demo_partner_hashes_are_distinct_per_entity():
    hashes = seed.build_demo_partner_hashes(
        ["phone:+254700123456", "ip:196.201.214.55"],
        salt="national-demo-salt",
    )
    assert len(hashes) == 2
    assert len(set(hashes.values())) == 2


def test_seed_specs_have_unique_usernames_and_partners():
    usernames = [item["username"] for item in seed.AGENCIES]
    partner_ids = [item["partner_id"] for item in seed.PARTNERS]
    assert len(usernames) == len(set(usernames))
    assert len(partner_ids) == len(set(partner_ids))
    assert any(item["access_level"] == "central" for item in seed.AGENCIES)


def test_credentials_manifest_redacts_secrets_by_default():
    manifest = seed._credentials_manifest(include_secrets=False)  # noqa: SLF001
    assert manifest["include_secrets"] is False
    assert "password" not in manifest["users"][0]
    assert "api_key" not in manifest["partners"][0]
    assert "api_key_fingerprint" in manifest["partners"][0]


def test_api_key_fingerprint_is_redacted():
    fp = seed._api_key_fingerprint("demo-secret-api-key")  # noqa: SLF001
    assert fp.endswith("…")
    assert "demo-secret-api-key" not in fp
