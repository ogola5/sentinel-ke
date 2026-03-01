from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.integrations.real_data_pipeline import (
    build_kev_epss_records,
    fetch_epss_lookup,
    ingest_records_via_connectors,
    iter_rows_from_path,
    normalize_caida_row,
    normalize_cic_row,
    NormalizedConnectorRecord,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

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
