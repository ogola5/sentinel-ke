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
    assert "pgaudit_event_v1" in keys
    assert "wazuh_fim_v1" in keys
    assert "velociraptor_artifact_v1" in keys
    assert "m365_bec_mail_v1" in keys
    assert "waf_api_attack_v1" in keys
    assert "kev_vuln_feed_v1" in keys
    assert "backup_attestation_v1" in keys


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


def test_map_pgaudit_event_to_db_audit_event():
    ev = map_external_event(
        connector_key="pgaudit_event_v1",
        payload={
            "timestamp": "2026-02-14T08:00:00Z",
            "db_instance": "pg-primary-01",
            "db_name": "ifmis",
            "db_user": "svc_audit",
            "statement_type": "COPY",
            "table": "payments_2026",
            "query": "COPY payments_2026 TO PROGRAM 'curl ...'",
            "success": True,
            "audit_setting_changed": True,
        },
        confidence=0.95,
    )

    assert ev.event_type == "DB_AUDIT_EVENT"
    assert ev.anchors["service_id"] == "pg-primary-01"
    assert ev.payload["statement_type"] == "COPY"
    assert "query_fingerprint" in ev.payload
    assert "high_impact_db_statement" in ev.payload["reason_codes"]
    assert "audit_config_changed" in ev.payload["reason_codes"]


def test_map_wazuh_fim_event_to_file_integrity_event():
    ev = map_external_event(
        connector_key="wazuh_fim_v1",
        payload={
            "timestamp": "2026-02-14T08:05:00Z",
            "hostname": "county-finance-db-01",
            "path": "/var/backups/ifmis/ledger.sql.gz",
            "action": "deleted",
            "critical_path": True,
            "user": "root",
            "process_name": "rm",
        },
        confidence=0.9,
    )

    assert ev.event_type == "FILE_INTEGRITY_EVENT"
    assert ev.payload["action"] == "deleted"
    assert ev.payload["is_critical_path"] is True
    assert "file_deleted" in ev.payload["reason_codes"]
    assert "critical_path_mutation" in ev.payload["reason_codes"]
    assert ev.anchors["device_id"] == "county-finance-db-01"


def test_map_velociraptor_artifact_to_dfir_finding_event():
    ev = map_external_event(
        connector_key="velociraptor_artifact_v1",
        payload={
            "timestamp": "2026-02-14T08:15:00Z",
            "host": "gov-mail-01",
            "artifact": "Windows.Detection.EventLogs",
            "finding_type": "eventlog_cleared",
            "severity": "high",
            "eventlog_cleared": True,
            "user": "administrator",
        },
        confidence=0.88,
    )

    assert ev.event_type == "DFIR_FINDING_EVENT"
    assert ev.payload["artifact_name"] == "Windows.Detection.EventLogs"
    assert ev.payload["severity"] == "high"
    assert "log_tamper_signal" in ev.payload["reason_codes"]
    assert ev.anchors["service_id"] == "endpoint:gov-mail-01"


def test_map_waf_api_attack_to_web_attack_event():
    ev = map_external_event(
        connector_key="waf_api_attack_v1",
        payload={
            "timestamp": "2026-02-14T10:20:00Z",
            "service_id": "gov-api-portal",
            "endpoint": "/v1/payments",
            "attack_type": "sql_injection",
            "decision": "allowed",
            "src_ip": "41.90.0.10",
        },
        confidence=0.91,
    )

    assert ev.event_type == "WEB_ATTACK_EVENT"
    assert ev.payload["status"] == "allowed"
    assert "waf_bypass_signal" in ev.payload["reason_codes"]
    assert ev.anchors["service_id"] == "gov-api-portal"
    assert ev.anchors["ip"] == "41.90.0.10"


def test_map_kev_vuln_to_vulnerability_event():
    ev = map_external_event(
        connector_key="kev_vuln_feed_v1",
        payload={
            "published_at": "2026-02-14T10:30:00Z",
            "asset_id": "county-finance-db-01",
            "cve": "cve-2026-1001",
            "severity": "critical",
            "known_exploited": True,
            "epss": 0.87,
            "cisa_due_date": "2026-03-01T00:00:00Z",
        },
        confidence=0.93,
    )

    assert ev.event_type == "VULNERABILITY_EVENT"
    assert ev.payload["cve_id"] == "CVE-2026-1001"
    assert ev.payload["kev"] is True
    assert ev.anchors["service_id"] == "county-finance-db-01"


def test_map_backup_attestation_to_backup_event():
    ev = map_external_event(
        connector_key="backup_attestation_v1",
        payload={
            "attested_at": "2026-02-14T10:40:00Z",
            "asset_id": "ifmis-db-01",
            "backup_id": "snap-123",
            "immutable": False,
            "status": "risk",
        },
        confidence=0.8,
    )

    assert ev.event_type == "BACKUP_ATTESTATION_EVENT"
    assert ev.payload["backup_id"] == "snap-123"
    assert ev.payload["status"] == "risk"
    assert ev.anchors["service_id"] == "ifmis-db-01"
