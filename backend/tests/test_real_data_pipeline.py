from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.integrations.real_data_pipeline import (
    build_feodo_records,
    build_kev_epss_records,
    build_malwarebazaar_records,
    build_otx_indicator_records,
    build_threatfox_records,
    build_otx_stix_bundle,
    build_urlhaus_records,
    fetch_epss_lookup,
    ingest_records_via_connectors,
    iter_rows_from_path,
    load_feodo_rows,
    load_malwarebazaar_rows,
    load_threatfox_rows,
    normalize_caida_row,
    normalize_cic_row,
    normalize_vpn_benchmark_row,
    _run_ppra_job,
    NormalizedConnectorRecord,
)


class _FakeResponse:
    def __init__(self, payload, *, text: str = ""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_epss_lookup_parses_scores_from_api_payload():
    def _fake_get(url, params=None, timeout=30):
        assert "epss" in url
        assert "cve" in (params or {})
        return _FakeResponse(
            {
                "status": "OK",
                "data": [
                    {"cve": "CVE-2024-1111", "epss": "0.91"},
                    {"cve": "CVE-2024-2222", "epss": "0.42"},
                ],
            }
        )

    out = fetch_epss_lookup(
        ["CVE-2024-1111", "CVE-2024-2222"],
        getter=_fake_get,
    )
    assert out["CVE-2024-1111"] == 0.91
    assert out["CVE-2024-2222"] == 0.42


def test_build_kev_epss_records_maps_required_connector_fields():
    rows = [
        {
            "cveID": "CVE-2024-1111",
            "dateAdded": "2026-02-01",
            "dueDate": "2026-03-01",
            "knownRansomwareCampaignUse": "Known",
            "vendorProject": "vendor-a",
            "product": "product-a",
        }
    ]
    records = build_kev_epss_records(rows, asset_id="county-finance-db-01", epss_lookup={"CVE-2024-1111": 0.83})
    assert len(records) == 1
    item = records[0]
    assert item.connector_key == "kev_vuln_feed_v1"
    assert item.payload["asset_id"] == "county-finance-db-01"
    assert item.payload["cve_id"] == "CVE-2024-1111"
    assert item.payload["kev"] is True
    assert item.payload["severity"] == "critical"
    assert item.payload["epss"] == 0.83


def test_load_feodo_rows_accepts_json_list_from_api():
    def _fake_get(url, params=None, timeout=30):
        del url, params, timeout
        return _FakeResponse(
            [
                {
                    "first_seen_utc": "2026-03-09T00:00:00Z",
                    "ip_address": "198.51.100.10",
                    "malware": "qakbot",
                }
            ]
        )

    rows = load_feodo_rows(getter=_fake_get)
    assert rows[0]["ip_address"] == "198.51.100.10"


def test_build_feodo_records_maps_required_connector_fields():
    rows = [
        {
            "first_seen_utc": "2026-03-09T00:00:00Z",
            "ip_address": "198.51.100.10",
            "malware": "qakbot",
            "status": "online",
        }
    ]
    records = build_feodo_records(rows)
    assert len(records) == 1
    item = records[0]
    assert item.connector_key == "feodo_c2_v1"
    assert item.payload["ip_address"] == "198.51.100.10"
    assert item.payload["malware"] == "qakbot"


def test_build_urlhaus_records_extracts_url_and_host():
    rows = [
        {
            "dateadded": "2026-03-09 12:00:00",
            "url": "http://bad.example/dropper.exe",
            "host": "bad.example",
            "host_ip": "203.0.113.55",
            "threat": "malware_download",
        }
    ]
    records = build_urlhaus_records(rows)
    assert len(records) == 1
    item = records[0]
    assert item.connector_key == "urlhaus_ioc_v1"
    assert item.payload["url"] == "http://bad.example/dropper.exe"
    assert item.payload["host"] == "bad.example"


def test_load_threatfox_rows_accepts_json_list_from_api():
    def _fake_get(url, params=None, timeout=30, headers=None):
        del url, params, timeout, headers
        return _FakeResponse({"data": [{"ioc": "203.0.113.5", "ioc_type": "ip"}]})

    rows = load_threatfox_rows(getter=_fake_get)
    assert rows[0]["ioc"] == "203.0.113.5"


def test_load_threatfox_rows_sends_auth_key_header(monkeypatch):
    captured = {}

    def _fake_get(url, params=None, timeout=30, headers=None):
        del url, params, timeout
        captured["headers"] = headers
        return _FakeResponse({"data": [{"ioc": "203.0.113.5", "ioc_type": "ip"}]})

    monkeypatch.setenv("ABUSECH_AUTH_KEY", "secret-auth")
    rows = load_threatfox_rows(getter=_fake_get)
    assert rows[0]["ioc"] == "203.0.113.5"
    assert captured["headers"] == {"Auth-Key": "secret-auth"}


def test_build_threatfox_records_maps_required_connector_fields():
    rows = [
        {
            "first_seen": "2026-03-09T12:00:00Z",
            "ioc": "203.0.113.5",
            "ioc_type": "ip",
            "malware": "qakbot",
            "status": "active",
        }
    ]
    records = build_threatfox_records(rows)
    assert len(records) == 1
    item = records[0]
    assert item.connector_key == "threatfox_ioc_v1"
    assert item.payload["indicator"] == "203.0.113.5"
    assert item.payload["indicator_type"] == "ip"
    assert item.payload["malware"] == "qakbot"


def test_load_malwarebazaar_rows_accepts_json_list_from_api():
    def _fake_post(url, data=None, timeout=30, headers=None):
        del url, data, timeout, headers
        return _FakeResponse({"data": [{"sha256_hash": "ab" * 32}]})

    rows = load_malwarebazaar_rows(getter=_fake_post)
    assert rows[0]["sha256_hash"] == "ab" * 32


def test_load_malwarebazaar_rows_sends_auth_key_header(monkeypatch):
    captured = {}

    def _fake_post(url, data=None, timeout=30, headers=None):
        del url, data, timeout
        captured["headers"] = headers
        return _FakeResponse({"data": [{"sha256_hash": "ab" * 32}]})

    monkeypatch.setenv("ABUSECH_AUTH_KEY", "secret-auth")
    rows = load_malwarebazaar_rows(getter=_fake_post)
    assert rows[0]["sha256_hash"] == "ab" * 32
    assert captured["headers"] == {"Auth-Key": "secret-auth"}


def test_build_malwarebazaar_records_maps_required_connector_fields():
    rows = [
        {
            "first_seen": "2026-03-09T12:00:00Z",
            "sha256_hash": "ab" * 32,
            "signature": "win.qakbot",
            "file_name": "dropper.exe",
        }
    ]
    records = build_malwarebazaar_records(rows)
    assert len(records) == 1
    item = records[0]
    assert item.connector_key == "malwarebazaar_sample_v1"
    assert item.payload["sha256_hash"] == "ab" * 32
    assert item.payload["malware_family"] == "win.qakbot"


def test_normalize_vpn_benchmark_row_maps_vpn_rows_to_login_connector():
    row = {
        "timestamp": "2016-07-01T10:20:30Z",
        "src_ip": "10.0.0.5",
        "dst_ip": "198.51.100.10",
        "label": "VPN",
        "app_label": "OpenVPN",
        "protocol": "udp",
    }
    record = normalize_vpn_benchmark_row(row)
    assert record is not None
    assert record.connector_key == "vpn_gateway_session_v1"
    assert record.payload["src_ip"] == "10.0.0.5"
    assert record.payload["provider"] == "OpenVPN"


def test_normalize_vpn_benchmark_row_keeps_nonvpn_rows_as_benign_login_signal():
    row = {
        "timestamp": "2016-07-01T10:20:30Z",
        "src_ip": "10.0.0.6",
        "dst_ip": "198.51.100.11",
        "label": "nonVPN",
        "app_label": "HTTP",
        "protocol": "tcp",
    }
    record = normalize_vpn_benchmark_row(row)
    assert record is not None
    assert record.connector_key == "vpn_gateway_session_v1"
    assert record.payload["src_ip"] == "10.0.0.6"
    assert record.payload["vpn_detected"] is False
    assert record.payload["confirmed_benign"] is True


def test_build_otx_indicator_records_and_stix_bundle():
    pulses = [
        {
            "id": "pulse-1",
            "name": "OTX pulse",
            "created": "2026-03-09T12:00:00Z",
            "modified": "2026-03-09T12:05:00Z",
            "tags": ["phishing"],
            "indicators": [
                {"type": "domain", "indicator": "bad.example"},
                {"type": "IPv4", "indicator": "203.0.113.10"},
            ],
        }
    ]
    records = build_otx_indicator_records(pulses)
    bundle = build_otx_stix_bundle(pulses)

    assert len(records) == 2
    assert {r.connector_key for r in records} == {"otx_indicator_v1"}
    assert len(bundle["objects"]) == 2
    assert any("domain-name:value" in obj["pattern"] for obj in bundle["objects"])


def test_normalize_cic_row_ddos_maps_to_ddos_connector():
    row = {
        "Label": "DDoS attack-HOIC",
        "Timestamp": "2018-02-14 10:20:30",
        "Src IP": "10.0.0.5",
        "Dst IP": "172.16.0.10",
        "Flow Packets/s": "1234.5",
        "Dst Port": "443",
    }
    record = normalize_cic_row(row, service_id_prefix="safaricom")
    assert record is not None
    assert record.connector_key == "cloudflare_ddos_v1"
    assert record.payload["service_id"] == "safaricom:172.16.0.10"
    assert record.payload["request_rate"] == 1234.5
    assert record.payload["endpoint"] == "port:443"


def test_normalize_cic_row_benign_keeps_negative_ddos_background():
    row = {
        "Label": "BENIGN",
        "Timestamp": "2018-02-14 10:20:30",
        "Src IP": "10.0.0.5",
        "Dst IP": "172.16.0.10",
        "Flow Packets/s": "22.0",
        "Dst Port": "443",
    }
    record = normalize_cic_row(row, service_id_prefix="safaricom")
    assert record is not None
    assert record.connector_key == "cloudflare_ddos_v1"
    assert record.payload["confirmed_benign"] is True
    assert record.payload["benchmark_family"] == "ddos"


def test_normalize_cic_row_web_maps_to_web_connector():
    row = {
        "Label": "Web Attack - SQL Injection",
        "Timestamp": "2018-02-14 10:20:30",
        "Src IP": "10.1.1.3",
        "Dst IP": "172.16.0.20",
        "URI": "/api/payments",
        "Method": "POST",
        "Total Fwd Packets": "15",
    }
    record = normalize_cic_row(row, service_id_prefix="ecitizen")
    assert record is not None
    assert record.connector_key == "waf_api_attack_v1"
    assert record.payload["service_id"] == "ecitizen:172.16.0.20"
    assert record.payload["attack_type"] == "sql_injection"
    assert record.payload["status"] == "detected"
    assert record.payload["req_count"] == 15


def test_normalize_caida_row_maps_to_ddos_connector():
    row = {
        "timestamp": "2026-02-27T10:10:00Z",
        "target_ip": "41.90.1.10",
        "pps": 22000,
        "unique_src_ips": 1200,
        "target_port": 443,
        "protocol": "TCP",
    }
    record = normalize_caida_row(row, service_id_prefix="ke-infra")
    assert record is not None
    assert record.connector_key == "cloudflare_ddos_v1"
    assert record.payload["service_id"] == "ke-infra:41.90.1.10"
    assert record.payload["request_rate"] == 22000.0
    assert record.payload["unique_ips_count"] == 1200
    assert record.payload["endpoint"] == "port:443"


def test_run_ppra_job_is_deprecated_in_favor_of_corruption_ingesters():
    args = SimpleNamespace(input_file="/tmp/ppra.csv")
    with pytest.raises(ValueError, match="deprecated"):
        _run_ppra_job(args)


def test_iter_rows_from_path_supports_csv_and_jsonl(tmp_path: Path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    csv_rows = list(iter_rows_from_path(str(csv_path)))
    assert csv_rows == [{"a": "1", "b": "2"}]

    jsonl_path = tmp_path / "sample.jsonl"
    jsonl_path.write_text(json.dumps({"x": 1}) + "\n" + json.dumps({"x": 2}) + "\n", encoding="utf-8")
    jsonl_rows = list(iter_rows_from_path(str(jsonl_path)))
    assert jsonl_rows == [{"x": 1}, {"x": 2}]


def test_ingest_records_via_connectors_uses_connector_mapping(monkeypatch):
    calls = {"mapped": 0, "ingested": 0}

    class _FakeSvc:
        def __init__(self, db, pseudonym_salt=None):
            return None

        def ingest_event(self, *, event, source_api_key):
            calls["ingested"] += 1

            class _Result:
                status = "accepted"

            return _Result()

    def _fake_map_external_event(*, connector_key, payload, confidence, classification):
        calls["mapped"] += 1
        return SimpleNamespace(
            event_type="WEB_ATTACK_EVENT",
            payload=payload,
            anchors={"service_id": "svc-1"},
            occurred_at="2026-03-01T00:00:00Z",
            schema_version="v1",
            classification=classification,
        )

    monkeypatch.setattr("app.integrations.real_data_pipeline.IngestionService", _FakeSvc)
    monkeypatch.setattr("app.integrations.real_data_pipeline.map_external_event", _fake_map_external_event)

    stats = ingest_records_via_connectors(
        db=object(),
        records=[
            NormalizedConnectorRecord(
                connector_key="waf_api_attack_v1",
                payload={"timestamp": "2026-03-01T00:00:00Z", "service_id": "svc-1", "attack_type": "sql_injection"},
                confidence=0.9,
            )
        ],
        source_api_key="test-key",
    )
    assert stats.accepted == 1
    assert stats.errors == 0
    assert calls["mapped"] == 1
    assert calls["ingested"] == 1
