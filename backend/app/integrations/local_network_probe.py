from __future__ import annotations

import argparse
import json
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest


@dataclass(frozen=True)
class InterfaceStats:
    interface: str
    operstate: str
    mac: Optional[str]
    mtu: Optional[int]
    rx_bytes: int
    tx_bytes: int
    rx_packets: int
    tx_packets: int
    rx_errors: int
    tx_errors: int
    rx_drop: int
    tx_drop: int


@dataclass(frozen=True)
class SampleSnapshot:
    interface: str
    sampled_monotonic: float
    rx_bytes: int
    tx_bytes: int
    rx_packets: int
    tx_packets: int
    rx_errors: int
    tx_errors: int


def _read_text(path: str) -> Optional[str]:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _read_int(path: str) -> Optional[int]:
    raw = _read_text(path)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _hex_le_ipv4(raw_hex: str) -> Optional[str]:
    try:
        b = int(raw_hex, 16).to_bytes(4, byteorder="little", signed=False)
        return ".".join(str(x) for x in b)
    except Exception:
        return None


def _read_default_route() -> Tuple[Optional[str], Optional[str]]:
    path = "/proc/net/route"
    try:
        rows = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return None, None

    for row in rows[1:]:
        cols = row.split()
        if len(cols) < 4:
            continue
        iface = cols[0]
        destination = cols[1]
        gateway_hex = cols[2]
        flags_hex = cols[3]

        try:
            flags = int(flags_hex, 16)
        except ValueError:
            continue

        # RTF_GATEWAY=0x2, default route destination=0.0.0.0
        if destination == "00000000" and (flags & 0x2):
            return iface, _hex_le_ipv4(gateway_hex)
    return None, None


def _read_dns_config() -> Tuple[List[str], List[str]]:
    nameservers: List[str] = []
    search_domains: List[str] = []
    path = "/etc/resolv.conf"

    try:
        rows = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return nameservers, search_domains

    for raw in rows:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        key = parts[0].lower()
        vals = parts[1:]
        if key == "nameserver":
            nameservers.extend(vals)
        elif key == "search":
            search_domains.extend(vals)

    nameservers = sorted(set(x.strip() for x in nameservers if x.strip()))
    search_domains = sorted(set(x.strip() for x in search_domains if x.strip()))
    return nameservers, search_domains


def _count_dns_udp_sockets(path: str) -> int:
    try:
        rows = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return 0

    count = 0
    for row in rows[1:]:
        cols = row.split()
        if len(cols) < 3:
            continue
        local = cols[1]
        remote = cols[2]
        local_port_hex = local.split(":")[-1] if ":" in local else ""
        remote_port_hex = remote.split(":")[-1] if ":" in remote else ""
        try:
            local_port = int(local_port_hex, 16)
            remote_port = int(remote_port_hex, 16)
        except ValueError:
            continue
        if local_port == 53 or remote_port == 53:
            count += 1
    return count


def _read_proc_net_dev(interface: str) -> Dict[str, int]:
    try:
        rows = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()
    except Exception as e:
        raise RuntimeError(f"failed to read /proc/net/dev: {e}") from e

    for row in rows[2:]:
        if ":" not in row:
            continue
        name, values_raw = row.split(":", 1)
        if name.strip() != interface:
            continue
        parts = values_raw.split()
        if len(parts) < 16:
            raise RuntimeError(f"unexpected /proc/net/dev format for interface '{interface}'")
        return {
            "rx_bytes": int(parts[0]),
            "rx_packets": int(parts[1]),
            "rx_errors": int(parts[2]),
            "rx_drop": int(parts[3]),
            "tx_bytes": int(parts[8]),
            "tx_packets": int(parts[9]),
            "tx_errors": int(parts[10]),
            "tx_drop": int(parts[11]),
        }
    raise RuntimeError(f"interface '{interface}' not found in /proc/net/dev")


def _read_interface_stats(interface: str) -> InterfaceStats:
    base = f"/sys/class/net/{interface}"
    operstate = (_read_text(f"{base}/operstate") or "unknown").lower()
    mac = _read_text(f"{base}/address")
    mtu = _read_int(f"{base}/mtu")
    dev = _read_proc_net_dev(interface)
    return InterfaceStats(
        interface=interface,
        operstate=operstate,
        mac=mac,
        mtu=mtu,
        rx_bytes=dev["rx_bytes"],
        tx_bytes=dev["tx_bytes"],
        rx_packets=dev["rx_packets"],
        tx_packets=dev["tx_packets"],
        rx_errors=dev["rx_errors"],
        tx_errors=dev["tx_errors"],
        rx_drop=dev["rx_drop"],
        tx_drop=dev["tx_drop"],
    )


