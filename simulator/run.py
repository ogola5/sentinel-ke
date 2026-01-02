from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from app.ingestion.schemas import CanonicalEvent
from app.ingestion.service import IngestionService
from app.ledger.db import SessionLocal
from app.ledger.seed_sources import seed as seed_sources


SCENARIO_DIR = os.path.join(os.path.dirname(__file__), "scenarios")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_base_time(value: str | None) -> datetime:
    if not value or value.lower() == "now":
        return _now_utc()
    return datetime.fromisoformat(value)


def _default_scenario(name: str) -> Dict[str, Any]:
    if name == "ddos_rehearsal":
        return {
            "name": name,
            "description": "Moderate DDoS rehearsal bursts (no hard outage).",
            "source_api_key": "kpa-secret-key",
            "base_time": "now",
            "events": [
                {
                    "event_type": "DDOS_SIGNAL_EVENT",
                    "offset_sec": -1200,
                    "repeat": 40,
                    "repeat_every_sec": 15,
                    "ip_pool_prefix": "198.51.100.",
                    "ip_pool_count": 20,
                    "anchors": {"service_id": "kplc", "endpoint": "kplc:/pay:POST"},
                    "payload": {
                        "service_id": "kplc",
                        "endpoint": "/pay",
                        "req_rate": 120,
                        "unique_ips_count": 20,
                        "error_rate": 0.01,
                        "avg_latency_ms": 60,
                        "endpoint_convergence": 0.35,
                        "asn_concentration": 0.25,
                    },
                },
                {
                    "event_type": "DDOS_SIGNAL_EVENT",
                    "offset_sec": -180,
                    "repeat": 120,
                    "repeat_every_sec": 2,
                    "ip_pool_prefix": "198.51.100.",
                    "ip_pool_count": 50,
                    "anchors": {"service_id": "kplc", "endpoint": "kplc:/pay:POST"},
                    "payload": {
                        "service_id": "kplc",
                        "endpoint": "/pay",
                        "req_rate": 320,
                        "unique_ips_count": 50,
                        "error_rate": 0.03,
                        "avg_latency_ms": 90,
                        "endpoint_convergence": 0.55,
                        "asn_concentration": 0.45,
                    },
                },
            ],
        }
    if name == "ddos_active":
        return {
            "name": name,
            "description": "High-volume DDoS burst with strong convergence.",
            "source_api_key": "kpa-secret-key",
            "base_time": "now",
            "events": [
                {
                    "event_type": "DDOS_SIGNAL_EVENT",
                    "offset_sec": -900,
                    "repeat": 20,
                    "repeat_every_sec": 30,
                    "ip_pool_prefix": "203.0.113.",
                    "ip_pool_count": 15,
                    "anchors": {"service_id": "kplc", "endpoint": "kplc:/login:POST"},
                    "payload": {
                        "service_id": "kplc",
                        "endpoint": "/login",
                        "req_rate": 90,
                        "unique_ips_count": 15,
                        "error_rate": 0.02,
                        "avg_latency_ms": 70,
                        "endpoint_convergence": 0.4,
                        "asn_concentration": 0.3,
                    },
                },
                {
                    "event_type": "DDOS_SIGNAL_EVENT",
                    "offset_sec": -120,
                    "repeat": 300,
                    "repeat_every_sec": 1,
                    "ip_pool_prefix": "203.0.113.",
                    "ip_pool_count": 200,
                    "anchors": {"service_id": "kplc", "endpoint": "kplc:/login:POST"},
                    "payload": {
                        "service_id": "kplc",
                        "endpoint": "/login",
                        "req_rate": 1200,
                        "unique_ips_count": 200,
                        "error_rate": 0.08,
                        "avg_latency_ms": 250,
                        "endpoint_convergence": 0.8,
                        "asn_concentration": 0.7,
                    },
                },
            ],
        }
    if name == "vpn_rotation":
        return {
            "name": name,
            "description": "VPN rotation: multiple IPs hitting same endpoint.",
            "source_api_key": "osint-secret-key",
            "base_time": "now",
            "events": [
                {
                    "event_type": "LOGIN_EVENT",
                    "offset_sec": -1800,
                    "repeat": 30,
                    "repeat_every_sec": 40,
                    "ip_pool_prefix": "102.168.1.",
                    "ip_pool_count": 6,
                    "anchors": {"endpoint": "portal:/login:POST", "device_id": "device-demo-1"},
                    "payload": {
                        "username": "demo-user",
                        "outcome": "success",
                        "user_agent": "Mozilla/5.0",
                        "provider": "demo-vpn",
                    },
                }
            ],
        }
    if name == "fraud_chain":
        return {
            "name": name,
            "description": "SIM swap -> login -> transaction chain.",
            "source_api_key": "safaricom-secret-key",
            "base_time": "now",
            "events": [
                {
                    "event_type": "SIM_SWAP_EVENT",
                    "offset_sec": -3600,
                    "repeat": 3,
                    "repeat_every_sec": 600,
                    "anchors": {"phone_h": "254700000001", "device_id": "sim-device-1"},
                    "payload": {
                        "phone": "254700000001",
                        "prev_sim_id": "sim-001",
                        "new_sim_id": "sim-002",
                        "reason": "re-issue",
                    },
                },
                {
                    "event_type": "LOGIN_EVENT",
                    "offset_sec": -3300,
                    "repeat": 6,
                    "repeat_every_sec": 300,
                    "ip_pool_prefix": "41.90.1.",
                    "ip_pool_count": 3,
                    "anchors": {"device_id": "sim-device-1", "endpoint": "bank:/login:POST"},
                    "payload": {
                        "username": "user-001",
                        "outcome": "success",
                        "user_agent": "Mozilla/5.0",
                        "device_id": "sim-device-1",
                        "provider": "cellular",
                    },
                },
                {
                    "event_type": "TRANSACTION_EVENT",
                    "offset_sec": -3000,
                    "repeat": 6,
                    "repeat_every_sec": 300,
                    "ip_pool_prefix": "41.90.1.",
                    "ip_pool_count": 3,
                    "anchors": {"device_id": "sim-device-1", "account_h": "acct-0001"},
                    "payload": {
                        "account_from": "acct-0001",
                        "account_to": "acct-9001",
                        "amount": 5000,
                        "currency": "KES",
                        "channel": "MOBILE",
                        "device_id": "sim-device-1",
                    },
                },
            ],
        }
    if name == "full_demo":
        ddos = _default_scenario("ddos_active")
        vpn = _default_scenario("vpn_rotation")
        fraud = _default_scenario("fraud_chain")
        return {
            "name": name,
            "description": "DDoS + VPN + fraud combined demo.",
            "source_api_key": "kpa-secret-key",
            "base_time": "now",
            "events": ddos["events"] + vpn["events"] + fraud["events"],
        }
    raise ValueError(f"Unknown scenario: {name}")


