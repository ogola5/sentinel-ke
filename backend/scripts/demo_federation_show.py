#!/usr/bin/env python3
"""
demo_federation_show.py — Live HMAC federation demo for presentations
======================================================================
Shows judges exactly how Kenya's privacy-preserving federated threat
intelligence works:

  1. Raw entity (phone number) STAYS at Safaricom — never sent anywhere
  2. HMAC-SHA256(entity_key, national_salt) produces a deterministic hash
  3. Same entity at Equity Bank produces the SAME hash
  4. The hub correlates by hash — sees "3 agencies flagged the same actor"
     without ever learning who the actor is

Usage:
    cd backend
    python scripts/demo_federation_show.py

    # Show with custom entities
    python scripts/demo_federation_show.py --entity "phone:+254700123456"

    # Query live DB for cross-agency correlations
    python scripts/demo_federation_show.py --live
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

NATIONAL_SALT = os.environ.get("NATIONAL_SALT", "ke-sentinel-national-demo-salt-2026")

# Demo entities — realistic Kenyan identifiers
DEMO_ENTITIES = [
    ("phone:+254700123456",  "Safaricom",    "SIM_SWAP",    0.91),
    ("account:EQ-ACC-8821",  "Equity Bank",  "FRAUD_MULE",  0.87),
    ("ip:196.201.214.55",    "KE-CIRT",      "VPN_FRAUD",   0.79),
    ("phone:+254700123456",  "CBK",          "SIM_SWAP",    0.83),  # same entity, 3rd agency
]

SEPARATOR = "─" * 70


def _hmac_hash(entity_key: str, salt: str) -> str:
    return hmac.new(salt.encode(), entity_key.encode(), hashlib.sha256).hexdigest()


def _truncate(s: str, n: int = 16) -> str:
    return s[:n] + "…"


def build_multi_agency_correlations(
    entities: list[tuple[str, str, str, float]] | None = None,
    *,
    salt: str | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """
    Build deterministic demo rows and correlation summaries for presentation
    screens, tests, and scripted demos.
    """
    source_entities = entities or DEMO_ENTITIES
    corr_salt = salt or NATIONAL_SALT
    rows: list[dict[str, object]] = []
    grouped: dict[str, list[dict[str, object]]] = {}

    for entity_key, agency, family, risk in source_entities:
        entity_hash = _hmac_hash(entity_key, corr_salt)
        row = {
            "agency": agency,
            "entity_key": entity_key,
            "display_key": entity_key[:14] + "…" + " [LOCAL]",
            "hash": entity_hash,
            "short_hash": entity_hash[:18] + "…",
            "risk": float(risk),
            "family": family,
        }
        rows.append(row)
        grouped.setdefault(entity_hash, []).append(row)

    correlations: list[dict[str, object]] = []
    for entity_hash, matches in grouped.items():
        if len(matches) < 2:
            continue
        correlations.append(
            {
                "entity_hash": entity_hash,
                "short_hash": entity_hash[:16] + "…",
                "agencies": [str(item["agency"]) for item in matches],
                "avg_risk": sum(float(item["risk"]) for item in matches) / len(matches),
                "family": str(matches[0]["family"]),
                "sources": len(matches),
            }
        )
    return rows, correlations


def _print_slow(text: str, delay: float = 0.02) -> None:
    """Print character by character for dramatic effect."""
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def show_hash_demo(entity: str, delay: bool = True) -> None:
    print()
    print(SEPARATOR)
    print("  SENTINEL-KE — Privacy-Preserving Federation Protocol")
    print(SEPARATOR)
    print()

    fn = _print_slow if delay else print

    print("  Step 1: Raw entity stays on-premise at the agency")
    print(f"          Raw identifier  : {entity}")
    print(f"          National salt   : {NATIONAL_SALT[:20]}…  (shared securely at onboarding)")
    print()
    time.sleep(0.5 if delay else 0)

    hash_val = _hmac_hash(entity, NATIONAL_SALT)
    print("  Step 2: Agency edge agent computes HMAC-SHA256(entity, salt)")
    print(f"          HMAC-SHA256     : ", end="")
    if delay:
        _print_slow(hash_val, delay=0.01)
    else:
        print(hash_val)
    print()
    time.sleep(0.3 if delay else 0)

    print("  Step 3: Only the HASH is sent to NCSC hub — not the raw key")
    print("          POST /v1/federation/patterns")
    print("          {")
    print(f'            "entity_key_hash": "{hash_val[:32]}…",')
    print(f'            "entity_type":     "phone_h",')
    print(f'            "risk_score":      0.91,')
    print(f'            "fraud_family":    "SIM_SWAP"')
    print("          }")
    print()
    time.sleep(0.5 if delay else 0)

    # Show same entity from two other agencies → same hash
    print("  Step 4: Equity Bank GNN independently flags the same actor")
    hash_val_equity = _hmac_hash(entity, NATIONAL_SALT)
    print(f"          Their HMAC-SHA256: {hash_val_equity[:32]}…")
    match = hash_val[:32] == hash_val_equity[:32]
    print(f"          Match with Safaricom hash? {'✓ YES — same actor!' if match else '✗ NO'}")
    print()
    time.sleep(0.3 if delay else 0)

    print("  Step 5: Hub correlates — 3 agencies flagged same hash in 2h window")
    print("          GET /v1/federation/correlations")
    print("          → entity_key_hash:", hash_val[:24] + "…")
    print("          → agencies: Safaricom, Equity Bank, CBK")
    print("          → avg_risk_score: 0.87  |  fraud_family: SIM_SWAP")
    print("          → confidence: CONFIRMED (3 independent sources)")
    print()
    print("  What the hub NEVER learns:")
    print("    ✗  The actual phone number (+254700123456)")
    print("    ✗  The person's name or account details")
    print("    ✗  Raw transaction history")
    print()
    print("  What the hub DOES learn:")
    print("    ✓  Same risk pattern seen across 3 agencies")
    print("    ✓  Fraud family: SIM_SWAP chain")
    print("    ✓  Risk score: 0.87 — high confidence containment candidate")
    print()
    print(SEPARATOR)


def show_multi_agency_table(delay: bool = True) -> None:
    rows, correlations = build_multi_agency_correlations()
    print()
    print(SEPARATOR)
    print("  CROSS-AGENCY FEDERATION PATTERNS (last 2 hours)")
    print(SEPARATOR)
    print()
    print(f"  {'Agency':<18} {'Entity (local)':<28} {'Hash (sent to hub)':<20} {'Risk':<6} {'Family'}")
    print(f"  {'─'*18} {'─'*28} {'─'*20} {'─'*6} {'─'*12}")

    for entry in rows:
        row = (
            f"  {str(entry['agency']):<18} {str(entry['display_key']):<28} "
            f"{str(entry['short_hash']):<20} {float(entry['risk']):<6.2f} {str(entry['family'])}"
        )
        if delay:
            _print_slow(row, delay=0.008)
        else:
            print(row)
        time.sleep(0.1 if delay else 0)

    print()
    if correlations:
        print(f"  ✓ {len(correlations)} cross-agency correlation(s) detected:")
        for corr in correlations:
            names = ", ".join(corr["agencies"])
            print(f"    Hash {corr['short_hash']}  →  {names}")
            print(
                f"    Avg risk: {float(corr['avg_risk']):.2f}  |  {corr['family']}  |  "
                f"{int(corr['sources'])} independent sources"
            )
    print()
    print(SEPARATOR)


def query_live_db() -> None:
    """Query the actual federation DB and print real correlations."""
    import app.db.registry  # noqa: F401
    from app.ledger.db import SessionLocal
    from app.federation.models import FederationPattern, FederationPartner
    from sqlalchemy import func

    db = SessionLocal()
    try:
        # Replicate the correlation query from api/federation.py
        correlations = (
            db.query(
                FederationPattern.entity_key_hash,
                FederationPattern.entity_type,
                func.count(FederationPattern.partner_id.distinct()).label("agency_count"),
                func.avg(FederationPattern.risk_score).label("avg_risk"),
                func.max(FederationPattern.fraud_family).label("fraud_family"),
            )
            .group_by(FederationPattern.entity_key_hash, FederationPattern.entity_type)
            .having(func.count(FederationPattern.partner_id.distinct()) >= 2)
            .order_by(func.avg(FederationPattern.risk_score).desc())
            .limit(10)
            .all()
        )

        partner_count = db.query(FederationPartner).filter(FederationPartner.is_active.is_(True)).count()
        pattern_count = db.query(FederationPattern).count()

        print()
        print(SEPARATOR)
        print("  LIVE DATABASE — FEDERATION STATUS")
        print(SEPARATOR)
        print(f"  Registered agencies : {partner_count}")
        print(f"  Total patterns      : {pattern_count:,}")
        print(f"  Cross-agency hits   : {len(correlations)}")
        print()

        if correlations:
            print(f"  {'Hash (truncated)':<22} {'Type':<12} {'Agencies':<10} {'Avg Risk':<10} {'Family'}")
            print(f"  {'─'*22} {'─'*12} {'─'*10} {'─'*10} {'─'*15}")
            for row in correlations:
                print(
                    f"  {row.entity_key_hash[:20]}…  {row.entity_type or '?':<12} "
                    f"{row.agency_count:<10} {float(row.avg_risk or 0):<10.3f} {row.fraud_family or '?'}"
                )
        else:
            print("  No cross-agency correlations yet.")
            print("  Run: python scripts/seed_demo_agencies.py")

        print()
        print(SEPARATOR)
    finally:
        db.close()


def presenter_talking_points() -> list[str]:
    return [
        "Same raw entity plus the same national salt produces the same hash at every agency.",
        "The hub correlates by hash, fraud family, and risk score; raw identifiers stay local.",
        "Live partner heartbeat and correlation rows are the proof surface to show judges.",
        "Use benchmark and operational-probe artifacts for any performance or impact figures.",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live HMAC federation demo for presentations"
    )
    parser.add_argument(
        "--entity",
        default="phone:+254700123456",
        help="Entity key to hash (default: phone:+254700123456)",
    )
    parser.add_argument(
        "--no-delay",
        action="store_true",
        help="Disable typing animation (useful for non-interactive runs)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Query live DB and show real correlation data",
    )
    parser.add_argument(
        "--table-only",
        action="store_true",
        help="Show only the multi-agency table (skip single-entity walkthrough)",
    )
    args = parser.parse_args()

    delay = not args.no_delay

    if not args.table_only:
        show_hash_demo(args.entity, delay=delay)

    show_multi_agency_table(delay=delay)

    if args.live:
        query_live_db()

    print()
    print("  Presenter talking points:")
    print("  ─────────────────────────")
    for idx, item in enumerate(presenter_talking_points(), start=1):
        print(f"  {idx}. {item}")
        print()


if __name__ == "__main__":
    main()
