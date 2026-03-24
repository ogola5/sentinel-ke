#!/usr/bin/env python3
"""
seed_demo_agencies.py — Sentinel-KE demo data seeder
=====================================================
Creates realistic Kenyan agency users, federation partners, and
cross-agency correlation seed patterns for the hackathon demo.

Usage:
    cd backend
    python scripts/seed_demo_agencies.py

    # Optional: custom admin password
    ADMIN_PASSWORD=secret python scripts/seed_demo_agencies.py

What it creates:
  Users (section analysts + central NCSC staff):
    cbk_analyst      / Demo@CBK2026!     (section: CBK)
    kecirt_analyst   / Demo@KECIRT2026!  (section: KE-CIRT)
    dci_analyst      / Demo@DCI2026!     (section: DCI)
    safaricom_soc    / Demo@SAF2026!     (section: SAFARICOM)
    equity_analyst   / Demo@EQT2026!     (section: EQUITY-BANK)
    ncsc_supervisor  / Demo@NCSC2026!    (central, supervisor role)

  Federation partners (for cross-agency correlation demo):
    equity-bank-ke, safaricom-ke, ke-cirt, cbk-ke, dci-ke

  Cross-agency patterns (same HMAC hash seen at 3 agencies):
    Simulates a SIM-Swap actor moving through Safaricom → Equity Bank → CBK
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend root is in path when running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.auth.models import AuthUser
from app.auth.security import generate_salt, hash_password
from app.federation.models import FederationPartner, FederationPattern
from app.ledger.db import SessionLocal
import app.db.registry  # noqa: F401 — registers all ORM models


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Agency definitions
# ---------------------------------------------------------------------------

AGENCIES = [
    {
        "username": "cbk_analyst",
        "display_name": "CBK SOC Analyst",
        "password": "Demo@CBK2026!",
        "role": "analyst",
        "access_level": "section",
        "section_code": "CBK",
        "scopes": ["events.read", "ai.read", "defense.read", "reports.read"],
    },
    {
        "username": "kecirt_analyst",
        "display_name": "KE-CIRT Threat Analyst",
        "password": "Demo@KECIRT2026!",
        "role": "analyst",
        "access_level": "section",
        "section_code": "KE-CIRT",
        "scopes": ["events.read", "ai.read", "defense.read", "defense.write", "reports.read"],
    },
    {
        "username": "dci_analyst",
        "display_name": "DCI Cyber Investigator",
        "password": "Demo@DCI2026!",
        "role": "analyst",
        "access_level": "section",
        "section_code": "DCI",
        "scopes": ["events.read", "ai.read", "cases.read", "reports.read"],
    },
    {
        "username": "safaricom_soc",
        "display_name": "Safaricom SOC Engineer",
        "password": "Demo@SAF2026!",
        "role": "analyst",
        "access_level": "section",
        "section_code": "SAFARICOM",
        "scopes": ["events.read", "events.write", "ai.read", "defense.read"],
    },
    {
        "username": "equity_analyst",
        "display_name": "Equity Bank Risk Analyst",
        "password": "Demo@EQT2026!",
        "role": "analyst",
        "access_level": "section",
        "section_code": "EQUITY-BANK",
        "scopes": ["events.read", "events.write", "ai.read", "defense.read"],
    },
    {
        "username": "ncsc_supervisor",
        "display_name": "NCSC National Supervisor",
        "password": "Demo@NCSC2026!",
        "role": "central_operator",
        "access_level": "central",
        "section_code": None,
        "scopes": [
            "events.read", "events.write", "ai.read", "ai.feedback.write",
            "defense.read", "defense.write", "cases.read", "campaigns.read",
            "graph.read", "legal.read", "economy.read", "metrics.read",
        ],
    },
]

# ---------------------------------------------------------------------------
# Federation partner definitions
# ---------------------------------------------------------------------------

# National correlation salt — same salt used by all partners so cross-agency
# HMAC hashes for the same entity match (privacy-preserving correlation)
NATIONAL_SALT = os.environ.get(
    "NATIONAL_SALT",
    "ke-sentinel-national-demo-salt-2026",
)

PARTNERS = [
    {
        "partner_id":   "equity-bank-ke",
        "partner_name": "Equity Bank Kenya",
        "partner_type": "bank",
        "api_key":      "eq-bank-api-key-demo-2026",
    },
    {
        "partner_id":   "safaricom-ke",
        "partner_name": "Safaricom PLC",
        "partner_type": "telco",
        "api_key":      "saf-telco-api-key-demo-2026",
    },
    {
        "partner_id":   "ke-cirt",
        "partner_name": "Kenya Computer Incident Response Team",
        "partner_type": "government",
        "api_key":      "kecirt-gov-api-key-demo-2026",
    },
    {
        "partner_id":   "cbk-ke",
        "partner_name": "Central Bank of Kenya",
        "partner_type": "government",
        "api_key":      "cbk-reg-api-key-demo-2026",
    },
    {
        "partner_id":   "dci-ke",
        "partner_name": "Directorate of Criminal Investigations",
        "partner_type": "government",
        "api_key":      "dci-law-api-key-demo-2026",
    },
]

# ---------------------------------------------------------------------------
# Cross-agency SIM-Swap attack chain (3 agencies see the same hashed actor)
# ---------------------------------------------------------------------------
# Raw entity keys (never leave their respective agencies — only hashes go to hub)
SIM_SWAP_ENTITIES = [
    "phone:+254700123456",   # primary SIM-swap target
    "account:EQ-ACC-8821",   # Equity Bank account
    "ip:196.201.214.55",     # VPN exit node
]


def _hmac_hash(entity_key: str, salt: str) -> str:
    """HMAC-SHA256(entity_key, national_salt) — same as edge_agent.py."""
    import hmac as _hmac
    return _hmac.new(salt.encode(), entity_key.encode(), hashlib.sha256).hexdigest()


def _api_key_hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _api_key_fingerprint(raw_key: str) -> str:
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    return f"{digest[:12]}…"


def build_demo_partner_hashes(
    entity_keys: list[str] | None = None,
    *,
    salt: str | None = None,
) -> dict[str, str]:
    keys = entity_keys or SIM_SWAP_ENTITIES
    corr_salt = salt or NATIONAL_SALT
    return {entity_key: _hmac_hash(entity_key, corr_salt) for entity_key in keys}


def seed_users(db) -> None:
    pepper = os.environ.get("AUTH_PASSWORD_PEPPER", "")
    created = 0
    skipped = 0
    for spec in AGENCIES:
        existing = db.query(AuthUser).filter(AuthUser.username == spec["username"]).first()
        if existing:
            skipped += 1
            continue
        salt = generate_salt()
        pw_hash = hash_password(spec["password"], salt, pepper=pepper)
        user = AuthUser(
            user_id=uuid.uuid4(),
            username=spec["username"],
            display_name=spec["display_name"],
            password_hash=pw_hash,
            password_salt=salt,
            role=spec["role"],
            access_level=spec["access_level"],
            section_code=spec["section_code"],
            scopes_json=spec["scopes"],
            is_active=True,
            created_by="demo-seed",
        )
        db.add(user)
        created += 1
    db.commit()
    print(f"[seed] Users: {created} created, {skipped} already existed")


def seed_partners(db) -> None:
    created = 0
    skipped = 0
    now = utcnow()
    for spec in PARTNERS:
        metadata = {
            "demo": True,
            "api_key_fingerprint": _api_key_fingerprint(spec["api_key"]),
            "region": "Kenya",
            "edge_status": {
                "last_heartbeat_at": now.isoformat(),
                "agent_version": "edge-agent-demo-v1",
                "model_version": "gnn-v2.1-demo",
                "artifact": {
                    "available": True,
                    "model_version": "gnn-v2.1-demo",
                    "trained_at": now.isoformat(),
                },
                "last_run_at": now.isoformat(),
                "last_run_status": "ok",
                "last_publish_status": "seeded",
                "run_count": 0,
                "data_source": "demo_seed",
                "hub_reachable": True,
                "capabilities": ["heartbeat", "pattern_publish", "local_gnn"],
            },
        }
        existing = db.query(FederationPartner).filter(
            FederationPartner.partner_id == spec["partner_id"]
        ).first()
        if existing:
            current_metadata = dict(existing.metadata_json or {})
            current_metadata.pop("raw_api_key_hint", None)
            current_metadata.update(metadata)
            existing.metadata_json = current_metadata
            existing.last_seen = now
            skipped += 1
            continue
        partner = FederationPartner(
            partner_id=spec["partner_id"],
            partner_name=spec["partner_name"],
            partner_type=spec["partner_type"],
            api_key_hash=_api_key_hash(spec["api_key"]),
            correlation_salt=NATIONAL_SALT,
            is_active=True,
            last_seen=now,
            metadata_json=metadata,
        )
        db.add(partner)
        created += 1
    db.commit()
    print(f"[seed] Partners: {created} created, {skipped} already existed")


def seed_cross_agency_patterns(db) -> None:
    """
    Seed federation patterns showing the same hashed SIM-swap actor
    appearing at three independent agencies in the same 2-hour window.
    This proves cross-agency correlation without sharing raw identifiers.
    """
    now = utcnow()
    window_start = now - timedelta(hours=2)
    window_end = now

    # Partners that 'observed' this actor
    observing_partners = ["equity-bank-ke", "safaricom-ke", "cbk-ke"]
    entity_key = SIM_SWAP_ENTITIES[0]  # same entity across all three
    entity_hash = _hmac_hash(entity_key, NATIONAL_SALT)

    created = 0
    partner_ids_touched: set[str] = set()
    for i, partner_id in enumerate(observing_partners):
        partner_ids_touched.add(partner_id)
        risk_scores = [0.91, 0.87, 0.83]
        # Check if pattern already seeded for this entity+partner
        existing = (
            db.query(FederationPattern)
            .filter(
                FederationPattern.partner_id == partner_id,
                FederationPattern.entity_key_hash == entity_hash,
            )
            .first()
        )
        if existing:
            existing.received_at = now - timedelta(minutes=i * 15)
            existing.window_start = window_start
            existing.window_end = window_end
            existing.gnn_model_version = "gnn-v2.1-demo"
            existing.entity_type = "phone_h"
            existing.risk_score = risk_scores[i]
            existing.uncertainty = 0.04
            existing.fraud_family = "SIM_SWAP"
            existing.chain_score = 0.88
            existing.risk_flags = ["sim_swap_velocity", "cross_agency_correlation", "account_takeover_risk"]
            existing.summary_json = {
                "total_scored": 1247 + i * 312,
                "high_risk_count": 3 + i,
                "mean_risk": round(0.72 + i * 0.02, 3),
                "window_key": "W2h",
            }
            existing.schema_version = "1.0"
            continue

        pattern = FederationPattern(
            id=uuid.uuid4(),
            partner_id=partner_id,
            received_at=now - timedelta(minutes=i * 15),
            window_start=window_start,
            window_end=window_end,
            gnn_model_version="gnn-v2.1-demo",
            entity_key_hash=entity_hash,
            entity_type="phone_h",
            risk_score=risk_scores[i],
            uncertainty=0.04,
            fraud_family="SIM_SWAP",
            chain_score=0.88,
            risk_flags=["sim_swap_velocity", "cross_agency_correlation", "account_takeover_risk"],
            summary_json={
                "total_scored": 1247 + i * 312,
                "high_risk_count": 3 + i,
                "mean_risk": round(0.72 + i * 0.02, 3),
                "window_key": "W2h",
            },
            schema_version="1.0",
        )
        db.add(pattern)
        created += 1

    # Also seed IP cross-correlation (VPN exit node seen at Safaricom + KE-CIRT)
    ip_hash = _hmac_hash(SIM_SWAP_ENTITIES[2], NATIONAL_SALT)
    for partner_id in ["safaricom-ke", "ke-cirt"]:
        partner_ids_touched.add(partner_id)
        existing = (
            db.query(FederationPattern)
            .filter(
                FederationPattern.partner_id == partner_id,
                FederationPattern.entity_key_hash == ip_hash,
            )
            .first()
        )
        if existing:
            existing.received_at = now - timedelta(minutes=45)
            existing.window_start = window_start
            existing.window_end = window_end
            existing.gnn_model_version = "gnn-v2.1-demo"
            existing.entity_type = "ip"
            existing.risk_score = 0.79
            existing.uncertainty = 0.07
            existing.fraud_family = "VPN_FRAUD"
            existing.chain_score = 0.71
            existing.risk_flags = ["vpn_exit_node", "ddos_source", "cross_agency_correlation"]
            existing.summary_json = {
                "total_scored": 891,
                "high_risk_count": 7,
                "mean_risk": 0.68,
                "window_key": "W2h",
            }
            existing.schema_version = "1.0"
            continue
        pattern = FederationPattern(
            id=uuid.uuid4(),
            partner_id=partner_id,
            received_at=now - timedelta(minutes=45),
            window_start=window_start,
            window_end=window_end,
            gnn_model_version="gnn-v2.1-demo",
            entity_key_hash=ip_hash,
            entity_type="ip",
            risk_score=0.79,
            uncertainty=0.07,
            fraud_family="VPN_FRAUD",
            chain_score=0.71,
            risk_flags=["vpn_exit_node", "ddos_source", "cross_agency_correlation"],
            summary_json={
                "total_scored": 891,
                "high_risk_count": 7,
                "mean_risk": 0.68,
                "window_key": "W2h",
            },
            schema_version="1.0",
        )
        db.add(pattern)
        created += 1

    db.flush()

    for partner_id in sorted(partner_ids_touched):
        partner = (
            db.query(FederationPartner)
            .filter(FederationPartner.partner_id == partner_id)
            .first()
        )
        if not partner:
            continue
        total_patterns = (
            db.query(FederationPattern)
            .filter(FederationPattern.partner_id == partner_id)
            .count()
        )
        metadata = dict(partner.metadata_json or {})
        metadata["edge_status"] = {
            "last_heartbeat_at": now.isoformat(),
            "agent_version": "edge-agent-demo-v1",
            "model_version": "gnn-v2.1-demo",
            "artifact": {
                "available": True,
                "model_version": "gnn-v2.1-demo",
                "trained_at": now.isoformat(),
            },
            "last_run_at": now.isoformat(),
            "last_run_status": "ok",
            "last_publish_status": "published",
            "run_count": max(1, total_patterns),
            "data_source": "demo_seed",
            "hub_reachable": True,
            "capabilities": ["heartbeat", "pattern_publish", "local_gnn"],
        }
        partner.metadata_json = metadata
        partner.last_seen = now
        partner.last_pattern_at = now
        partner.total_patterns = total_patterns

    db.commit()
    print(f"[seed] Cross-agency patterns: {created} created")
    print(f"       Correlation hash (SIM-swap actor): {entity_hash[:16]}...")
    print(f"       Seen at: equity-bank-ke, safaricom-ke, cbk-ke")
    print(f"       → POST /v1/federation/correlations to see this in the UI")


def deactivate_stale_demo_partners(db) -> int:
    canonical_ids = {spec["partner_id"] for spec in PARTNERS}
    stale = (
        db.query(FederationPartner)
        .filter(FederationPartner.is_active.is_(True))
        .all()
    )
    deactivated = 0
    for partner in stale:
        if partner.partner_id in canonical_ids:
            continue
        if partner.partner_id.startswith("TMP") or partner.partner_id.startswith("demo-edge-"):
            partner.is_active = False
            deactivated += 1
    if deactivated:
        db.commit()
    return deactivated


def _credentials_manifest(*, include_secrets: bool) -> dict[str, object]:
    users = []
    for spec in AGENCIES:
        item = {
            "username": spec["username"],
            "display_name": spec["display_name"],
            "role": spec["role"],
            "access_level": spec["access_level"],
            "section_code": spec["section_code"],
        }
        if include_secrets:
            item["password"] = spec["password"]
        users.append(item)

    partners = []
    for spec in PARTNERS:
        item = {
            "partner_id": spec["partner_id"],
            "partner_name": spec["partner_name"],
            "partner_type": spec["partner_type"],
            "api_key_fingerprint": _api_key_fingerprint(spec["api_key"]),
        }
        if include_secrets:
            item["api_key"] = spec["api_key"]
        partners.append(item)

    return {
        "generated_at": utcnow().isoformat(),
        "include_secrets": include_secrets,
        "users": users,
        "partners": partners,
    }


def _print_credentials_summary(*, include_secrets: bool) -> None:
    print()
    print("Demo login accounts:")
    print("-" * 40)
    for spec in AGENCIES:
        sc = f" ({spec['section_code']})" if spec["section_code"] else " (central)"
        if include_secrets:
            print(f"  {spec['username']:<22} {spec['password']}{sc}")
        else:
            print(f"  {spec['username']:<22} password available via --show-secrets{sc}")

    print()
    print("Federation partners:")
    print("-" * 40)
    for spec in PARTNERS:
        fp = _api_key_fingerprint(spec["api_key"])
        if include_secrets:
            print(f"  {spec['partner_id']:<18} api_key={spec['api_key']}  (fingerprint {fp})")
        else:
            print(f"  {spec['partner_id']:<18} api_key fingerprint {fp}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Seed Sentinel-KE demo agencies and partner correlations")
    parser.add_argument(
        "--show-secrets",
        action="store_true",
        help="Print demo passwords and partner API keys to stdout",
    )
    parser.add_argument(
        "--write-credentials",
        default="",
        help="Optional path to write a JSON credential manifest for rehearsals",
    )
    parser.add_argument(
        "--deactivate-stale-demo-partners",
        action="store_true",
        help="Deactivate temporary TMP*/demo-edge* partners outside the canonical demo set",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Sentinel-KE — Agency Demo Seed")
    print("=" * 60)
    db = SessionLocal()
    try:
        if args.deactivate_stale_demo_partners:
            removed = deactivate_stale_demo_partners(db)
            print(f"[seed] Stale demo partners deactivated: {removed}")
        seed_users(db)
        seed_partners(db)
        seed_cross_agency_patterns(db)
        manifest = _credentials_manifest(include_secrets=args.show_secrets)
        _print_credentials_summary(include_secrets=args.show_secrets)
        if args.write_credentials:
            out_path = Path(args.write_credentials)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                f"{json.dumps(manifest, indent=2)}\n",
                encoding="utf-8",
            )
            print()
            print(f"Credential manifest written to {out_path}")
        print()
        print("Cross-agency correlation:")
        print("  GET /v1/federation/correlations   ← 3-agency SIM-swap signal")
        print("  GET /v1/federation/partners        ← 5 registered agencies")
    finally:
        db.close()


if __name__ == "__main__":
    main()
