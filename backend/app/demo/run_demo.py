from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Iterable, List

from app.core.config import settings
from app.federation.models import FederationPartner, FederationPattern
from app.ingestion.schemas import CanonicalEvent
from app.ingestion.service import IngestionService
from app.ledger.db import SessionLocal
from app.ledger.seed_sources import seed as seed_sources
from app.streaming.producer import get_producer
from sqlalchemy.dialects.postgresql import insert as pg_insert


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


FEDERATION_DEMO_PARTNERS = {
    "equity-bank-ke": {
        "partner_name": "Equity Bank Kenya",
        "partner_type": "bank",
        "api_key": "eq-bank-api-key-demo-2026",
    },
    "kcb-bank-ke": {
        "partner_name": "KCB Bank Kenya",
        "partner_type": "bank",
        "api_key": "kcb-bank-api-key-demo-2026",
    },
    "safaricom-ke": {
        "partner_name": "Safaricom PLC",
        "partner_type": "telco",
        "api_key": "saf-telco-api-key-demo-2026",
    },
    "ke-cirt": {
        "partner_name": "Kenya Computer Incident Response Team",
        "partner_type": "government",
        "api_key": "kecirt-gov-api-key-demo-2026",
    },
}


def _entity_hash(entity_key: str) -> str:
    salt = str(getattr(settings, "federation_correlation_salt", "") or "sentinel-demo-salt")
    return hmac.new(salt.encode(), entity_key.encode(), hashlib.sha256).hexdigest()


def _api_key_hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _upsert_demo_partners(db, *, now: datetime) -> None:
    for partner_id, spec in FEDERATION_DEMO_PARTNERS.items():
        partner = db.query(FederationPartner).filter(FederationPartner.partner_id == partner_id).first()
        metadata = dict((partner.metadata_json if partner else None) or {})
        metadata["demo"] = True
        metadata["edge_status"] = {
            "last_heartbeat_at": now.isoformat(),
            "agent_version": "edge-agent-demo-v2",
            "model_version": "edge-gnn-demo-v2",
            "artifact": {
                "available": True,
                "model_version": "edge-gnn-demo-v2",
                "trained_at": now.isoformat(),
            },
            "last_run_at": now.isoformat(),
            "last_run_status": "ok",
            "last_publish_status": "published",
            "run_count": max(1, int(metadata.get("edge_status", {}).get("run_count", 0))),
            "data_source": "federation_demo_seed",
            "hub_reachable": True,
            "capabilities": ["heartbeat", "pattern_publish", "local_gnn"],
        }
        values = {
            "partner_id": partner_id,
            "partner_name": str(spec["partner_name"]),
            "partner_type": str(spec["partner_type"]),
            "api_key_hash": _api_key_hash(str(spec["api_key"])),
            "correlation_salt": str(getattr(settings, "federation_correlation_salt", "") or ""),
            "is_active": True,
            "last_seen": now,
            "metadata_json": metadata,
        }
        stmt = pg_insert(FederationPartner).values(**values)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[FederationPartner.partner_id],
                set_={
                    "partner_name": values["partner_name"],
                    "partner_type": values["partner_type"],
                    "api_key_hash": values["api_key_hash"],
                    "correlation_salt": values["correlation_salt"],
                    "is_active": values["is_active"],
                    "last_seen": values["last_seen"],
                    "metadata_json": values["metadata_json"],
                },
            )
        )
    db.flush()


def _upsert_pattern(
    db,
    *,
    partner_id: str,
    entity_key: str,
    entity_type: str,
    risk_score: float,
    fraud_family: str,
    chain_score: float,
    risk_flags: Iterable[str],
    now: datetime,
    minutes_ago: int = 0,
) -> None:
    entity_key_hash = _entity_hash(entity_key)
    received_at = now - timedelta(minutes=minutes_ago)
    window_start = now - timedelta(hours=2)
    pattern = (
        db.query(FederationPattern)
        .filter(
            FederationPattern.partner_id == partner_id,
            FederationPattern.entity_key_hash == entity_key_hash,
            FederationPattern.fraud_family == fraud_family,
        )
        .first()
    )
    if pattern is None:
        pattern = FederationPattern(
            partner_id=partner_id,
            entity_key_hash=entity_key_hash,
        )
        db.add(pattern)
    pattern.received_at = received_at
    pattern.window_start = window_start
    pattern.window_end = now
    pattern.gnn_model_version = "edge-gnn-demo-v2"
    pattern.entity_type = entity_type
    pattern.risk_score = risk_score
    pattern.uncertainty = 0.05
    pattern.fraud_family = fraud_family
    pattern.chain_score = chain_score
    pattern.risk_flags = list(risk_flags)
    pattern.summary_json = {
        "total_scored": 1200,
        "high_risk_count": 4,
        "mean_risk": round(max(0.62, risk_score - 0.14), 3),
        "window_key": "W2h",
        "source": "federation_demo_seed",
    }
    pattern.schema_version = "1.0"


