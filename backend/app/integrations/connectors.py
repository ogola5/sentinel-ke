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


def _normalize_numeric_severity(raw: Any, *, default: str = "medium") -> str:
    if raw is None:
        return default
    if isinstance(raw, (int, float)):
        value = int(raw)
    else:
        s = str(raw).strip()
        if not s:
            return default
        if s.isdigit():
            value = int(s)
        else:
            return _normalize_severity(s, default=default)
    if value <= 1:
        return "critical"
    if value == 2:
        return "high"
    if value == 3:
        return "medium"
    return "low"


def _suricata_status_from_action(action: Optional[str]) -> str:
    if not action:
        return "detected"
    x = action.strip().lower()
    if x in {"allowed", "allow", "pass", "alert"}:
        return "allowed"
    if x in {"blocked", "drop", "reject", "denied"}:
        return "blocked"
    return "detected"


def _suricata_signal_family(signature: Optional[str], category: Optional[str], app_proto: Optional[str]) -> str:
    haystack = " ".join(
        part.strip().lower()
        for part in (signature or "", category or "", app_proto or "")
        if str(part).strip()
    )
    ddos_terms = (
        "denial of service",
        "ddos",
        "syn flood",
        "udp flood",
        "icmp flood",
        "http flood",
        "flood",
    )
    if any(term in haystack for term in ddos_terms):
        return "ddos"
    web_terms = (
        "web",
        "http",
        "sql injection",
        "xss",
        "command injection",
        "path traversal",
        "directory traversal",
        "lfi",
        "rfi",
    )
    if (app_proto or "").strip().lower() in {"http", "http2", "h2"}:
        return "web"
    if any(term in haystack for term in web_terms):
        return "web"
    return "dfir"


def _suricata_attack_type(signature: Optional[str], category: Optional[str]) -> str:
    haystack = " ".join(part.strip().lower() for part in (signature or "", category or "") if str(part).strip())
    for needle, label in (
        ("sql injection", "sql_injection"),
        ("xss", "xss"),
        ("cross site scripting", "xss"),
        ("command injection", "command_injection"),
        ("path traversal", "path_traversal"),
        ("directory traversal", "path_traversal"),
        ("lfi", "local_file_inclusion"),
        ("rfi", "remote_file_inclusion"),
        ("csrf", "csrf"),
    ):
        if needle in haystack:
            return label
    return category or signature or "suricata_alert"