def _available_interfaces() -> List[str]:
    path = Path("/sys/class/net")
    if not path.exists():
        return []
    items = []
    for p in path.iterdir():
        if p.is_dir():
            items.append(p.name)
    return sorted(items)


def _pick_interface(preferred: Optional[str]) -> Optional[str]:
    interfaces = _available_interfaces()
    if not interfaces:
        return None

    if preferred and preferred in interfaces:
        return preferred

    route_iface, _ = _read_default_route()
    if route_iface and route_iface in interfaces:
        return route_iface

    non_loopback = [x for x in interfaces if x != "lo"]
    if non_loopback:
        return non_loopback[0]
    return interfaces[0]


def _to_snapshot(stats: InterfaceStats, sampled_monotonic: float) -> SampleSnapshot:
    return SampleSnapshot(
        interface=stats.interface,
        sampled_monotonic=sampled_monotonic,
        rx_bytes=stats.rx_bytes,
        tx_bytes=stats.tx_bytes,
        rx_packets=stats.rx_packets,
        tx_packets=stats.tx_packets,
        rx_errors=stats.rx_errors,
        tx_errors=stats.tx_errors,
    )


def _derive_rates(
    *,
    prev: Optional[SampleSnapshot],
    current: SampleSnapshot,
) -> Dict[str, float]:
    if prev is None or prev.interface != current.interface:
        return {}
    elapsed = current.sampled_monotonic - prev.sampled_monotonic
    if elapsed <= 0:
        return {}

    def _delta(now: int, before: int) -> int:
        d = now - before
        return d if d >= 0 else 0

    d_rx_bytes = _delta(current.rx_bytes, prev.rx_bytes)
    d_tx_bytes = _delta(current.tx_bytes, prev.tx_bytes)
    d_rx_packets = _delta(current.rx_packets, prev.rx_packets)
    d_tx_packets = _delta(current.tx_packets, prev.tx_packets)
    d_rx_errors = _delta(current.rx_errors, prev.rx_errors)
    d_tx_errors = _delta(current.tx_errors, prev.tx_errors)

    total_packets = d_rx_packets + d_tx_packets
    total_errors = d_rx_errors + d_tx_errors
    error_rate = (float(total_errors) / float(total_packets)) if total_packets > 0 else 0.0

    return {
        "sample_interval_seconds": round(elapsed, 3),
        "rx_bps": round((d_rx_bytes * 8.0) / elapsed, 3),
        "tx_bps": round((d_tx_bytes * 8.0) / elapsed, 3),
        "rx_pps": round(d_rx_packets / elapsed, 3),
        "tx_pps": round(d_tx_packets / elapsed, 3),
        "error_rate": round(error_rate, 6),
    }


def _build_payload(
    *,
    interface: str,
    prev_snapshot: Optional[SampleSnapshot],
) -> Tuple[Dict[str, Any], SampleSnapshot]:
    sampled_wall = datetime.now(timezone.utc)
    sampled_monotonic = time.monotonic()
    hostname = socket.gethostname()
    route_iface, gateway = _read_default_route()
    dns_servers, search_domains = _read_dns_config()

    stats = _read_interface_stats(interface)
    snapshot = _to_snapshot(stats, sampled_monotonic)
    rates = _derive_rates(prev=prev_snapshot, current=snapshot)

    status = "up"
    link_up = stats.operstate == "up"
    if not link_up:
        status = "down"
    elif not gateway or not dns_servers:
        status = "degraded"
    elif rates.get("error_rate", 0.0) > 0.01:
        status = "degraded"

    payload: Dict[str, Any] = {
        "timestamp": sampled_wall.isoformat(),
        "hostname": hostname,
        "interface": interface,
        "service_id": f"local-network:{hostname}:{interface}",
        "status": status,
        "link_up": link_up,
        "gateway": gateway,
        "gateway_iface": route_iface,
        "dns_servers": dns_servers,
        "dns_search_domains": search_domains,
        "dns_server_count": len(dns_servers),
        "dns_udp_sockets_v4": _count_dns_udp_sockets("/proc/net/udp"),
        "dns_udp_sockets_v6": _count_dns_udp_sockets("/proc/net/udp6"),
        "mac": stats.mac,
        "mtu": stats.mtu,
        "rx_bytes": stats.rx_bytes,
        "tx_bytes": stats.tx_bytes,
        "rx_packets": stats.rx_packets,
        "tx_packets": stats.tx_packets,
        "rx_errors": stats.rx_errors,
        "tx_errors": stats.tx_errors,
        "rx_drop": stats.rx_drop,
        "tx_drop": stats.tx_drop,
    }
    payload.update(rates)
    payload = {k: v for k, v in payload.items() if v is not None}
    return payload, snapshot