def _refresh_partner_rollups(db, *, partner_ids: Iterable[str], now: datetime) -> None:
    for partner_id in sorted(set(partner_ids)):
        partner = db.query(FederationPartner).filter(FederationPartner.partner_id == partner_id).first()
        if not partner:
            continue
        total_patterns = (
            db.query(FederationPattern)
            .filter(FederationPattern.partner_id == partner_id)
            .count()
        )
        metadata = dict(partner.metadata_json or {})
        edge_status = dict(metadata.get("edge_status") or {})
        edge_status.update(
            {
                "last_heartbeat_at": now.isoformat(),
                "model_version": "edge-gnn-demo-v2",
                "last_run_at": now.isoformat(),
                "last_run_status": "ok",
                "last_publish_status": "published",
                "run_count": max(1, total_patterns),
                "data_source": "federation_demo_seed",
                "hub_reachable": True,
            }
        )
        metadata["edge_status"] = edge_status
        partner.metadata_json = metadata
        partner.last_seen = now
        partner.last_pattern_at = now
        partner.total_patterns = total_patterns


def _federated_vpn_events(base_time: datetime) -> List[CanonicalEvent]:
    rows = [
        ("kcb-bank-ke", "KCB", "kcb-portal:/login:POST", "kcb-device-01"),
        ("equity-bank-ke", "Equity", "equity-portal:/login:POST", "equity-device-04"),
        ("safaricom-mpesa", "M-Pesa", "mpesa-wallet:/login:POST", "mpesa-device-02"),
    ]
    shared_ip = "196.201.214.55"
    events: List[CanonicalEvent] = []
    for idx, (service_id, provider, endpoint, device_id) in enumerate(rows):
        for j in range(4):
            ts = base_time - timedelta(minutes=24 - idx * 3) + timedelta(seconds=j * 40)
            events.append(
                CanonicalEvent(
                    event_type="LOGIN_EVENT",
                    occurred_at=ts,
                    anchors={
                        "service_id": service_id,
                        "endpoint": endpoint,
                        "device_id": device_id,
                        "ip": shared_ip,
                    },
                    payload={
                        "username": f"{provider.lower()}-user-{idx+1}",
                        "outcome": "success",
                        "user_agent": "Mozilla/5.0",
                        "device_id": device_id,
                        "provider": "demo-vpn",
                        "service_id": service_id,
                    },
                )
            )
    return events


def _federated_sim_swap_events(base_time: datetime) -> List[CanonicalEvent]:
    phone = "254700123456"
    device_id = "simswap-cross-01"
    events: List[CanonicalEvent] = [
        CanonicalEvent(
            event_type="SIM_SWAP_EVENT",
            occurred_at=base_time - timedelta(minutes=36),
            anchors={"phone_h": phone, "device_id": device_id, "service_id": "safaricom-mpesa"},
            payload={
                "phone": phone,
                "prev_sim_id": "sim-111",
                "new_sim_id": "sim-999",
                "reason": "urgent replacement",
                "provider": "Safaricom",
            },
        ),
        CanonicalEvent(
            event_type="LOGIN_EVENT",
            occurred_at=base_time - timedelta(minutes=29),
            anchors={
                "device_id": device_id,
                "endpoint": "bank:/login:POST",
                "ip": "102.89.14.77",
                "service_id": "equity-bank-ke",
            },
            payload={
                "username": "equity-retail-user",
                "outcome": "success",
                "user_agent": "Mozilla/5.0",
                "device_id": device_id,
                "provider": "cellular",
            },
        ),
        CanonicalEvent(
            event_type="TRANSACTION_EVENT",
            occurred_at=base_time - timedelta(minutes=22),
            anchors={
                "account_h": "EQ-ACC-8821",
                "device_id": device_id,
                "service_id": "equity-bank-ke",
            },
            payload={
                "account_from": "EQ-ACC-8821",
                "account_to": "MPESA-WALLET-77",
                "amount": 18500,
                "currency": "KES",
                "channel": "MOBILE",
                "provider": "M-Pesa",
                "device_id": device_id,
            },
        ),
        CanonicalEvent(
            event_type="TRANSACTION_EVENT",
            occurred_at=base_time - timedelta(minutes=14),
            anchors={
                "account_h": "MPESA-WALLET-77",
                "agent_id": "mpesa-agent-11",
                "service_id": "safaricom-mpesa",
            },
            payload={
                "account_from": "MPESA-WALLET-77",
                "account_to": "cashout",
                "amount": 17000,
                "currency": "KES",
                "channel": "AGENT_CASHOUT",
                "provider": "M-Pesa",
                "agent_id": "mpesa-agent-11",
            },
        ),
    ]
    return events


