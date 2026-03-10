from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from app.core.security import pseudonymize
from app.ingestion.schemas import CanonicalEvent


MapperFn = Callable[[Dict[str, Any], float, Optional[str]], CanonicalEvent]


@dataclass(frozen=True)
class ConnectorDefinition:
    key: str
    description: str
    required_fields: Tuple[str, ...]
    mapper: MapperFn


def _coerce_confidence(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _first_value(payload: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
    for k in keys:
        if k in payload and payload[k] is not None:
            return payload[k]
    return None


def _as_str(payload: Dict[str, Any], keys: Tuple[str, ...], *, required: bool = False) -> Optional[str]:
    raw = _first_value(payload, keys)
    if raw is None:
        if required:
            joined = ", ".join(keys)
            raise ValueError(f"missing required field: one of ({joined})")
        return None
    s = str(raw).strip()
    if not s:
        if required:
            joined = ", ".join(keys)
            raise ValueError(f"empty required field: one of ({joined})")
        return None
    return s


def _as_float(payload: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[float]:
    raw = _first_value(payload, keys)
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    return float(s)


def _as_int(payload: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[int]:
    raw = _first_value(payload, keys)
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    s = str(raw).strip()
    if not s:
        return None
    return int(float(s))


def _as_bool(payload: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[bool]:
    raw = _first_value(payload, keys)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in {"1", "true", "t", "yes", "y", "on", "up"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off", "down"}:
        return False
    return None


def _as_str_list(payload: Dict[str, Any], keys: Tuple[str, ...]) -> List[str]:
    raw = _first_value(payload, keys)
    if raw is None:
        return []

    if isinstance(raw, (list, tuple, set)):
        out = [str(v).strip() for v in raw if str(v).strip()]
    else:
        s = str(raw).strip()
        if not s:
            return []
        out = [v.strip() for v in s.split(",") if v.strip()]

    deduped: List[str] = []
    seen = set()
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _as_datetime(payload: Dict[str, Any], keys: Tuple[str, ...]) -> datetime:
    raw = _first_value(payload, keys)
    if raw is None:
        raise ValueError(f"missing timestamp field: expected one of {', '.join(keys)}")

    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:
            ts = ts / 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        s = str(raw).strip()
        if not s:
            raise ValueError("timestamp field is empty")
        if s.isdigit():
            ts = float(s)
            if ts > 1e12:
                ts = ts / 1000.0
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            normalized = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_login_outcome(v: Optional[str]) -> str:
    if not v:
        return "unknown"
    x = v.strip().lower()
    if x in {"ok", "success", "succeeded", "allow", "allowed", "pass"}:
        return "success"
    if x in {"fail", "failed", "failure", "deny", "denied", "blocked", "error"}:
        return "failure"
    return "unknown"


def _normalize_service_status(v: Optional[str]) -> str:
    if not v:
        return "up"
    x = v.strip().lower()
    if x in {"up", "ok", "healthy", "normal"}:
        return "up"
    if x in {"degraded", "warn", "warning", "partial"}:
        return "degraded"
    if x in {"down", "failed", "offline", "error"}:
        return "down"
    return "degraded"


def _normalize_fim_action(v: Optional[str]) -> str:
    if not v:
        return "modified"
    x = v.strip().lower()
    if x in {"added", "create", "created", "new"}:
        return "created"
    if x in {"delete", "deleted", "removed", "unlink"}:
        return "deleted"
    if x in {"renamed", "rename", "moved", "move"}:
        return "moved"
    if x in {"perm", "permission_changed", "chmod", "chown"}:
        return "permission_changed"
    return "modified"


def _normalize_severity(v: Optional[str], *, default: str = "medium") -> str:
    if not v:
        return default
    x = v.strip().lower()
    if x in {"critical", "high", "medium", "low", "info"}:
        return x
    return default


def _normalize_web_attack_status(v: Optional[str]) -> str:
    if not v:
        return "detected"
    x = v.strip().lower()
    if x in {"blocked", "deny", "denied", "mitigated"}:
        return "blocked"
    if x in {"allow", "allowed", "pass"}:
        return "allowed"
    return "detected"


def _normalize_ioc_severity(v: Optional[str], *, default: str = "high") -> str:
    if not v:
        return default
    x = v.strip().lower()
    if x in {"critical", "high", "medium", "low", "info"}:
        return x
    if x in {"online", "active", "malicious"}:
        return "high"
    if x in {"offline", "disabled", "inactive"}:
        return "medium"
    return default


def _extract_domain_from_url(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    try:
        parsed = urlsplit(str(v).strip())
    except Exception:
        return None
    host = (parsed.hostname or "").strip().lower()
    return host or None


def _map_splunk_login(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "_time", "time", "occurred_at", "ts"))
    username = _as_str(payload, ("username", "user", "principal", "actor"))
    outcome = _normalize_login_outcome(_as_str(payload, ("result", "status", "outcome")))
    ip = _as_str(payload, ("ip", "src_ip", "source_ip", "client_ip"))
    device_id = _as_str(payload, ("device_id", "device", "host_id"))

    anchors: Dict[str, str] = {}
    if ip:
        anchors["ip"] = ip
    if device_id:
        anchors["device_id"] = device_id
    if not anchors:
        raise ValueError("splunk_login_v1 requires at least one of ip/src_ip or device_id")

    model_payload: Dict[str, Any] = {
        "username": username,
        "outcome": outcome,
        "user_agent": _as_str(payload, ("user_agent", "ua")),
        "device_id": device_id,
        "ip": ip,
        "asn": _as_int(payload, ("asn",)),
        "provider": _as_str(payload, ("provider", "isp")),
        "request_fingerprint": _as_str(payload, ("request_fingerprint", "fingerprint")),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="LOGIN_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_core_banking_tx(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "transaction_time"))
    account_from = _as_str(
        payload,
        ("account_from", "from_account", "debit_account", "source_account"),
    )
    account_to = _as_str(
        payload,
        ("account_to", "to_account", "credit_account", "destination_account"),
    )
    ip = _as_str(payload, ("ip", "src_ip", "source_ip"))
    device_id = _as_str(payload, ("device_id", "terminal_id"))

    anchors: Dict[str, str] = {}
    if ip:
        anchors["ip"] = ip
    if device_id:
        anchors["device_id"] = device_id
    if not anchors:
        anchor_source = account_from or account_to
        if anchor_source:
            anchors["account_h"] = pseudonymize(anchor_source, salt="integration-prehash")
        else:
            raise ValueError(
                "core_banking_tx_v1 requires ip/device_id or one account field for anchor derivation"
            )
    amount = _as_float(payload, ("amount", "value", "transaction_amount"))
    if amount is None:
        raise ValueError("core_banking_tx_v1 requires amount/value/transaction_amount")

    model_payload: Dict[str, Any] = {
        "account_from": account_from,
        "account_to": account_to,
        "amount": amount,
        "currency": _as_str(payload, ("currency", "ccy")) or "KES",
        "channel": _as_str(payload, ("channel", "transaction_channel")),
        "ip": ip,
        "device_id": device_id,
        "agent_id": _as_str(payload, ("agent_id", "branch_id")),
        "agent_location": _as_str(payload, ("agent_location", "branch_location")),
        "withdrawal_type": _as_str(payload, ("withdrawal_type", "cashout_type")),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="TRANSACTION_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_cloudflare_ddos(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "window_end"))
    service_id = _as_str(payload, ("service_id", "zone_id", "application"), required=True)
    endpoint = _as_str(payload, ("endpoint", "path", "uri"))

    anchors: Dict[str, str] = {"service_id": service_id}
    if endpoint:
        anchors["endpoint"] = endpoint

    model_payload: Dict[str, Any] = {
        "service_id": service_id,
        "endpoint": endpoint,
        "method": _as_str(payload, ("method", "http_method")),
        "req_rate": _as_float(payload, ("req_rate", "request_rate", "rps")),
        "error_rate": _as_float(payload, ("error_rate", "errors_ratio")),
        "unique_ips_count": _as_int(payload, ("unique_ips_count", "uniq_ip_count")),
        "avg_latency_ms": _as_float(payload, ("avg_latency_ms", "latency_ms")),
        "user_agent_entropy": _as_float(payload, ("user_agent_entropy",)),
        "asn_concentration": _as_float(payload, ("asn_concentration",)),
        "endpoint_convergence": _as_float(payload, ("endpoint_convergence",)),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="DDOS_SIGNAL_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_telco_sim_swap(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "event_time"))
    phone = _as_str(payload, ("phone", "msisdn"), required=True)

    model_payload: Dict[str, Any] = {
        "phone": phone,
        "prev_sim_id": _as_str(payload, ("prev_sim_id", "old_sim_id")),
        "new_sim_id": _as_str(payload, ("new_sim_id", "sim_id")),
        "reason": _as_str(payload, ("reason", "change_reason")),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    anchors = {"phone_h": pseudonymize(phone, salt="integration-prehash")}

    return CanonicalEvent(
        event_type="SIM_SWAP_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_local_network_probe(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "sampled_at", "ts"))
    hostname = _as_str(payload, ("hostname", "host", "node")) or "localhost"
    interface = _as_str(payload, ("interface", "iface", "interface_name", "nic"), required=True)
    service_id = _as_str(payload, ("service_id",)) or f"local-network:{hostname}:{interface}"
    gateway = _as_str(payload, ("gateway", "default_gateway"))
    dns_servers = _as_str_list(payload, ("dns_servers", "nameservers"))
    link_up = _as_bool(payload, ("link_up", "interface_up"))

    status_raw = _as_str(payload, ("status", "health_status"))
    if status_raw:
        status = _normalize_service_status(status_raw)
    elif link_up is False:
        status = "down"
    elif not gateway or not dns_servers:
        status = "degraded"
    else:
        status = "up"

    ip = _as_str(payload, ("ip", "interface_ip", "local_ip"))
    device_id = _as_str(payload, ("device_id", "host_id", "machine_id"))

    anchors: Dict[str, str] = {"service_id": service_id}
    if ip:
        anchors["ip"] = ip
    if device_id:
        anchors["device_id"] = device_id

    model_payload: Dict[str, Any] = {
        "service_id": service_id,
        "status": status,
        "hostname": hostname,
        "interface": interface,
        "interface_alias": _as_str(payload, ("interface_alias", "description")),
        "link_up": link_up,
        "mac": _as_str(payload, ("mac", "mac_address")),
        "ip": ip,
        "gateway": gateway,
        "gateway_iface": _as_str(payload, ("gateway_iface",)),
        "dns_servers": dns_servers or None,
        "dns_server_count": _as_int(payload, ("dns_server_count",)) or (len(dns_servers) if dns_servers else None),
        "dns_udp_sockets_v4": _as_int(payload, ("dns_udp_sockets_v4", "dns_udp_sockets")),
        "dns_udp_sockets_v6": _as_int(payload, ("dns_udp_sockets_v6",)),
        "rx_bytes": _as_int(payload, ("rx_bytes", "bytes_in")),
        "tx_bytes": _as_int(payload, ("tx_bytes", "bytes_out")),
        "rx_packets": _as_int(payload, ("rx_packets", "packets_in")),
        "tx_packets": _as_int(payload, ("tx_packets", "packets_out")),
        "rx_errors": _as_int(payload, ("rx_errors",)),
        "tx_errors": _as_int(payload, ("tx_errors",)),
        "rx_drop": _as_int(payload, ("rx_drop", "rx_dropped")),
        "tx_drop": _as_int(payload, ("tx_drop", "tx_dropped")),
        "rx_bps": _as_float(payload, ("rx_bps",)),
        "tx_bps": _as_float(payload, ("tx_bps",)),
        "rx_pps": _as_float(payload, ("rx_pps",)),
        "tx_pps": _as_float(payload, ("tx_pps",)),
        "latency_ms": _as_float(payload, ("latency_ms",)),
        "error_rate": _as_float(payload, ("error_rate",)),
        "sample_interval_seconds": _as_float(payload, ("sample_interval_seconds", "interval_seconds")),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="SERVICE_HEALTH_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_pgaudit_event(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "log_time", "ts"))
    db_instance = _as_str(payload, ("db_instance", "service_id", "db_host", "instance"), required=True)
    statement_type = (_as_str(payload, ("statement_type", "command", "class"), required=True) or "").upper()
    object_name = _as_str(payload, ("object_name", "relation", "table", "object"))
    raw_query = _as_str(payload, ("query", "statement", "sql"))

    reason_codes: List[str] = []
    if statement_type in {"COPY", "ALTER SYSTEM", "DROP", "TRUNCATE", "GRANT", "REVOKE"}:
        reason_codes.append("high_impact_db_statement")
    if _as_bool(payload, ("audit_setting_changed", "audit_tamper")):
        reason_codes.append("audit_config_changed")
    if _as_bool(payload, ("backup_deleted", "backup_rotation_disabled")):
        reason_codes.append("backup_control_modified")

    query_fingerprint = _as_str(payload, ("query_fingerprint",))
    if not query_fingerprint and raw_query:
        # Deterministic fingerprint to avoid storing full SQL text in downstream systems.
        query_fingerprint = pseudonymize(raw_query, salt="pgaudit-fingerprint")

    anchors: Dict[str, str] = {"service_id": db_instance}
    if object_name:
        anchors["endpoint"] = object_name

    model_payload: Dict[str, Any] = {
        "source": "pgaudit",
        "db_instance": db_instance,
        "db_name": _as_str(payload, ("db_name", "database")),
        "db_user": _as_str(payload, ("db_user", "user", "role")),
        "statement_type": statement_type,
        "object_name": object_name,
        "operation": _as_str(payload, ("operation", "action")),
        "row_count": _as_int(payload, ("rows", "row_count", "affected_rows")),
        "success": bool(_as_bool(payload, ("success", "allowed", "result_ok")) is not False),
        "session_id": _as_str(payload, ("session_id", "pid", "connection_id")),
        "query_fingerprint": query_fingerprint,
        "client_ip": _as_str(payload, ("client_ip", "src_ip", "ip")),
        "reason_codes": sorted(set(reason_codes)),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="DB_AUDIT_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_wazuh_fim(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "agent_time", "syscheck_ts"))
    host = _as_str(payload, ("host", "hostname", "agent_name", "agent"), required=True)
    file_path = _as_str(payload, ("file_path", "path", "file"), required=True)
    action = _normalize_fim_action(_as_str(payload, ("action", "event_type", "syscheck_event")))

    reason_codes: List[str] = []
    is_critical_path = bool(_as_bool(payload, ("is_critical_path", "critical_path", "critical")) is True)
    if is_critical_path:
        reason_codes.append("critical_path_mutation")
    if action == "deleted":
        reason_codes.append("file_deleted")
    if _as_bool(payload, ("permission_escalation", "chmod_777", "suid_added")):
        reason_codes.append("permission_escalation_signal")

    anchors: Dict[str, str] = {
        "service_id": f"host:{host}",
        "device_id": host,
        "endpoint": file_path,
    }
    agent_id = _as_str(payload, ("agent_id",))
    if agent_id:
        anchors["agent_id"] = agent_id

    model_payload: Dict[str, Any] = {
        "source": "wazuh",
        "host": host,
        "agent_id": agent_id,
        "file_path": file_path,
        "action": action,
        "hash_before": _as_str(payload, ("hash_before", "old_sha256", "sha256_before", "md5_before")),
        "hash_after": _as_str(payload, ("hash_after", "sha256_after", "new_sha256", "md5_after")),
        "user": _as_str(payload, ("user", "actor", "username")),
        "process": _as_str(payload, ("process", "process_name")),
        "severity": _normalize_severity(_as_str(payload, ("severity", "rule_level")), default="medium"),
        "rule_id": _as_str(payload, ("rule_id", "sid")),
        "client_ip": _as_str(payload, ("client_ip", "src_ip", "ip")),
        "is_critical_path": is_critical_path,
        "reason_codes": sorted(set(reason_codes)),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="FILE_INTEGRITY_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_velociraptor_artifact(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "collected_at"))
    host = _as_str(payload, ("host", "hostname", "client_id", "endpoint"), required=True)
    artifact_name = _as_str(payload, ("artifact_name", "artifact", "vql_artifact"), required=True)
    finding_type = _as_str(payload, ("finding_type", "category", "event_type"), required=True)

    reason_codes: List[str] = []
    severity = _normalize_severity(_as_str(payload, ("severity", "level")), default="medium")
    if severity in {"critical", "high"}:
        reason_codes.append("high_severity_dfir_finding")
    if _as_bool(payload, ("credential_access", "lsass_access")):
        reason_codes.append("credential_access_signal")
    if _as_bool(payload, ("log_tamper", "eventlog_cleared")):
        reason_codes.append("log_tamper_signal")

    file_path = _as_str(payload, ("file_path", "path"))
    anchors: Dict[str, str] = {
        "service_id": f"endpoint:{host}",
        "device_id": host,
    }
    if file_path:
        anchors["endpoint"] = file_path

    model_payload: Dict[str, Any] = {
        "source": "velociraptor",
        "host": host,
        "artifact_name": artifact_name,
        "finding_type": finding_type,
        "severity": severity,
        "status": _as_str(payload, ("status", "state")),
        "user": _as_str(payload, ("user", "username", "actor")),
        "process_name": _as_str(payload, ("process_name", "process")),
        "process_pid": _as_int(payload, ("process_pid", "pid")),
        "file_path": file_path,
        "sha256": _as_str(payload, ("sha256", "hash")),
        "command_line": _as_str(payload, ("command_line", "cmdline")),
        "client_ip": _as_str(payload, ("client_ip", "src_ip", "ip")),
        "case_id": _as_str(payload, ("case_id",)),
        "hunt_id": _as_str(payload, ("hunt_id", "flow_id")),
        "reason_codes": sorted(set(reason_codes)),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="DFIR_FINDING_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_feodo_c2(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(
        payload,
        ("timestamp", "first_seen_utc", "first_seen", "first_seen_at", "last_online", "date_added"),
    )
    ip = _as_str(payload, ("ip_address", "ip", "host"), required=True)
    malware = _as_str(payload, ("malware", "malware_family", "family"))
    status = _as_str(payload, ("status", "online_status", "host_status")) or "online"
    port = _as_int(payload, ("port", "dst_port", "c2_port"))
    host = _as_str(payload, ("host", "hostname")) or ip

    reason_codes = ["botnet_c2_indicator", "osint_feed", "feed:feodo"]
    if str(status).strip().lower() in {"online", "active"}:
        reason_codes.append("ioc_online")
    if malware:
        reason_codes.append(f"malware_family:{malware.strip().lower()}")

    model_payload: Dict[str, Any] = {
        "source": "feodo_tracker",
        "host": host,
        "artifact_name": "feodo_tracker",
        "finding_type": "botnet_c2_indicator",
        "severity": _normalize_ioc_severity(status, default="high"),
        "status": status,
        "client_ip": ip,
        "command_line": f"c2_port={port}" if port is not None else None,
        "hunt_id": _as_str(payload, ("id", "ioc_id", "feodo_id")),
        "case_id": _as_str(payload, ("reporter", "reporter_name")),
        "reason_codes": sorted(set(reason_codes)),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="DFIR_FINDING_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors={"ip": ip},
        classification=classification,
    )


def _map_urlhaus_ioc(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(
        payload,
        ("timestamp", "date_added", "dateadded", "first_seen", "urlhaus_reference_date"),
    )
    url = _as_str(payload, ("url", "indicator", "ioc"), required=True)
    domain = (
        _as_str(payload, ("host", "domain", "hostname", "urlhost"))
        or _extract_domain_from_url(url)
    )
    ip = _as_str(payload, ("host_ip", "ip_address", "ip"))
    threat = _as_str(payload, ("threat", "threat_type", "classification")) or "malware_url"
    status = _as_str(payload, ("url_status", "status")) or "online"
    tags = _as_str_list(payload, ("tags", "tag"))

    reason_codes = ["malware_url_indicator", "osint_feed", "feed:urlhaus"]
    if status:
        reason_codes.append(f"url_status:{status.strip().lower()}")
    for tag in tags[:5]:
        reason_codes.append(f"tag:{tag.strip().lower()}")

    anchors: Dict[str, str] = {"url": url}
    if domain:
        anchors["domain"] = domain
    if ip:
        anchors["ip"] = ip

    model_payload: Dict[str, Any] = {
        "source": "urlhaus",
        "host": domain or ip or url,
        "artifact_name": "urlhaus",
        "finding_type": threat,
        "severity": _normalize_ioc_severity(status, default="high"),
        "status": status,
        "client_ip": ip,
        "file_path": url,
        "case_id": _as_str(payload, ("reporter", "reporter_name")),
        "hunt_id": _as_str(payload, ("id", "urlhaus_id")),
        "reason_codes": sorted(set(reason_codes)),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="DFIR_FINDING_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_otx_indicator(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(
        payload,
        ("timestamp", "first_seen", "modified", "created", "pulse_created"),
    )
    indicator = _as_str(payload, ("indicator", "value", "ioc"), required=True)
    indicator_type = (_as_str(payload, ("indicator_type", "type", "ioc_type")) or "").strip().lower()
    pulse_name = _as_str(payload, ("pulse_name", "pulse", "artifact_name")) or "alienvault_otx"
    status = _as_str(payload, ("status", "activity")) or "active"
    tags = _as_str_list(payload, ("tags", "labels"))

    anchors: Dict[str, str] = {}
    host = indicator
    if indicator_type in {"ipv4", "ipv4-addr", "ip", "ipv6", "ipv6-addr"}:
        anchors["ip"] = indicator
    elif indicator_type in {"domain", "hostname"}:
        anchors["domain"] = indicator.lower()
        host = indicator.lower()
    elif indicator_type == "url":
        anchors["url"] = indicator
        domain = _extract_domain_from_url(indicator)
        if domain:
            anchors["domain"] = domain
            host = domain
    else:
        raise ValueError(f"unsupported otx indicator_type '{indicator_type}'")

    reason_codes = ["otx_indicator", "osint_feed", "feed:otx"]
    for tag in tags[:5]:
        reason_codes.append(f"tag:{tag.strip().lower()}")

    model_payload: Dict[str, Any] = {
        "source": "alienvault_otx",
        "host": host,
        "artifact_name": pulse_name,
        "finding_type": f"otx_{indicator_type or 'indicator'}",
        "severity": _normalize_ioc_severity(_as_str(payload, ("severity", "priority")), default="high"),
        "status": status,
        "file_path": indicator if indicator_type == "url" else None,
        "client_ip": indicator if "ip" in anchors else None,
        "case_id": _as_str(payload, ("pulse_id", "id")),
        "hunt_id": _as_str(payload, ("indicator_id",)),
        "reason_codes": sorted(set(reason_codes)),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="DFIR_FINDING_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_m365_bec_mail(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "received_at"))
    sender = _as_str(payload, ("sender", "from", "from_address"), required=True)
    recipient = _as_str(payload, ("recipient", "to", "target_user"))
    subject = _as_str(payload, ("subject",))
    domain = _as_str(payload, ("domain", "sender_domain"))
    url = _as_str(payload, ("url", "link"))
    msg_id = _as_str(payload, ("message_id", "internet_message_id"))
    risk = _normalize_severity(_as_str(payload, ("severity", "risk_level")), default="high")

    anchors: Dict[str, str] = {}
    if domain:
        anchors["domain"] = domain
    if url:
        anchors["url"] = url
    recipient_h = pseudonymize(recipient, salt="integration-prehash") if recipient else None
    if recipient_h:
        anchors["person_h"] = recipient_h
    if not anchors:
        anchors["service_id"] = "mail:m365"

    model_payload: Dict[str, Any] = {
        "channel": "email",
        "sender": sender,
        "recipient": recipient,
        "subject": subject,
        "domain": domain,
        "url": url,
        "message_id": msg_id,
        "threat_class": "bec",
        "severity": risk,
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="PHISHING_MESSAGE_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_waf_api_attack(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "window_end"))
    service_id = _as_str(payload, ("service_id", "app", "application"), required=True)
    endpoint = _as_str(payload, ("endpoint", "path", "uri"))
    attack_type = _as_str(payload, ("attack_type", "rule_family", "signature"), required=True)
    status = _normalize_web_attack_status(_as_str(payload, ("status", "action", "decision")))
    ip = _as_str(payload, ("ip", "src_ip", "client_ip"))
    req_count = _as_int(payload, ("request_count", "req_count", "count"))

    reason_codes = [f"web_attack:{attack_type.lower()}"]
    if status == "allowed":
        reason_codes.append("waf_bypass_signal")

    anchors: Dict[str, str] = {"service_id": service_id}
    if endpoint:
        anchors["endpoint"] = endpoint
    if ip:
        anchors["ip"] = ip

    model_payload: Dict[str, Any] = {
        "source": "waf",
        "service_id": service_id,
        "endpoint": endpoint,
        "method": _as_str(payload, ("method", "http_method")),
        "attack_type": attack_type,
        "status": status,
        "req_count": req_count,
        "src_ip": ip,
        "user_agent": _as_str(payload, ("user_agent", "ua")),
        "reason_codes": reason_codes,
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="WEB_ATTACK_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_kev_vuln(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "published_at"))
    cve_id = (_as_str(payload, ("cve_id", "cve"), required=True) or "").upper()
    asset_id = _as_str(payload, ("asset_id", "service_id", "hostname"), required=True)
    severity = _normalize_severity(_as_str(payload, ("severity", "cvss_severity")), default="high")
    epss = _as_float(payload, ("epss",))
    kev = bool(_as_bool(payload, ("kev", "known_exploited", "known_exploited_vuln")) is True)
    patch_due = _as_str(payload, ("patch_due_date", "due_date", "cisa_due_date"))

    anchors: Dict[str, str] = {"service_id": asset_id, "endpoint": cve_id}
    model_payload: Dict[str, Any] = {
        "source": "kev",
        "asset_id": asset_id,
        "cve_id": cve_id,
        "severity": severity,
        "kev": kev,
        "epss": epss,
        "patch_due_date": patch_due,
        "status": _as_str(payload, ("status", "patch_status")) or "open",
        "reason_codes": ["known_exploited_vuln"] if kev else ["vulnerability_detected"],
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="VULNERABILITY_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


def _map_backup_attestation(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "attested_at"))
    asset_id = _as_str(payload, ("asset_id", "service_id", "hostname"), required=True)
    backup_id = _as_str(payload, ("backup_id", "snapshot_id"), required=True)
    immutable = bool(_as_bool(payload, ("immutable", "object_lock_enabled")) is True)
    object_lock_until = _as_str(payload, ("object_lock_until", "retention_until"))

    anchors: Dict[str, str] = {"service_id": asset_id, "endpoint": backup_id}
    model_payload: Dict[str, Any] = {
        "source": "backup_system",
        "asset_id": asset_id,
        "backup_id": backup_id,
        "immutable": immutable,
        "object_lock_until": object_lock_until,
        "backup_hash": _as_str(payload, ("backup_hash", "hash", "sha256")),
        "storage_tier": _as_str(payload, ("storage_tier", "tier")),
        "status": _as_str(payload, ("status",)) or ("ok" if immutable else "risk"),
        "rpo_hours": _as_float(payload, ("rpo_hours",)),
    }
    model_payload = {k: v for k, v in model_payload.items() if v is not None}

    return CanonicalEvent(
        event_type="BACKUP_ATTESTATION_EVENT",
        occurred_at=occurred_at,
        confidence=_coerce_confidence(confidence),
        payload=model_payload,
        anchors=anchors,
        classification=classification,
    )


_CONNECTORS: Dict[str, ConnectorDefinition] = {
    "splunk_login_v1": ConnectorDefinition(
        key="splunk_login_v1",
        description="Splunk login/auth events to LOGIN_EVENT",
        required_fields=("timestamp", "result|status|outcome", "ip|src_ip|device_id"),
        mapper=_map_splunk_login,
    ),
    "core_banking_tx_v1": ConnectorDefinition(
        key="core_banking_tx_v1",
        description="Core banking transaction logs to TRANSACTION_EVENT",
        required_fields=("timestamp", "amount", "account_from|from_account OR account_to|to_account"),
        mapper=_map_core_banking_tx,
    ),
    "cloudflare_ddos_v1": ConnectorDefinition(
        key="cloudflare_ddos_v1",
        description="Cloudflare or edge telemetry to DDOS_SIGNAL_EVENT",
        required_fields=("timestamp", "service_id|zone_id"),
        mapper=_map_cloudflare_ddos,
    ),
    "telco_sim_swap_v1": ConnectorDefinition(
        key="telco_sim_swap_v1",
        description="Telco SIM-change feeds to SIM_SWAP_EVENT",
        required_fields=("timestamp", "phone|msisdn"),
        mapper=_map_telco_sim_swap,
    ),
    "local_network_probe_v1": ConnectorDefinition(
        key="local_network_probe_v1",
        description="Local passive network probe to SERVICE_HEALTH_EVENT",
        required_fields=("timestamp", "interface|iface", "gateway|default_gateway", "dns_servers"),
        mapper=_map_local_network_probe,
    ),
    "pgaudit_event_v1": ConnectorDefinition(
        key="pgaudit_event_v1",
        description="PostgreSQL pgAudit log records to DB_AUDIT_EVENT",
        required_fields=("timestamp", "db_instance|service_id|db_host", "statement_type|command|class"),
        mapper=_map_pgaudit_event,
    ),
    "wazuh_fim_v1": ConnectorDefinition(
        key="wazuh_fim_v1",
        description="Wazuh file integrity monitoring records to FILE_INTEGRITY_EVENT",
        required_fields=("timestamp", "host|hostname|agent_name", "file_path|path", "action|event_type"),
        mapper=_map_wazuh_fim,
    ),
    "feodo_c2_v1": ConnectorDefinition(
        key="feodo_c2_v1",
        description="Feodo Tracker botnet C2 IP feed to DFIR_FINDING_EVENT",
        required_fields=("ip_address|ip|host",),
        mapper=_map_feodo_c2,
    ),
    "urlhaus_ioc_v1": ConnectorDefinition(
        key="urlhaus_ioc_v1",
        description="URLhaus malware URL intelligence to DFIR_FINDING_EVENT",
        required_fields=("url",),
        mapper=_map_urlhaus_ioc,
    ),
    "otx_indicator_v1": ConnectorDefinition(
        key="otx_indicator_v1",
        description="AlienVault OTX indicators to DFIR_FINDING_EVENT",
        required_fields=("indicator|value", "indicator_type|type"),
        mapper=_map_otx_indicator,
    ),
    "velociraptor_artifact_v1": ConnectorDefinition(
        key="velociraptor_artifact_v1",
        description="Velociraptor artifact findings to DFIR_FINDING_EVENT",
        required_fields=("timestamp", "host|hostname|client_id", "artifact_name|artifact", "finding_type|category"),
        mapper=_map_velociraptor_artifact,
    ),
    "m365_bec_mail_v1": ConnectorDefinition(
        key="m365_bec_mail_v1",
        description="Microsoft 365 mail telemetry to PHISHING_MESSAGE_EVENT (BEC-focused)",
        required_fields=("timestamp", "sender|from", "recipient|to"),
        mapper=_map_m365_bec_mail,
    ),
    "waf_api_attack_v1": ConnectorDefinition(
        key="waf_api_attack_v1",
        description="WAF/API gateway attack telemetry to WEB_ATTACK_EVENT",
        required_fields=("timestamp", "service_id|app", "attack_type|rule_family"),
        mapper=_map_waf_api_attack,
    ),
    "kev_vuln_feed_v1": ConnectorDefinition(
        key="kev_vuln_feed_v1",
        description="KEV/CVE feed rows to VULNERABILITY_EVENT",
        required_fields=("published_at|timestamp", "cve_id|cve", "asset_id|service_id"),
        mapper=_map_kev_vuln,
    ),
    "backup_attestation_v1": ConnectorDefinition(
        key="backup_attestation_v1",
        description="Backup/immutable storage attestations to BACKUP_ATTESTATION_EVENT",
        required_fields=("attested_at|timestamp", "asset_id|service_id", "backup_id|snapshot_id"),
        mapper=_map_backup_attestation,
    ),
}


def list_connectors() -> List[Dict[str, Any]]:
    return [
        {
            "key": c.key,
            "description": c.description,
            "required_fields": list(c.required_fields),
        }
        for c in _CONNECTORS.values()
    ]


def map_external_event(
    *,
    connector_key: str,
    payload: Dict[str, Any],
    confidence: float = 0.7,
    classification: Optional[str] = None,
) -> CanonicalEvent:
    connector = _CONNECTORS.get(connector_key)
    if connector is None:
        available = ", ".join(sorted(_CONNECTORS.keys()))
        raise ValueError(f"unknown connector '{connector_key}'. available: {available}")
    return connector.mapper(payload, confidence, classification)
