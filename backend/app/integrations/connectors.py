from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

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