def _federated_malware_events(base_time: datetime) -> List[CanonicalEvent]:
    shared_ip = "50.16.16.211"
    shared_domain = "update-checkin-control.net"
    services = [
        ("kcb-bank-ke", "kcb-core-node-07", "threatfox"),
        ("equity-bank-ke", "equity-core-node-04", "feodo"),
        ("ke-cirt-hub", "kecirt-hunt-node-02", "malwarebazaar"),
    ]
    events: List[CanonicalEvent] = []
    for idx, (service_id, device_id, source) in enumerate(services):
        ts = base_time - timedelta(minutes=18 - idx * 4)
        events.append(
            CanonicalEvent(
                event_type="DFIR_FINDING_EVENT",
                occurred_at=ts,
                anchors={
                    "ip": shared_ip,
                    "domain": shared_domain,
                    "url": f"http://{shared_domain}/bootstrap.bin",
                    "device_id": device_id,
                    "service_id": service_id,
                },
                payload={
                    "host": device_id,
                    "artifact_name": "network_ioc_hunt",
                    "ip": shared_ip,
                    "domain": shared_domain,
                    "url": f"http://{shared_domain}/bootstrap.bin",
                    "device_id": device_id,
                    "service_id": service_id,
                    "finding_type": "botnet_c2_indicator",
                    "malware_family": "loader",
                    "severity": "high",
                    "confidence": 0.9 - (idx * 0.03),
                    "source": source,
                    "summary": f"Shared C2 infrastructure touching {service_id}",
                },
            )
        )
    return events


def _seed_federation_demo(db, *, scenario: str, base_time: datetime) -> None:
    now = base_time
    _upsert_demo_partners(db, now=now)

    touched: list[str] = []
    if scenario == "federated_vpn":
        partner_ids = ["kcb-bank-ke", "equity-bank-ke", "safaricom-ke"]
        for idx, partner_id in enumerate(partner_ids):
            _upsert_pattern(
                db,
                partner_id=partner_id,
                entity_key="ip:196.201.214.55",
                entity_type="ip",
                risk_score=0.86 - (idx * 0.03),
                fraud_family="VPN_REUSE",
                chain_score=0.74,
                risk_flags=["vpn_exit_node", "cross_agency_correlation", "shared_access_infrastructure"],
                now=now,
                minutes_ago=idx * 8,
            )
            touched.append(partner_id)
    elif scenario == "federated_sim_swap":
        pattern_rows = [
            ("safaricom-ke", "phone:+254700123456", "phone_h", 0.93, "SIM_SWAP", 0.91, ["sim_swap_velocity", "otp_takeover_risk", "cross_agency_correlation"]),
            ("equity-bank-ke", "phone:+254700123456", "phone_h", 0.88, "SIM_SWAP", 0.86, ["account_takeover_risk", "shared_actor_hash", "cross_agency_correlation"]),
            ("kcb-bank-ke", "phone:+254700123456", "phone_h", 0.84, "SIM_SWAP", 0.82, ["wallet_cashout_overlap", "shared_actor_hash", "cross_agency_correlation"]),
        ]
        for idx, row in enumerate(pattern_rows):
            _upsert_pattern(
                db,
                partner_id=row[0],
                entity_key=row[1],
                entity_type=row[2],
                risk_score=row[3],
                fraud_family=row[4],
                chain_score=row[5],
                risk_flags=row[6],
                now=now,
                minutes_ago=idx * 6,
            )
            touched.append(row[0])
    elif scenario == "federated_malware":
        pattern_rows = [
            ("kcb-bank-ke", "ip:50.16.16.211", "ip", 0.91, "MALWARE_C2", 0.79, ["shared_malware_ioc", "cross_agency_correlation", "banking_exposure"]),
            ("equity-bank-ke", "ip:50.16.16.211", "ip", 0.88, "MALWARE_C2", 0.76, ["shared_malware_ioc", "cross_agency_correlation", "banking_exposure"]),
            ("ke-cirt", "ip:50.16.16.211", "ip", 0.85, "MALWARE_C2", 0.74, ["shared_malware_ioc", "cross_agency_correlation", "national_monitoring"]),
            ("ke-cirt", "domain:update-checkin-control.net", "domain", 0.83, "MALWARE_C2", 0.71, ["c2_domain", "cross_agency_correlation", "national_monitoring"]),
        ]
        for idx, row in enumerate(pattern_rows):
            _upsert_pattern(
                db,
                partner_id=row[0],
                entity_key=row[1],
                entity_type=row[2],
                risk_score=row[3],
                fraud_family=row[4],
                chain_score=row[5],
                risk_flags=row[6],
                now=now,
                minutes_ago=idx * 5,
            )
            touched.append(row[0])

    db.flush()
    _refresh_partner_rollups(db, partner_ids=touched, now=now)
    db.commit()


