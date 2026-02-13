from __future__ import annotations

import pytest

from app.integrations.connectors import list_connectors, map_external_event


def test_list_connectors_includes_expected_keys():
    keys = {item["key"] for item in list_connectors()}
    assert "splunk_login_v1" in keys
    assert "core_banking_tx_v1" in keys
    assert "cloudflare_ddos_v1" in keys
    assert "telco_sim_swap_v1" in keys
    assert "local_network_probe_v1" in keys


def test_map_splunk_login_event():
    ev = map_external_event(
        connector_key="splunk_login_v1",
        payload={
            "_time": "2026-02-13T10:45:00Z",
            "user": "alice",
            "status": "failed",
            "src_ip": "1.2.3.4",
            "ua": "Mozilla/5.0",
        },
        confidence=0.8,
    )

    assert ev.event_type == "LOGIN_EVENT"
    assert ev.payload["username"] == "alice"
    assert ev.payload["outcome"] == "failure"
    assert ev.anchors["ip"] == "1.2.3.4"


def test_map_core_banking_event_derives_account_anchor_when_ip_missing():
    ev = map_external_event(
        connector_key="core_banking_tx_v1",
        payload={
            "transaction_time": "2026-02-13T11:00:00Z",
            "from_account": "ACC-001",
            "to_account": "ACC-002",
            "amount": 1500,
            "currency": "KES",
        },
        confidence=0.9,
    )

    assert ev.event_type == "TRANSACTION_EVENT"
    assert ev.payload["account_from"] == "ACC-001"
    assert ev.payload["account_to"] == "ACC-002"
    assert ev.anchors.get("account_h")


def test_map_unknown_connector_raises():
    with pytest.raises(ValueError) as e:
        map_external_event(connector_key="unknown", payload={})
    assert "unknown connector" in str(e.value)


def test_map_local_network_probe_to_service_health_event():
    ev = map_external_event(
        connector_key="local_network_probe_v1",
        payload={
            "timestamp": "2026-02-13T12:30:00Z",
            "hostname": "workstation-01",
            "interface": "eth0",
            "default_gateway": "192.168.1.1",
            "dns_servers": ["1.1.1.1", "8.8.8.8"],
            "rx_bytes": 1024,
            "tx_bytes": 2048,
            "rx_bps": 100.5,
            "tx_bps": 200.5,
            "link_up": True,
        },
        confidence=0.86,
    )

    assert ev.event_type == "SERVICE_HEALTH_EVENT"
    assert ev.payload["service_id"] == "local-network:workstation-01:eth0"
    assert ev.payload["status"] == "up"
    assert ev.payload["gateway"] == "192.168.1.1"
    assert ev.payload["dns_servers"] == ["1.1.1.1", "8.8.8.8"]
    assert ev.anchors["service_id"] == "local-network:workstation-01:eth0"
