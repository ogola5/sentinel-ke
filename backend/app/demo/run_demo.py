from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from app.ingestion.schemas import CanonicalEvent
from app.ingestion.service import IngestionService
from app.ledger.db import SessionLocal
from app.ledger.seed_sources import seed as seed_sources
from app.streaming.producer import get_producer


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ip_pool(prefix: str, count: int) -> List[str]:
    return [f"{prefix}{i+1}" for i in range(count)]


def _endpoint_anchor(service_id: str, endpoint_path: str, method: str = "POST") -> str:
    normalized_service = str(service_id or "").strip() or "unknown-service"
    normalized_path = str(endpoint_path or "").strip() or "/"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    normalized_method = str(method or "POST").strip().upper() or "POST"
    return f"{normalized_service}:{normalized_path}:{normalized_method}"


def build_ddos_events(
    base_time: datetime,
    *,
    service_id: str = "kplc",
    endpoint_path: str = "/login",
    method: str = "POST",
    ip_prefix: str = "203.0.113.",
    ip_count: int = 25,
) -> List[CanonicalEvent]:
    events: List[CanonicalEvent] = []
    ip_pool = _ip_pool(ip_prefix, ip_count)
    endpoint_anchor = _endpoint_anchor(service_id, endpoint_path, method)

    # rehearsal burst (low)
    for i in range(20):
        ts = base_time - timedelta(minutes=12) + timedelta(seconds=i * 15)
        events.append(
            CanonicalEvent(
                event_type="DDOS_SIGNAL_EVENT",
                occurred_at=ts,
                anchors={
                    "service_id": service_id,
                    "endpoint": endpoint_anchor,
                    "ip": ip_pool[i % len(ip_pool)],
                },
                payload={
                    "service_id": service_id,
                    "endpoint": endpoint_path,
                    "req_rate": 90,
                    "unique_ips_count": 25,
                    "error_rate": 0.01,
                    "avg_latency_ms": 70,
                    "endpoint_convergence": 0.3,
                    "asn_concentration": 0.25,
                },
            )
        )

    # active burst (higher)
    for i in range(60):
        ts = base_time - timedelta(minutes=3) + timedelta(seconds=i * 3)
        events.append(
            CanonicalEvent(
                event_type="DDOS_SIGNAL_EVENT",
                occurred_at=ts,
                anchors={
                    "service_id": service_id,
                    "endpoint": endpoint_anchor,
                    "ip": ip_pool[i % len(ip_pool)],
                },
                payload={
                    "service_id": service_id,
                    "endpoint": endpoint_path,
                    "req_rate": 450,
                    "unique_ips_count": 40,
                    "error_rate": 0.04,
                    "avg_latency_ms": 180,
                    "endpoint_convergence": 0.7,
                    "asn_concentration": 0.6,
                },
            )
        )

    return events


def _ddos_events(base_time: datetime) -> List[CanonicalEvent]:
    return build_ddos_events(base_time)


def _vpn_events(base_time: datetime) -> List[CanonicalEvent]:
    events: List[CanonicalEvent] = []
    ip_pool = _ip_pool("102.168.1.", 6)

    for i in range(24):
        ts = base_time - timedelta(minutes=30) + timedelta(seconds=i * 45)
        events.append(
            CanonicalEvent(
                event_type="LOGIN_EVENT",
                occurred_at=ts,
                anchors={
                    "endpoint": "portal:/login:POST",
                    "device_id": "device-demo-1",
                    "ip": ip_pool[i % len(ip_pool)],
                },
                payload={
                    "username": "demo-user",
                    "outcome": "success",
                    "user_agent": "Mozilla/5.0",
                    "device_id": "device-demo-1",
                    "provider": "demo-vpn",
                },
            )
        )

    return events