def _post_connector_event(
    *,
    endpoint: str,
    connector_key: str,
    source_api_key: str,
    payload: Dict[str, Any],
    confidence: float,
    classification: Optional[str],
    x_api_key: Optional[str],
    timeout_seconds: float,
) -> Dict[str, Any]:
    base = endpoint.rstrip("/")
    url = f"{base}/v1/integrations/{connector_key}/event"
    req_payload: Dict[str, Any] = {
        "source_api_key": source_api_key,
        "confidence": confidence,
        "payload": payload,
    }
    if classification:
        req_payload["classification"] = classification

    data = json.dumps(req_payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if x_api_key:
        headers["X-API-Key"] = x_api_key

    req = urlrequest.Request(url=url, data=data, headers=headers, method="POST")
    with urlrequest.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read().decode("utf-8")
        if not body.strip():
            return {"status_code": resp.getcode()}
        return json.loads(body)


def _run_loop(args: argparse.Namespace) -> int:
    prev_snapshot: Optional[SampleSnapshot] = None

    while True:
        loop_started = time.monotonic()

        interface = _pick_interface(args.interface)
        if interface is None:
            print("local_network_probe: no network interface found")
            if args.once:
                return 1
            time.sleep(args.interval_seconds)
            continue

        try:
            payload, current_snapshot = _build_payload(
                interface=interface,
                prev_snapshot=prev_snapshot,
            )
            prev_snapshot = current_snapshot
        except Exception as e:
            print(f"local_network_probe: sample_error interface={interface} err={e}")
            if args.once:
                return 1
            time.sleep(args.interval_seconds)
            continue

        if args.dry_run:
            print(json.dumps(payload, sort_keys=True))
        else:
            try:
                out = _post_connector_event(
                    endpoint=args.endpoint,
                    connector_key=args.connector_key,
                    source_api_key=args.source_api_key,
                    payload=payload,
                    confidence=args.confidence,
                    classification=args.classification,
                    x_api_key=args.x_api_key,
                    timeout_seconds=args.timeout_seconds,
                )
                status = out.get("status")
                event_hash = out.get("event_hash", "-")
                mapped = out.get("mapped_event_type", "-")
                print(
                    f"local_network_probe: sent interface={interface} status={status} "
                    f"mapped={mapped} event_hash={event_hash}"
                )
            except urlerror.HTTPError as e:
                details = e.read().decode("utf-8", errors="replace")
                print(
                    f"local_network_probe: http_error code={e.code} interface={interface} details={details}"
                )
            except Exception as e:
                print(f"local_network_probe: send_error interface={interface} err={e}")

        if args.once:
            return 0

        elapsed = time.monotonic() - loop_started
        sleep_for = max(0.0, args.interval_seconds - elapsed)
        time.sleep(sleep_for)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Continuously sample passive local interface/gateway/DNS/traffic metrics and send to "
            "Sentinel integrations connector."
        )
    )
    parser.add_argument("--endpoint", default="http://localhost:8000")
    parser.add_argument("--connector-key", default="local_network_probe_v1")
    parser.add_argument("--source-api-key", default="local-net-probe-secret-key")
    parser.add_argument("--x-api-key", default=None, help="Optional API key for route auth (X-API-Key).")
    parser.add_argument("--interface", default=None, help="Interface to monitor (auto if omitted).")
    parser.add_argument("--interval-seconds", type=float, default=10.0)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--confidence", type=float, default=0.8)
    parser.add_argument("--classification", default=None, choices=["PUBLIC", "RESTRICTED", "INTERNAL"])
    parser.add_argument("--once", action="store_true", help="Collect and send one sample only.")
    parser.add_argument("--dry-run", action="store_true", help="Print sampled payload instead of sending.")
    args = parser.parse_args()

    try:
        raise SystemExit(_run_loop(args))
    except KeyboardInterrupt:
        print("local_network_probe: stopped")


if __name__ == "__main__":
    main()