def _load_scenario(name: str) -> Dict[str, Any]:
    path = os.path.join(SCENARIO_DIR, f"{name}.json")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return _default_scenario(name)


def _build_ip_pool(spec: Dict[str, Any]) -> List[str]:
    if spec.get("ip_pool"):
        return list(spec["ip_pool"])
    prefix = spec.get("ip_pool_prefix")
    count = spec.get("ip_pool_count")
    if prefix and count:
        return [f"{prefix}{i+1}" for i in range(int(count))]
    return []


def _expand_events(spec: Dict[str, Any], base_time: datetime) -> List[CanonicalEvent]:
    out: List[CanonicalEvent] = []
    offset = int(spec.get("offset_sec", 0))
    repeat = int(spec.get("repeat", 1))
    step = int(spec.get("repeat_every_sec", 0))
    ip_pool = _build_ip_pool(spec)
    anchors_base = dict(spec.get("anchors") or {})
    payload_base = dict(spec.get("payload") or {})
    event_type = spec["event_type"]

    for i in range(repeat):
        ts = base_time + timedelta(seconds=offset + (i * step))
        anchors = dict(anchors_base)
        if ip_pool:
            anchors["ip"] = ip_pool[i % len(ip_pool)]
        payload = dict(payload_base)
        out.append(
            CanonicalEvent(
                event_type=event_type,
                occurred_at=ts,
                anchors=anchors,
                payload=payload,
            )
        )
    return out


def run_scenario(name: str, *, seed: bool = False, dry_run: bool = False) -> None:
    if seed:
        seed_sources()

    scenario = _load_scenario(name)
    base_time = _parse_base_time(scenario.get("base_time"))
    events: List[CanonicalEvent] = []
    for spec in scenario.get("events", []):
        events.extend(_expand_events(spec, base_time))

    if dry_run:
        print(f"[demo] scenario={name} events={len(events)} source={scenario.get('source_api_key')}")
        return

    source_api_key = scenario.get("source_api_key")
    if not source_api_key:
        raise ValueError("scenario missing source_api_key")

    db = SessionLocal()
    svc = IngestionService(db, pseudonym_salt="demo-salt")
    accepted = 0
    duplicates = 0
    try:
        for ev in events:
            res = svc.ingest_event(event=ev, source_api_key=source_api_key)
            if res.status == "accepted":
                accepted += 1
            else:
                duplicates += 1
    finally:
        db.close()

    print(
        f"[demo] scenario={name} total={len(events)} accepted={accepted} duplicate={duplicates}"
    )


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="ddos_rehearsal")
    p.add_argument("--seed-sources", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    run_scenario(args.scenario, seed=args.seed_sources, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