def _malware_events(base_time: datetime) -> List[CanonicalEvent]:
    events: List[CanonicalEvent] = []
    shared_ip = "50.16.16.211"
    shared_domain = "update-checkin-control.net"
    shared_url = "http://update-checkin-control.net/bootstrap.bin"

    rows = [
        {
            "minutes_ago": 22,
            "device_id": "gov-edge-host-17",
            "service_id": "ecitizen",
            "finding_type": "botnet_c2_indicator",
            "malware_family": "mirai",
            "confidence": 0.92,
            "source": "threatfox",
        },
        {
            "minutes_ago": 18,
            "device_id": "gov-edge-host-17",
            "service_id": "ecitizen",
            "finding_type": "malware_url",
            "malware_family": "mirai",
            "confidence": 0.88,
            "source": "urlhaus",
        },
        {
            "minutes_ago": 13,
            "device_id": "kra-edge-host-02",
            "service_id": "kra-tax-portal-ke",
            "finding_type": "botnet_c2_indicator",
            "malware_family": "mirai",
            "confidence": 0.9,
            "source": "feodo",
        },
        {
            "minutes_ago": 9,
            "device_id": "finance-mail-node-04",
            "service_id": "mail-gateway-ke",
            "finding_type": "malware_url",
            "malware_family": "loader",
            "confidence": 0.85,
            "source": "malwarebazaar",
        },
    ]

    for row in rows:
        ts = base_time - timedelta(minutes=int(row["minutes_ago"]))
        events.append(
            CanonicalEvent(
                event_type="DFIR_FINDING_EVENT",
                occurred_at=ts,
                anchors={
                    "ip": shared_ip,
                    "domain": shared_domain,
                    "url": shared_url,
                    "device_id": str(row["device_id"]),
                    "service_id": str(row["service_id"]),
                },
                payload={
                    "host": row["device_id"],
                    "artifact_name": "network_ioc_hunt",
                    "ip": shared_ip,
                    "domain": shared_domain,
                    "url": shared_url,
                    "device_id": row["device_id"],
                    "service_id": row["service_id"],
                    "finding_type": row["finding_type"],
                    "malware_family": row["malware_family"],
                    "severity": "high",
                    "confidence": row["confidence"],
                    "source": row["source"],
                    "summary": f"{row['malware_family']} infrastructure touching {row['service_id']}",
                },
            )
        )

    return events


def _fraud_events(base_time: datetime) -> List[CanonicalEvent]:
    events: List[CanonicalEvent] = []

    victims = [
        {"phone": "254700000101", "device": "sim-device-a", "account": "acct-1001", "user": "user-1001"},
        {"phone": "254700000102", "device": "sim-device-b", "account": "acct-1002", "user": "user-1002"},
        {"phone": "254700000103", "device": "sim-device-c", "account": "acct-1003", "user": "user-1003"},
    ]
    mule_account = "acct-9001"
    agent_id = "agent-47"

    # SIM swaps (victims)
    for i, v in enumerate(victims):
        ts = base_time - timedelta(minutes=70) + timedelta(minutes=i * 3)
        events.append(
            CanonicalEvent(
                event_type="SIM_SWAP_EVENT",
                occurred_at=ts,
                anchors={"phone_h": v["phone"], "device_id": v["device"]},
                payload={
                    "phone": v["phone"],
                    "prev_sim_id": f"sim-{i+1:03d}",
                    "new_sim_id": f"sim-{i+4:03d}",
                    "reason": "re-issue",
                },
            )
        )

    # Logins from new device/IPs
    for i, v in enumerate(victims):
        for j in range(2):
            ts = base_time - timedelta(minutes=60) + timedelta(minutes=i * 3 + j * 5)
            events.append(
                CanonicalEvent(
                    event_type="LOGIN_EVENT",
                    occurred_at=ts,
                    anchors={
                        "device_id": v["device"],
                        "endpoint": "bank:/login:POST",
                        "ip": f"41.90.10.{10 + i * 3 + j}",
                    },
                    payload={
                        "username": v["user"],
                        "outcome": "success",
                        "user_agent": "Mozilla/5.0",
                        "device_id": v["device"],
                        "provider": "cellular",
                    },
                )
            )

    # Transfers from victims -> mule
    for i, v in enumerate(victims):
        for j in range(3):
            ts = base_time - timedelta(minutes=45) + timedelta(minutes=i * 2 + j * 3)
            events.append(
                CanonicalEvent(
                    event_type="TRANSACTION_EVENT",
                    occurred_at=ts,
                    anchors={
                        "device_id": v["device"],
                        "account_h": v["account"],
                    },
                    payload={
                        "account_from": v["account"],
                        "account_to": mule_account,
                        "amount": 4500 + (j * 500),
                        "currency": "KES",
                        "channel": "MOBILE",
                        "device_id": v["device"],
                        "agent_id": agent_id,
                    },
                )
            )

    # Cashout from mule at agent
    for j in range(2):
        ts = base_time - timedelta(minutes=25) + timedelta(minutes=j * 4)
        events.append(
            CanonicalEvent(
                event_type="TRANSACTION_EVENT",
                occurred_at=ts,
                anchors={
                    "account_h": mule_account,
                    "agent_id": agent_id,
                },
                payload={
                    "account_from": mule_account,
                    "account_to": "cashout",
                    "amount": 12000 + j * 1000,
                    "currency": "KES",
                    "channel": "AGENT_CASHOUT",
                    "agent_id": agent_id,
                    "agent_location": "Nairobi-West",
                    "withdrawal_type": "agent",
                },
            )
        )

    return events