def _source_api_key_for_event(event: CanonicalEvent) -> str:
    service_id = str(event.anchors.get("service_id") or event.payload.get("service_id") or "").lower()
    if event.event_type == "DDOS_SIGNAL_EVENT":
        return "kpa-secret-key"
    if event.event_type == "SIM_SWAP_EVENT":
        return "safaricom-secret-key"
    if event.event_type == "LOGIN_EVENT":
        if "safaricom" in service_id or "mpesa" in service_id:
            return "safaricom-secret-key"
        return "kcb-secret-key"
    if event.event_type == "TRANSACTION_EVENT":
        if "safaricom" in service_id or "mpesa" in service_id:
            return "safaricom-secret-key"
        return "kcb-secret-key"
    return "osint-secret-key"


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
    if normalized_scenario == "federated_vpn":
        events.extend(_federated_vpn_events(base_time))
    if normalized_scenario == "federated_sim_swap":
        events.extend(_federated_sim_swap_events(base_time))
    if normalized_scenario == "federated_malware":
        events.extend(_federated_malware_events(base_time))

    if mode == "kafka":
        producer = get_producer()
        if not producer:
            raise RuntimeError("Kafka producer unavailable (KAFKA_ENABLED=false?)")
        published = 0
        for ev in events:
            key = _source_api_key_for_event(ev)
            payload = {"source_api_key": key, "event": ev.model_dump()}
            producer.publish(topic=topic, key=f"demo:{published}", value=payload)
            published += 1
        producer.flush()
        if normalized_scenario.startswith("federated_"):
            db = SessionLocal()
            try:
                _seed_federation_demo(db, scenario=normalized_scenario, base_time=base_time)
            finally:
                db.close()
        print(f"[demo] scenario={normalized_scenario} total={len(events)} published={published} topic={topic}")
        return

    db = SessionLocal()
    svc = IngestionService(db, pseudonym_salt="demo-salt")
    accepted = 0
    duplicates = 0
    try:
        for ev in events:
            key = _source_api_key_for_event(ev)
            res = svc.ingest_event(event=ev, source_api_key=key)
            if res.status == "accepted":
                accepted += 1
            else:
                duplicates += 1
        if normalized_scenario.startswith("federated_"):
            _seed_federation_demo(db, scenario=normalized_scenario, base_time=base_time)
    finally:
        db.close()

    print(f"[demo] scenario={normalized_scenario} total={len(events)} accepted={accepted} duplicate={duplicates}")


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--seed-sources", action="store_true")
    p.add_argument(
        "--scenario",
        choices=[
            "ddos",
            "malware",
            "vpn",
            "sim_swap",
            "fraud",
            "ddos_vpn",
            "ddos_vpn_fraud",
            "federated_vpn",
            "federated_sim_swap",
            "federated_malware",
            "all",
        ],
        default="ddos_vpn",
    )
    p.add_argument("--mode", choices=["db", "kafka"], default="db")
    p.add_argument("--topic", default="sentinel.ingest")
    args = p.parse_args()

    run_demo(seed=args.seed_sources, scenario=args.scenario, mode=args.mode, topic=args.topic)


if __name__ == "__main__":
    main()