def _map_suricata_eve(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "flow.end", "flow.start"))
    src_ip = _as_str(payload, ("src_ip", "src"))
    dest_ip = _as_str(payload, ("dest_ip", "dst"))
    if not src_ip and not dest_ip:
        raise ValueError("suricata_eve_v1 requires src_ip/src or dest_ip/dst")

    alert = payload.get("alert") if isinstance(payload.get("alert"), dict) else {}
    http = payload.get("http") if isinstance(payload.get("http"), dict) else {}
    flow = payload.get("flow") if isinstance(payload.get("flow"), dict) else {}

    signature = _as_str(alert, ("signature", "signature_id")) or _as_str(payload, ("signature", "signature_id"))
    category = _as_str(alert, ("category",)) or _as_str(payload, ("category", "alert_category"))
    severity = _normalize_numeric_severity(
        _first_value(alert, ("severity",)) if alert else _first_value(payload, ("severity",)),
        default="high",
    )
    action = _suricata_status_from_action(
        _as_str(alert, ("action",)) or _as_str(payload, ("action", "verdict", "decision"))
    )
    app_proto = _as_str(payload, ("app_proto", "application_protocol", "service"))
    proto = _as_str(payload, ("proto", "ip_proto"))
    dest_port = _as_int(payload, ("dest_port", "dst_port", "port"))
    service_id = (
        _as_str(payload, ("service_id", "application"))
        or _as_str(http, ("hostname", "host"))
        or dest_ip
    )
    endpoint = _as_str(http, ("url", "uri")) or _as_str(payload, ("endpoint", "path", "uri"))
    domain = _as_str(http, ("hostname", "host", "domain"))
    user_agent = _as_str(http, ("http_user_agent", "user_agent"))
    method = _as_str(http, ("http_method", "method"))
    pkts_toserver = _as_int(flow, ("pkts_toserver", "packets_toserver"))
    bytes_toserver = _as_int(flow, ("bytes_toserver",))
    flow_id = _as_str(payload, ("flow_id",))
    family = _suricata_signal_family(signature, category, app_proto)

    reason_codes = ["suricata_alert", f"suricata_family:{family}"]
    if category:
        reason_codes.append(f"suricata_category:{category.strip().lower().replace(' ', '_')}")
    if signature:
        signature_code = str(signature).strip().lower().replace(" ", "_")
        reason_codes.append(f"suricata_signature:{signature_code[:80]}")
    if action == "allowed":
        reason_codes.append("suricata_alert_allowed")

    anchors: Dict[str, str] = {}
    if src_ip:
        anchors["ip"] = src_ip
    if service_id:
        anchors["service_id"] = service_id
    if endpoint:
        anchors["endpoint"] = endpoint
    if domain:
        anchors["domain"] = domain.lower()

    if family == "ddos":
        model_payload: Dict[str, Any] = {
            "source": "suricata",
            "service_id": service_id,
            "endpoint": endpoint,
            "method": method,
            "req_rate": pkts_toserver,
            "packet_burst": pkts_toserver,
            "bytes_toserver": bytes_toserver,
            "attack_type": signature or category or "suricata_ddos_alert",
            "status": action,
            "src_ip": src_ip,
            "dest_ip": dest_ip,
            "dest_port": dest_port,
            "proto": proto,
            "app_proto": app_proto,
            "severity": severity,
            "flow_id": flow_id,
            "reason_codes": sorted(set(reason_codes)),
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

    if family == "web":
        model_payload = {
            "source": "suricata",
            "service_id": service_id,
            "endpoint": endpoint,
            "method": method,
            "attack_type": _suricata_attack_type(signature, category),
            "status": action,
            "req_count": pkts_toserver,
            "src_ip": src_ip,
            "dest_ip": dest_ip,
            "dest_port": dest_port,
            "proto": proto,
            "app_proto": app_proto,
            "user_agent": user_agent,
            "signature": signature,
            "severity": severity,
            "reason_codes": sorted(set(reason_codes)),
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

    host = service_id or dest_ip or src_ip
    model_payload = {
        "source": "suricata",
        "host": host,
        "artifact_name": signature or "suricata_alert",
        "finding_type": category or "suricata_alert",
        "severity": severity,
        "status": action,
        "client_ip": src_ip,
        "command_line": f"{proto or 'ip'}:{dest_port}" if dest_port is not None else proto,
        "file_path": endpoint,
        "hunt_id": flow_id,
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


def _zeek_notice_severity(note: Optional[str], msg: Optional[str]) -> str:
    haystack = " ".join(part.strip().lower() for part in (note or "", msg or "") if str(part).strip())
    critical_terms = ("ransomware", "malware", "exploit", "credential", "bruteforce", "password guessing")
    medium_terms = ("scan", "port_scan", "weird", "certificate", "invalid", "dns")
    if any(term in haystack for term in critical_terms):
        return "high"
    if any(term in haystack for term in medium_terms):
        return "medium"
    return "medium"


def _crowdsec_alert_severity(scenario: Optional[str], decisions: list[str]) -> str:
    haystack = " ".join([scenario or "", *decisions]).strip().lower()
    if any(term in haystack for term in ("http-ddos", "ddos", "ransomware", "credential", "bruteforce")):
        return "high"
    if any(term in haystack for term in ("scan", "probe", "crawler", "bot")):
        return "medium"
    return "medium"


def _falco_priority_to_severity(priority: Optional[str]) -> str:
    x = (priority or "").strip().lower()
    if x in {"emergency", "alert", "critical"}:
        return "critical"
    if x in {"error", "err", "warning", "warn"}:
        return "high"
    if x in {"notice", "informational", "info"}:
        return "medium"
    if x in {"debug"}:
        return "low"
    return _normalize_severity(priority, default="medium")


def _map_zeek_notice(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "ts", "time", "occurred_at"))
    note = _as_str(payload, ("note", "notice_type", "notice"), required=True)
    msg = _as_str(payload, ("msg", "message", "notice_msg"))
    src_ip = _as_str(payload, ("src", "src_ip", "id.orig_h", "orig_h"))
    dest_ip = _as_str(payload, ("dst", "dest_ip", "id.resp_h", "resp_h"))
    service_id = _as_str(payload, ("service_id", "host", "hostname", "dest_host")) or dest_ip
    dest_port = _as_int(payload, ("p", "dest_port", "id.resp_p", "resp_p"))
    proto = _as_str(payload, ("proto", "transport"))
    sub = _as_str(payload, ("sub", "sub_message"))
    peer = _as_str(payload, ("peer_descr", "sensor", "zeek_node"))
    uid = _as_str(payload, ("uid", "conn_uid"))

    reason_codes = ["zeek_notice"]
    note_code = note.strip().lower().replace("::", "_").replace(" ", "_")
    reason_codes.append(f"zeek_note:{note_code}")
    if "password_guess" in note_code:
        reason_codes.append("credential_attack_signal")
    if "port_scan" in note_code or "scan" in note_code:
        reason_codes.append("network_scan_signal")

    anchors: Dict[str, str] = {}
    if src_ip:
        anchors["ip"] = src_ip
    if service_id:
        anchors["service_id"] = service_id

    model_payload = {
        "source": "zeek",
        "host": service_id or src_ip,
        "artifact_name": note,
        "finding_type": sub or note,
        "severity": _normalize_severity(_as_str(payload, ("severity",)), default=_zeek_notice_severity(note, msg)),
        "status": _as_str(payload, ("status", "action")) or "noticed",
        "client_ip": src_ip,
        "command_line": f"{proto or 'ip'}:{dest_port}" if dest_port is not None else proto,
        "hunt_id": uid,
        "case_id": peer,
        "reason_codes": sorted(set(reason_codes)),
        "message": msg,
        "dest_ip": dest_ip,
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


def _map_crowdsec_alert(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "created_at", "start_at"))
    scenario = _as_str(payload, ("scenario", "alert_name", "name"), required=True)
    scope = (_as_str(payload, ("scope", "scope_type")) or "").strip().lower()
    value = _as_str(payload, ("value", "scope_value", "src_ip", "ip", "domain"))
    src_ip = _as_str(payload, ("src_ip", "ip", "source_ip"))
    service_id = _as_str(payload, ("service_id", "service", "host", "hostname"))
    remediation = _as_bool(payload, ("remediation", "has_remediation"))
    decisions = _as_str_list(payload, ("decisions", "decision_type", "remediation_actions"))
    country = _as_str(payload, ("country", "source_country"))
    as_name = _as_str(payload, ("as_name", "asn_name"))
    as_num = _as_int(payload, ("asn", "as_num"))
    events_count = _as_int(payload, ("events_count", "count", "occurrences"))
    simulation = _as_bool(payload, ("simulation", "simulated"))

    anchors: Dict[str, str] = {}
    if scope == "ip" and value:
        anchors["ip"] = value
    elif scope == "domain" and value:
        anchors["domain"] = value.lower()
    elif src_ip:
        anchors["ip"] = src_ip
    if service_id:
        anchors["service_id"] = service_id
    if not anchors and value:
        anchors["endpoint"] = value
    if not anchors:
        raise ValueError("crowdsec_alert_v1 requires scope/value, src_ip, or service_id")

    reason_codes = ["crowdsec_alert", f"crowdsec_scenario:{scenario.strip().lower().replace('/', '_')}"]
    if scope:
        reason_codes.append(f"crowdsec_scope:{scope}")
    for decision in decisions[:5]:
        reason_codes.append(f"crowdsec_decision:{decision.strip().lower()}")
    if remediation is True:
        reason_codes.append("remediation_available")

    model_payload = {
        "source": "crowdsec",
        "host": service_id or src_ip or value,
        "artifact_name": scenario,
        "finding_type": scope or "crowdsec_alert",
        "severity": _normalize_severity(
            _as_str(payload, ("severity", "risk")), default=_crowdsec_alert_severity(scenario, decisions)
        ),
        "status": _as_str(payload, ("status", "state")) or ("active" if remediation else "noticed"),
        "client_ip": src_ip or (value if scope == "ip" else None),
        "file_path": value if scope in {"path", "uri"} else None,
        "hunt_id": _as_str(payload, ("id", "alert_id")),
        "case_id": _as_str(payload, ("origin", "origin_name", "source")),
        "reason_codes": sorted(set(reason_codes)),
        "message": _as_str(payload, ("message", "description")),
        "country": country,
        "as_name": as_name,
        "asn": as_num,
        "events_count": events_count,
        "simulation": simulation,
        "decisions": decisions or None,
        "scope": scope or None,
        "value": value,
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


def _map_falco_runtime(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "evt.time", "output_time"))
    rule = _as_str(payload, ("rule", "alert", "alert_name"), required=True)
    priority = _as_str(payload, ("priority", "severity", "level"))
    output = _as_str(payload, ("output", "message", "description"))
    host = _as_str(payload, ("hostname", "host", "node"))
    output_fields = payload.get("output_fields") if isinstance(payload.get("output_fields"), dict) else {}

    container_id = _as_str(payload, ("container_id",)) or _as_str(output_fields, ("container.id", "container_id"))
    container_name = _as_str(payload, ("container_name",)) or _as_str(output_fields, ("container.name", "container_name"))
    pod_name = _as_str(payload, ("pod_name",)) or _as_str(output_fields, ("k8s.pod.name", "pod_name"))
    namespace = _as_str(payload, ("namespace",)) or _as_str(output_fields, ("k8s.ns.name", "k8s.namespace.name"))
    process_name = _as_str(payload, ("process_name", "proc_name")) or _as_str(output_fields, ("proc.name", "proc_name"))
    command_line = _as_str(payload, ("command_line", "cmdline")) or _as_str(output_fields, ("proc.cmdline", "proc.cmdline_truncated"))
    user = _as_str(payload, ("user", "username")) or _as_str(output_fields, ("user.name", "user_name"))
    file_path = _as_str(payload, ("file_path", "path")) or _as_str(output_fields, ("fd.name", "file.path"))
    src_ip = _as_str(payload, ("src_ip", "client_ip")) or _as_str(output_fields, ("fd.sip", "net.sip"))
    tags = _as_str_list(payload, ("tags",))
    if not tags and isinstance(output_fields.get("tags"), (list, tuple, set)):
        tags = [str(v).strip() for v in output_fields.get("tags", []) if str(v).strip()]

    service_id = pod_name or container_name or container_id or (f"host:{host}" if host else None)
    anchors: Dict[str, str] = {}
    if service_id:
        anchors["service_id"] = service_id
    if host:
        anchors["device_id"] = host
    if src_ip:
        anchors["ip"] = src_ip
    if file_path:
        anchors["endpoint"] = file_path
    if not anchors:
        raise ValueError("falco_runtime_v1 requires host, container, pod, src_ip, or file path")

    reason_codes = ["falco_runtime", f"falco_rule:{rule.strip().lower().replace(' ', '_')}"]
    for tag in tags[:5]:
        reason_codes.append(f"tag:{tag.strip().lower()}")

    model_payload = {
        "source": "falco",
        "host": host or service_id,
        "artifact_name": rule,
        "finding_type": _as_str(payload, ("source", "evt_source")) or "runtime_alert",
        "severity": _falco_priority_to_severity(priority),
        "status": _as_str(payload, ("status", "state")) or "active",
        "client_ip": src_ip,
        "command_line": command_line,
        "file_path": file_path,
        "hunt_id": _as_str(payload, ("event_id", "evt_id", "rule_id")),
        "case_id": namespace,
        "reason_codes": sorted(set(reason_codes)),
        "message": output,
        "process_name": process_name,
        "user": user,
        "container_id": container_id,
        "container_name": container_name,
        "pod_name": pod_name,
        "host_name": host,
        "priority": priority,
        "tags": tags or None,
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


def _map_tetragon_runtime(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "process_start_time", "event_time"))
    policy_name = _as_str(payload, ("policy_name", "policy", "sensor"))
    event_type = _as_str(payload, ("event_type", "type", "action"), required=True)
    verdict = _as_str(payload, ("verdict", "result", "status"))
    host = _as_str(payload, ("hostname", "host", "node_name"))
    pod_name = _as_str(payload, ("pod_name", "pod", "k8s.pod.name"))
    namespace = _as_str(payload, ("namespace", "k8s.ns.name", "k8s.namespace.name"))
    workload = _as_str(payload, ("workload", "deployment", "container_name"))
    process_name = _as_str(payload, ("process_name", "binary", "exec"))
    command_line = _as_str(payload, ("command_line", "args", "arguments"))
    file_path = _as_str(payload, ("file_path", "path", "binary_path"))
    src_ip = _as_str(payload, ("src_ip", "client_ip", "source_ip"))

    service_id = pod_name or workload or (f"host:{host}" if host else None)
    anchors: Dict[str, str] = {}
    if service_id:
        anchors["service_id"] = service_id
    if host:
        anchors["device_id"] = host
    if src_ip:
        anchors["ip"] = src_ip
    if file_path:
        anchors["endpoint"] = file_path
    if not anchors:
        raise ValueError("tetragon_runtime_v1 requires host, pod, workload, src_ip, or file path")

    reason_codes = ["tetragon_runtime", f"tetragon_event:{event_type.strip().lower().replace(' ', '_')}"]
    if policy_name:
        reason_codes.append(f"tetragon_policy:{policy_name.strip().lower().replace(' ', '_')}")
    if verdict and verdict.strip().lower() in {"denied", "blocked", "killed"}:
        reason_codes.append("runtime_enforcement_triggered")

    model_payload = {
        "source": "tetragon",
        "host": host or service_id,
        "artifact_name": policy_name or event_type,
        "finding_type": event_type,
        "severity": _normalize_severity(_as_str(payload, ("severity", "priority")), default="high"),
        "status": verdict or "observed",
        "client_ip": src_ip,
        "command_line": command_line,
        "file_path": file_path,
        "hunt_id": _as_str(payload, ("event_id", "id")),
        "case_id": namespace,
        "reason_codes": sorted(set(reason_codes)),
        "message": _as_str(payload, ("message", "description")),
        "process_name": process_name,
        "pod_name": pod_name,
        "namespace": namespace,
        "workload": workload,
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


def _map_coraza_waf(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "transaction.time"))
    service_id = _as_str(payload, ("service_id", "host", "hostname", "server_name"), required=True)
    endpoint = _as_str(payload, ("endpoint", "uri", "path", "request_uri"))
    rule_id = _as_str(payload, ("rule_id", "matched_rule_id", "rule.id"))
    attack_type = _as_str(payload, ("attack_type", "rule_family", "tag", "matched_data")) or rule_id or "waf_rule_match"
    status = _normalize_web_attack_status(_as_str(payload, ("status", "action", "decision", "interruption_action")))
    ip = _as_str(payload, ("ip", "src_ip", "client_ip", "remote_addr"))
    method = _as_str(payload, ("method", "http_method", "request_method"))
    user_agent = _as_str(payload, ("user_agent", "request_headers.user-agent"))
    tx_id = _as_str(payload, ("transaction_id", "tx_id", "unique_id"))
    req_count = _as_int(payload, ("request_count", "count"))

    reason_codes = ["coraza_waf", f"web_attack:{str(attack_type).strip().lower().replace(' ', '_')}"]
    if rule_id:
        reason_codes.append(f"coraza_rule:{rule_id}")
    if status == "allowed":
        reason_codes.append("waf_bypass_signal")

    anchors: Dict[str, str] = {"service_id": service_id}
    if endpoint:
        anchors["endpoint"] = endpoint
    if ip:
        anchors["ip"] = ip

    model_payload = {
        "source": "coraza",
        "service_id": service_id,
        "endpoint": endpoint,
        "method": method,
        "attack_type": attack_type,
        "status": status,
        "req_count": req_count,
        "src_ip": ip,
        "user_agent": user_agent,
        "rule_id": rule_id,
        "transaction_id": tx_id,
        "reason_codes": sorted(set(reason_codes)),
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
        "dataset": _as_str(payload, ("dataset",)),
        "attack_label": _as_str(payload, ("attack_label",)),
        "benchmark_family": _as_str(payload, ("benchmark_family",)),
        "ground_truth_label": payload.get("ground_truth_label"),
        "confirmed_benign": payload.get("confirmed_benign"),
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


def _map_threatfox_ioc(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(
        payload,
        ("timestamp", "first_seen", "date_added", "created", "ioc_created_at"),
    )
    indicator = _as_str(payload, ("indicator", "ioc", "value"), required=True)
    indicator_type = (_as_str(payload, ("indicator_type", "ioc_type", "type")) or "").strip().lower()
    malware = _as_str(payload, ("malware", "malware_family", "threat_type")) or "malware_ioc"
    tags = _as_str_list(payload, ("tags", "tag"))
    status = _as_str(payload, ("status", "ioc_status")) or "active"

    anchors: Dict[str, str] = {}
    host = indicator
    if indicator_type in {"ip", "ipv4", "ipv6"}:
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
        anchors["endpoint"] = f"{indicator_type or 'ioc'}:{indicator}"

    reason_codes = ["malware_ioc", "osint_feed", "feed:threatfox"]
    if status:
        reason_codes.append(f"ioc_status:{status.strip().lower()}")
    if malware:
        reason_codes.append(f"malware_family:{malware.strip().lower()}")
    for tag in tags[:5]:
        reason_codes.append(f"tag:{tag.strip().lower()}")

    model_payload: Dict[str, Any] = {
        "source": "threatfox",
        "host": host,
        "artifact_name": "threatfox",
        "finding_type": malware,
        "severity": _normalize_ioc_severity(status, default="high"),
        "status": status,
        "client_ip": indicator if "ip" in anchors else None,
        "file_path": indicator if indicator_type == "url" else None,
        "sha256": indicator if indicator_type in {"sha256", "tlsh", "md5"} else None,
        "case_id": _as_str(payload, ("reporter", "reporter_name")),
        "hunt_id": _as_str(payload, ("id", "ioc_id", "threatfox_id")),
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


def _map_malwarebazaar_sample(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(
        payload,
        ("timestamp", "first_seen", "date_added", "created", "file_added"),
    )
    sha256 = _as_str(payload, ("sha256_hash", "sha256", "hash"), required=True)
    family = _as_str(payload, ("malware_family", "signature", "family")) or "malware_sample"
    filename = _as_str(payload, ("file_name", "filename"))
    delivery_url = _as_str(payload, ("delivery_url", "url"))
    tag_list = _as_str_list(payload, ("tags", "tag"))
    status = _as_str(payload, ("status", "sample_status")) or "active"

    anchors: Dict[str, str] = {"endpoint": f"sha256:{sha256.lower()}"}
    if delivery_url:
        anchors["url"] = delivery_url
        domain = _extract_domain_from_url(delivery_url)
        if domain:
            anchors["domain"] = domain

    reason_codes = ["malware_sample", "osint_feed", "feed:malwarebazaar"]
    if family:
        reason_codes.append(f"malware_family:{family.strip().lower()}")
    for tag in tag_list[:5]:
        reason_codes.append(f"tag:{tag.strip().lower()}")

    model_payload: Dict[str, Any] = {
        "source": "malwarebazaar",
        "host": family,
        "artifact_name": filename or family,
        "finding_type": family,
        "severity": _normalize_ioc_severity(status, default="high"),
        "status": status,
        "sha256": sha256.lower(),
        "file_path": delivery_url,
        "command_line": _as_str(payload, ("file_type", "file_type_mime")),
        "case_id": _as_str(payload, ("reporter", "reporter_name")),
        "hunt_id": _as_str(payload, ("sha256_hash", "sample_id", "id")),
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


def _map_vpn_gateway_session(payload: Dict[str, Any], confidence: float, classification: Optional[str]) -> CanonicalEvent:
    occurred_at = _as_datetime(payload, ("timestamp", "time", "occurred_at", "first_seen", "flow_start_time"))
    client_ip = _as_str(payload, ("src_ip", "ip", "client_ip", "source_ip"))
    gateway = _as_str(payload, ("gateway_id", "service_id", "dst_ip", "destination_ip", "vpn_gateway")) or "vpn-gateway"
    device_id = _as_str(payload, ("device_id", "session_id", "dst_ip", "client_id")) or gateway
    if not client_ip and not device_id:
        raise ValueError("vpn_gateway_session_v1 requires src_ip/ip/client_ip or device_id")

    anchors: Dict[str, str] = {}
    if client_ip:
        anchors["ip"] = client_ip
    if device_id:
        anchors["device_id"] = device_id

    username = _as_str(payload, ("username", "user", "principal", "app_label"))
    outcome = _normalize_login_outcome(_as_str(payload, ("result", "status", "outcome")) or "success")
    model_payload: Dict[str, Any] = {
        "username": username,
        "outcome": outcome,
        "user_agent": _as_str(payload, ("protocol", "vpn_proto", "app_label")),
        "device_id": device_id,
        "ip": client_ip,
        "asn": _as_int(payload, ("asn", "src_asn")),
        "provider": _as_str(payload, ("provider", "vpn_provider", "category")),
        "request_fingerprint": _as_str(payload, ("request_fingerprint", "flow_id")),
        "dataset": _as_str(payload, ("dataset",)),
        "benchmark_label": _as_str(payload, ("benchmark_label", "label")),
        "vpn_detected": payload.get("vpn_detected"),
        "confirmed_benign": payload.get("confirmed_benign"),
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
    "crowdsec_alert_v1": ConnectorDefinition(
        key="crowdsec_alert_v1",
        description="CrowdSec alert stream to DFIR_FINDING_EVENT",
        required_fields=("timestamp|created_at", "scenario|alert_name", "scope|value OR src_ip OR service_id"),
        mapper=_map_crowdsec_alert,
    ),
    "falco_runtime_v1": ConnectorDefinition(
        key="falco_runtime_v1",
        description="Falco runtime alerts to DFIR_FINDING_EVENT",
        required_fields=("timestamp|output_time", "rule|alert", "hostname|host OR container_id OR pod_name"),
        mapper=_map_falco_runtime,
    ),
    "tetragon_runtime_v1": ConnectorDefinition(
        key="tetragon_runtime_v1",
        description="Tetragon runtime telemetry to DFIR_FINDING_EVENT",
        required_fields=("timestamp|event_time", "event_type|type", "hostname|host OR pod_name OR workload"),
        mapper=_map_tetragon_runtime,
    ),
    "coraza_waf_v1": ConnectorDefinition(
        key="coraza_waf_v1",
        description="Coraza or OWASP CRS WAF alerts to WEB_ATTACK_EVENT",
        required_fields=("timestamp", "service_id|host|hostname", "attack_type|rule_id|matched_rule_id"),
        mapper=_map_coraza_waf,
    ),
    "suricata_eve_v1": ConnectorDefinition(
        key="suricata_eve_v1",
        description="Suricata EVE alerts to DDOS_SIGNAL_EVENT, WEB_ATTACK_EVENT, or DFIR_FINDING_EVENT",
        required_fields=("timestamp", "src_ip|src OR dest_ip|dst", "alert.signature|category"),
        mapper=_map_suricata_eve,
    ),
    "zeek_notice_v1": ConnectorDefinition(
        key="zeek_notice_v1",
        description="Zeek notice.log alerts to DFIR_FINDING_EVENT",
        required_fields=("timestamp|ts", "note|notice_type", "src|src_ip OR dst|dest_ip"),
        mapper=_map_zeek_notice,
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
    "threatfox_ioc_v1": ConnectorDefinition(
        key="threatfox_ioc_v1",
        description="ThreatFox malware IOC feed to DFIR_FINDING_EVENT",
        required_fields=("indicator|ioc|value", "indicator_type|ioc_type|type"),
        mapper=_map_threatfox_ioc,
    ),
    "malwarebazaar_sample_v1": ConnectorDefinition(
        key="malwarebazaar_sample_v1",
        description="MalwareBazaar sample metadata to DFIR_FINDING_EVENT",
        required_fields=("sha256_hash|sha256|hash",),
        mapper=_map_malwarebazaar_sample,
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
    "vpn_gateway_session_v1": ConnectorDefinition(
        key="vpn_gateway_session_v1",
        description="VPN benchmark or gateway session rows to LOGIN_EVENT",
        required_fields=("timestamp|time|flow_start_time", "src_ip|ip|client_ip OR device_id|session_id|dst_ip"),
        mapper=_map_vpn_gateway_session,
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