def run_demo(*, seed: bool = False, scenario: str = "ddos_vpn", mode: str = "db", topic: str = "sentinel.ingest") -> None:
    if seed:
        seed_sources()

    normalized_scenario = "fraud" if scenario == "sim_swap" else scenario
    base_time = _now_utc()

    events: List[CanonicalEvent] = []
    if normalized_scenario in ("ddos", "ddos_vpn", "all", "ddos_vpn_fraud"):
        events.extend(_ddos_events(base_time))
    if normalized_scenario in ("malware", "all"):
        events.extend(_malware_events(base_time))
    if normalized_scenario in ("vpn", "ddos_vpn", "all", "ddos_vpn_fraud"):
        events.extend(_vpn_events(base_time))
    if normalized_scenario in ("fraud", "all", "ddos_vpn_fraud"):
        events.extend(_fraud_events(base_time))

    if mode == "kafka":
        producer = get_producer()
        if not producer:
            raise RuntimeError("Kafka producer unavailable (KAFKA_ENABLED=false?)")
        published = 0
        for ev in events:
            if ev.event_type == "DDOS_SIGNAL_EVENT":
                key = "kpa-secret-key"
            elif ev.event_type == "LOGIN_EVENT":
                key = "kcb-secret-key"
            elif ev.event_type == "SIM_SWAP_EVENT":
                key = "safaricom-secret-key"
            elif ev.event_type == "TRANSACTION_EVENT":
                key = "kcb-secret-key"
            else:
                key = "osint-secret-key"
            payload = {"source_api_key": key, "event": ev.model_dump()}
            producer.publish(topic=topic, key=f"demo:{published}", value=payload)
            published += 1
        producer.flush()
        print(f"[demo] scenario={normalized_scenario} total={len(events)} published={published} topic={topic}")
        return

    db = SessionLocal()
    svc = IngestionService(db, pseudonym_salt="demo-salt")
    accepted = 0
    duplicates = 0
    try:
        for ev in events:
            if ev.event_type == "DDOS_SIGNAL_EVENT":
                key = "kpa-secret-key"
            elif ev.event_type == "LOGIN_EVENT":
                key = "kcb-secret-key"
            elif ev.event_type == "SIM_SWAP_EVENT":
                key = "safaricom-secret-key"
            elif ev.event_type == "TRANSACTION_EVENT":
                key = "kcb-secret-key"
            else:
                key = "osint-secret-key"
            res = svc.ingest_event(event=ev, source_api_key=key)
            if res.status == "accepted":
                accepted += 1
            else:
                duplicates += 1
    finally:
        db.close()

    print(f"[demo] scenario={normalized_scenario} total={len(events)} accepted={accepted} duplicate={duplicates}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--seed-sources", action="store_true")
    p.add_argument("--scenario", choices=["ddos", "malware", "vpn", "sim_swap", "fraud", "ddos_vpn", "ddos_vpn_fraud", "all"], default="ddos_vpn")
    p.add_argument("--mode", choices=["db", "kafka"], default="db")
    p.add_argument("--topic", default="sentinel.ingest")
    args = p.parse_args()

    run_demo(seed=args.seed_sources, scenario=args.scenario, mode=args.mode, topic=args.topic)


if __name__ == "__main__":
    main()
