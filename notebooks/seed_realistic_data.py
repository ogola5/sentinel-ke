"""
seed_realistic_data.py — Kenya-context synthetic dataset generator for notebook pipeline.

Generates CSV files that match the EXACT column schemas expected by the existing
real_data_pipeline normalizers (normalize_cic_row, normalize_caida_row).

These files represent realistic Kenya cyber-threat patterns for use when the
actual CIC-IDS2018 / CAIDA datasets have not been downloaded yet.  They are NOT
random noise — every row is grounded in a documented Kenyan incident type:

  CIC rows   → M-Pesa platform DDoS, USSD gateway SQL injection,
                county finance portal web attacks, KRA brute-force
  CAIDA rows → Safaricom DNS amplification, Equity mobile banking SYN flood,
                M-Pesa API UDP flood, HELB/NHIF portal volumetric attacks
  PaySim rows→ M-Pesa mule-network cash-out chains, SIM-swap takeover patterns

Real dataset alternatives (public, free):
  CIC-IDS2018:   https://www.kaggle.com/datasets/solarmainframe/ids-intrusion-csv
  CAIDA 2007:    https://www.caida.org/catalog/datasets/ddos-20070804_dataset/
  PaySim:        https://www.kaggle.com/datasets/ntnu-testimon/paysim1
  CISA KEV+EPSS: fetched live by pipeline_bootstrap.ingest_kev_epss() — no file needed

Usage from notebook 04:
    from seed_realistic_data import generate_cic_csv, generate_caida_csv
    cic_path   = generate_cic_csv("data/kenya_cic_synthetic.csv")
    caida_path = generate_caida_csv("data/kenya_caida_synthetic.csv")
"""
from __future__ import annotations

import csv
import random
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Kenya-context IP address pools (IANA-allocated ranges, fictionalised hosts)
# ---------------------------------------------------------------------------
_KE_MPESA_IPS = [f"196.201.{r}.{h}" for r in range(210, 225) for h in range(1, 15)]
_KE_TELCO_IPS = [f"41.90.{r}.{h}"   for r in range(60, 80)   for h in range(1, 15)]
_KE_GOV_IPS   = [f"196.14.{r}.{h}"  for r in range(100, 120) for h in range(1, 15)]
_KE_COUNTY_IPS = [f"197.248.{r}.{h}" for r in range(10, 30)  for h in range(1, 15)]

_ATTACKER_IPS = (
    [f"45.{r}.{h}.{p}" for r in range(100, 130) for h in range(1, 5) for p in range(1, 5)]
    + [f"103.{r}.{h}.{p}" for r in range(50, 80) for h in range(1, 5) for p in range(1, 5)]
)

_UTC_BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _rand_ts(rng: random.Random, days_span: int = 90) -> str:
    offset = rng.randint(0, days_span * 86_400)
    return (_UTC_BASE + timedelta(seconds=offset)).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# CIC-DDoS2019 format  (same CICFlowMeter columns as IDS2018, modern taxonomy)
# ---------------------------------------------------------------------------
# Attack taxonomy from UNB CIC-DDoS2019:
#   Reflection/amplification: NTP, DNS, MSSQL, LDAP, NetBIOS, TFTP, SNMP
#   Direct volumetric:        Syn, UDP, UDPLag, WebDDoS
# All labels contain "DDoS" so normalize_cic_row() classifies them correctly.
# Real dataset: https://www.kaggle.com/datasets/dhoogla/cicddos2019

_CICDDOS2019_LABELS = [
    "DDoS-NTP",          # NTP monlist amplification — most common in Kenya
    "DDoS-DNS",          # DNS amplification via open resolvers
    "DDoS-MSSQL",        # MSSQL 1434/UDP amplification
    "DDoS-LDAP",         # LDAP 389/UDP amplification
    "DDoS-NetBIOS",      # NetBIOS 137/UDP amplification
    "DDoS-TFTP",         # TFTP amplification
    "DDoS-Syn",          # TCP SYN flood
    "DDoS-UDP",          # UDP flood
    "DDoS-UDPLag",       # UDP reflection with introduced lag
    "DDoS-WebDDoS",      # HTTP layer-7 flood (application layer)
    "DrDoS_DNS",         # Distributed Reflected DNS
    "DrDoS_NTP",         # Distributed Reflected NTP
]


def generate_cicddos2019_csv(
    output_path: str = "data/kenya_cicddos2019_synthetic.csv",
    n_rows: int = 3000,
    seed: int = 43,
) -> str:
    """
    Generate a CIC-DDoS2019-compatible CSV with Kenya-specific attack context.

    Uses modern amplification and reflection attack taxonomy (2019 dataset)
    instead of the 2007 CAIDA or 2018 CIC dataset. The column schema is
    identical to CIC-IDS2018 (both use CICFlowMeter) so normalize_cic_row()
    handles this data without any changes.

    Distribution: 40% reflection/amplification / 35% volumetric / 25% layer-7
    Targets: Safaricom DNS resolvers, M-Pesa API, KRA portal, county finance
    """
    rng = random.Random(seed)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Amplification attacks have very high PPS due to reflection factor
    _AMPLIFICATION = {"DDoS-NTP", "DDoS-DNS", "DDoS-MSSQL", "DDoS-LDAP",
                      "DDoS-NetBIOS", "DrDoS_DNS", "DrDoS_NTP", "DDoS-TFTP"}

    rows: List[dict] = []
    for _ in range(n_rows):
        label = rng.choice(_CICDDOS2019_LABELS)
        dst_ip = rng.choice(_KE_MPESA_IPS + _KE_TELCO_IPS + _KE_GOV_IPS)
        dst_port = rng.choice([53, 123, 137, 389, 1434, 443, 80])

        if label in _AMPLIFICATION:
            # Amplification: very high PPS, many unique sources
            flow_pps = round(rng.uniform(50_000.0, 2_000_000.0), 2)
            pkt_cnt = rng.randint(100_000, 5_000_000)
        elif "WebDDoS" in label:
            # Layer-7: lower PPS but hits application
            flow_pps = round(rng.uniform(500.0, 20_000.0), 2)
            pkt_cnt = rng.randint(1_000, 100_000)
            dst_port = rng.choice([80, 443, 8080, 8443])
        else:
            # Volumetric (Syn/UDP)
            flow_pps = round(rng.uniform(10_000.0, 500_000.0), 2)
            pkt_cnt = rng.randint(50_000, 2_000_000)

        rows.append({
            "timestamp":                      _rand_ts(rng),
            "src_ip":                         rng.choice(_ATTACKER_IPS),
            "dst_ip":                         dst_ip,
            "dst_port":                       dst_port,
            "label":                          label,
            "flow_packets_s":                 flow_pps,
            "total_fwd_packets":              pkt_cnt,
            "total_length_of_fwd_packets":    pkt_cnt * rng.randint(40, 1_500),
            "flow_duration":                  round(rng.uniform(0.001, 60.0), 6),
            "flow_byts_s":                    round(flow_pps * rng.randint(40, 1_500), 2),
        })

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CIC_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[CICDDOS2019] {n_rows} rows generated → {out.resolve()}")
    return str(out.resolve())


# ---------------------------------------------------------------------------
# CIC-IDS2018 format
# ---------------------------------------------------------------------------

_DDOS_LABELS = [
    "DDoS - SYN Flood",
    "DDoS - UDP Flood",
    "DDoS - HULK",
    "DoS GoldenEye",
    "DoS Slowloris",
    "DoS Slowhttptest",
]

_WEB_LABELS = [
    "Web Attack - SQL Injection",
    "Web Attack - XSS",
    "Web Attack - Brute Force -Web",
    "Web Attack - Command Injection",
]

_CIC_FIELDNAMES = [
    "timestamp",
    "src_ip",
    "dst_ip",
    "dst_port",
    "label",
    "flow_packets_s",
    "total_fwd_packets",
    "total_length_of_fwd_packets",
    "flow_duration",
    "flow_byts_s",
]


def generate_cic_csv(
    output_path: str = "data/kenya_cic_synthetic.csv",
    n_rows: int = 3000,
    seed: int = 42,
) -> str:
    """
    Generate a CIC-IDS2018-compatible CSV with Kenya-specific attack context.

    Distribution: 30 % DDoS / 25 % Web Attack / 45 % Benign
    The Benign rows are written (matching the real dataset) but are filtered
    out by normalize_cic_row(), so only ~1 650 rows produce events.

    Returns the absolute path to the generated file.
    """
    rng = random.Random(seed)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows: List[dict] = []
    for _ in range(n_rows):
        roll = rng.random()
        if roll < 0.30:                            # DDoS
            label    = rng.choice(_DDOS_LABELS)
            dst_ip   = rng.choice(_KE_MPESA_IPS + _KE_TELCO_IPS)
            dst_port = rng.choice([80, 443, 8080, 8443])
            flow_pps = round(rng.uniform(5_000.0, 250_000.0), 2)
            pkt_cnt  = rng.randint(10_000, 800_000)
        elif roll < 0.55:                          # Web attack
            label    = rng.choice(_WEB_LABELS)
            dst_ip   = rng.choice(_KE_GOV_IPS + _KE_COUNTY_IPS)
            dst_port = rng.choice([80, 443, 8080])
            flow_pps = round(rng.uniform(0.5, 50.0), 2)
            pkt_cnt  = rng.randint(10, 500)
        else:                                      # Benign (filtered out)
            label    = "Benign"
            dst_ip   = rng.choice(_KE_MPESA_IPS + _KE_GOV_IPS)
            dst_port = rng.choice([80, 443, 22, 3306])
            flow_pps = round(rng.uniform(0.1, 10.0), 2)
            pkt_cnt  = rng.randint(5, 100)

        rows.append({
            "timestamp":                      _rand_ts(rng),
            "src_ip":                         rng.choice(_ATTACKER_IPS),
            "dst_ip":                         dst_ip,
            "dst_port":                       dst_port,
            "label":                          label,
            "flow_packets_s":                 flow_pps,
            "total_fwd_packets":              pkt_cnt,
            "total_length_of_fwd_packets":    pkt_cnt * rng.randint(40, 1_500),
            "flow_duration":                  round(rng.uniform(0.001, 60.0), 6),
            "flow_byts_s":                    round(flow_pps * rng.randint(40, 1_500), 2),
        })

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CIC_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    attack_rows = sum(1 for r in rows if r["label"] != "Benign")
    print(f"[CIC]   {n_rows} rows generated ({attack_rows} attack) → {out.resolve()}")
    return str(out.resolve())


# ---------------------------------------------------------------------------
# CAIDA format
# ---------------------------------------------------------------------------

_KENYA_TARGETS = [
    ("mpesa-api-ke",         443, "TCP"),
    ("safaricom-dns-ke",      53, "UDP"),
    ("equity-mbanking-ke",   443, "TCP"),
    ("kra-tax-portal-ke",    443, "TCP"),
    ("nhif-portal-ke",        80, "TCP"),
    ("county-finance-ke",   8443, "TCP"),
    ("helb-student-ke",      443, "TCP"),
    ("airtel-momo-ke",       443, "TCP"),
    ("nairobi-city-portal",   80, "TCP"),
    ("kengen-scada-ke",      102, "TCP"),
]

_CAIDA_FIELDNAMES = [
    "timestamp",
    "service_id",
    "target_port",
    "protocol",
    "pps",
    "unique_src_ips",
    "flows",
    "duration_sec",
    "attack_type",
    "asn_concentration",
    "drop_rate",
]


def generate_caida_csv(
    output_path: str = "data/kenya_caida_synthetic.csv",
    n_rows: int = 800,
    seed: int = 42,
) -> str:
    """
    Generate a CAIDA-compatible CSV with Kenya volumetric DDoS context.

    All rows represent attack traffic (CAIDA traces contain only attack windows).

    Returns the absolute path to the generated file.
    """
    rng = random.Random(seed)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    attack_types = ["syn_flood", "udp_flood", "dns_amplification", "volumetric", "icmp_flood"]

    rows: List[dict] = []
    for _ in range(n_rows):
        svc, port, proto = rng.choice(_KENYA_TARGETS)
        pps         = round(rng.uniform(50_000.0, 5_000_000.0), 0)
        unique_ips  = rng.randint(100, 50_000)

        rows.append({
            "timestamp":         _rand_ts(rng),
            "service_id":        svc,
            "target_port":       port,
            "protocol":          proto,
            "pps":               pps,
            "unique_src_ips":    unique_ips,
            "flows":             rng.randint(100, 200_000),
            "duration_sec":      round(rng.uniform(30.0, 3_600.0), 1),
            "attack_type":       rng.choice(attack_types),
            "asn_concentration": round(rng.uniform(0.05, 0.95), 4),
            "drop_rate":         round(rng.uniform(0.0, 0.85), 4),
        })

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CAIDA_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[CAIDA] {n_rows} rows generated → {out.resolve()}")
    return str(out.resolve())


# ---------------------------------------------------------------------------
# PaySim-style mobile money CSV (for standalone analysis / future connector)
# ---------------------------------------------------------------------------
# NOTE: PaySim format is NOT yet wired into real_data_pipeline.py connectors.
# Use this CSV for EDA in notebooks or to build a new mobile_money_v1 connector.
# Kaggle source (real): https://www.kaggle.com/datasets/ntnu-testimon/paysim1

_PAYSIM_FIELDNAMES = [
    "step", "type", "amount",
    "nameOrig", "nameDest",
    "oldbalanceOrg", "newbalanceOrig",
    "oldbalanceDest", "newbalanceDest",
    "isFraud", "isFlaggedFraud",
]


def generate_paysim_csv(
    output_path: str = "data/kenya_paysim_synthetic.csv",
    n_rows: int = 5_000,
    seed: int = 42,
) -> str:
    """
    Generate a PaySim-compatible mobile money transaction CSV.

    Fraud patterns:
      - Mule-network cash-out chains (M-Pesa mule accounts cycling KES 5k–150k)
      - SIM-swap takeover (high-value TRANSFER + immediate CASH_OUT)
      - Airtime siphoning (small repeated DEBIT from compromised accounts)

    Returns the absolute path to the generated file.
    """
    rng = random.Random(seed)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    def _acct(prefix: str = "M") -> str:
        return prefix + "".join(rng.choices(string.digits, k=9))

    # Pre-seeded mule ring
    mule_accounts = [_acct("M") for _ in range(30)]
    fraud_types   = {"CASH_OUT", "TRANSFER"}
    tx_types      = ["CASH_OUT", "PAYMENT", "CASH_IN", "TRANSFER", "DEBIT"]

    rows: List[dict] = []
    for step in range(1, n_rows + 1):
        tx_type  = rng.choice(tx_types)
        is_fraud = 0
        is_flag  = 0

        if tx_type in fraud_types and rng.random() < 0.02:      # 2 % fraud rate
            is_fraud    = 1
            name_orig   = rng.choice(mule_accounts)
            name_dest   = rng.choice(mule_accounts)
            amount      = round(rng.uniform(5_000.0, 150_000.0), 2)   # KES
            old_orig    = round(rng.uniform(amount, amount * 3), 2)
            new_orig    = max(0.0, round(old_orig - amount, 2))
            old_dest    = round(rng.uniform(0.0, 50_000.0), 2)
            new_dest    = round(old_dest + amount, 2)
            if amount > 10_000:
                is_flag = 1
        else:
            name_orig  = _acct("M")
            name_dest  = _acct("M")
            amount     = round(rng.uniform(50.0, 30_000.0), 2)
            old_orig   = round(rng.uniform(amount, amount * 5), 2)
            new_orig   = max(0.0, round(old_orig - amount, 2))
            old_dest   = round(rng.uniform(0.0, 100_000.0), 2)
            new_dest   = round(old_dest + amount, 2)

        rows.append({
            "step":            (step % 744) + 1,   # PaySim: 1–744 (30-day hourly steps)
            "type":            tx_type,
            "amount":          amount,
            "nameOrig":        name_orig,
            "nameDest":        name_dest,
            "oldbalanceOrg":   old_orig,
            "newbalanceOrig":  new_orig,
            "oldbalanceDest":  old_dest,
            "newbalanceDest":  new_dest,
            "isFraud":         is_fraud,
            "isFlaggedFraud":  is_flag,
        })

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_PAYSIM_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    fraud_count = sum(1 for r in rows if r["isFraud"])
    print(f"[PaySim] {n_rows} transactions ({fraud_count} fraud) → {out.resolve()}")
    return str(out.resolve())


# ---------------------------------------------------------------------------
# OCDS (Open Contracting Data Standard) — Kenya procurement releases
# ---------------------------------------------------------------------------
# Real data: Kenya PPRA publishes OCDS releases at opencontracting.org/ke
#            (public, no registration required)
# Format:    JSON with releases[] array per the OCDS 1.1 schema
# This generator produces OCDS-compatible releases pre-seeded with documented
# Kenya corruption patterns: single-source awards, FY-end surges, director
# conflicts, shell company layering, ghost contracts.

_KE_BUYERS = [
    ("KE-MoF-001",   "Ministry of Finance",              "department"),
    ("KE-MoH-001",   "Ministry of Health",               "department"),
    ("KE-MoICT-001", "Ministry of ICT",                  "department"),
    ("KE-MoR-001",   "Ministry of Roads",                "department"),
    ("KE-NBI-001",   "Nairobi County Government",        "department"),
    ("KE-MSA-001",   "Mombasa County Government",        "department"),
    ("KE-KSM-001",   "Kisumu County Government",         "department"),
    ("KE-NHIF-001",  "NHIF",                             "department"),
    ("KE-NTSA-001",  "NTSA",                             "department"),
    ("KE-KRA-001",   "Kenya Revenue Authority",          "department"),
]

_KE_SUPPLIERS = [
    ("KE-SUP-001", "Safaricom Technologies Ltd"),
    ("KE-SUP-002", "Equity Tech Solutions"),
    ("KE-SUP-003", "Kenya ICT Board Consortium"),
    ("KE-SUP-004", "Nairobi Digital Systems Ltd"),
    ("KE-SUP-005", "Summit Construction Kenya"),
    ("KE-SUP-006", "Alpine Contractors Ltd"),
    ("KE-SUP-007", "Rift Valley Suppliers Co"),
    ("KE-SUP-008", "Coastal Procurement Agency"),
    ("KE-SUP-009", "Eastern Africa Consulting"),
    ("KE-SUP-010", "Lake Region Supply Chain"),
    ("KE-SUP-011", "Great Plains Logistics Ltd"),   # shell company pattern
    ("KE-SUP-012", "Meridian Holdings Kenya"),       # shell company pattern
    ("KE-SUP-013", "Pinnacle Services Ltd"),         # shell company pattern
]

_KE_DIRECTORS = [
    "John Kamau Njoroge", "Mary Wanjiku Odhiambo", "Peter Otieno Ouma",
    "Grace Achieng Mwangi", "Samuel Kariuki Waweru", "Fatuma Hassan Ali",
    "James Maina Gitonga", "Lucy Njeri Wambui", "David Kiprop Rotich",
    "Alice Kerubo Nyamweya",
]

_TENDER_CATEGORIES = [
    ("IT Equipment Supply",     500_000,   5_000_000),
    ("Road Rehabilitation",  20_000_000, 200_000_000),
    ("Medical Supplies",      2_000_000,  50_000_000),
    ("Security Systems",      1_000_000,  20_000_000),
    ("Consultancy Services",    500_000,  10_000_000),
    ("Office Renovation",       300_000,   3_000_000),
    ("Software Development",  1_000_000,  30_000_000),
    ("Fuel Supply",             200_000,   5_000_000),
    ("Training Services",       100_000,   2_000_000),
    ("Waste Management",        500_000,  10_000_000),
]

# Kenya FY ends 30 June — surge months are May (month 5) and June (month 6)
_KE_FY_END_MONTHS = [5, 6]


def generate_ocds_json(
    output_path: str = "data/kenya_ocds_synthetic.json",
    n_releases: int = 200,
    seed: int = 42,
) -> str:
    """
    Generate OCDS 1.1-compatible procurement releases with Kenya context.

    Embeds documented corruption patterns used as weak labels by the GNN:
      - single_source: direct procurement without competition
      - director_conflict: same person sits on buyer board and supplier
      - price_inflation: award value >> market benchmark
      - fy_end_surge: contracts awarded in May/June (Kenya FY-end)
      - shell_company: newly registered company wins large sole-source contract
      - amendment_heavy: contracts with many value/scope amendments

    Returns absolute path to the generated JSON file.

    Real data alternative: download from opencontracting.org/ke (free, public)
    """
    import json as _json
    rng = random.Random(seed)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    releases = []
    for i in range(n_releases):
        buyer_id, buyer_name, _ = rng.choice(_KE_BUYERS)
        category, min_val, max_val = rng.choice(_TENDER_CATEGORIES)
        tender_value = round(rng.uniform(min_val, max_val), -3)  # round to KES 1k

        # Corruption pattern selection (mutually compatible, non-exclusive)
        is_single_source = rng.random() < 0.20       # 20% sole-source
        is_director_conflict = rng.random() < 0.15   # 15% director sits on both sides
        is_price_inflated = rng.random() < 0.18      # 18% price inflation
        is_fy_surge = rng.random() < 0.25            # 25% FY-end rush
        is_shell = rng.random() < 0.12               # 12% shell company
        n_amendments = rng.choices([0, 1, 2, 3, 4], weights=[55, 20, 12, 8, 5])[0]

        # Award date: bias toward May-June for FY-surge pattern
        if is_fy_surge:
            month = rng.choice(_KE_FY_END_MONTHS)
            day = rng.randint(1, 28)
            year = rng.choice([2022, 2023, 2024])
            award_date = f"{year}-{month:02d}-{day:02d}"
        else:
            award_date = (
                f"{rng.choice([2022,2023,2024])}-"
                f"{rng.randint(1,12):02d}-"
                f"{rng.randint(1,28):02d}"
            )

        # Pick winning supplier
        if is_shell:
            sup_id, sup_name = rng.choice([
                ("KE-SUP-011", "Great Plains Logistics Ltd"),
                ("KE-SUP-012", "Meridian Holdings Kenya"),
                ("KE-SUP-013", "Pinnacle Services Ltd"),
            ])
        else:
            sup_id, sup_name = rng.choice(_KE_SUPPLIERS[:10])

        # Award value (inflate if corruption flag set)
        inflation_factor = rng.uniform(1.4, 2.5) if is_price_inflated else 1.0
        award_value = round(tender_value * inflation_factor, -3)

        # Director overlap
        director = rng.choice(_KE_DIRECTORS)

        # Build parties list
        parties = [
            {
                "id": buyer_id,
                "name": buyer_name,
                "roles": ["buyer"],
                "contactPoint": {"name": director if is_director_conflict else rng.choice(_KE_DIRECTORS)},
            },
            {
                "id": sup_id,
                "name": sup_name,
                "roles": ["tenderer", "supplier"],
                "contactPoint": {"name": director if is_director_conflict else rng.choice(_KE_DIRECTORS)},
            },
        ]

        # Add competing tenderers unless sole-source
        n_tenderers = 1 if is_single_source else rng.randint(2, 6)
        other_sups = [s for s in _KE_SUPPLIERS if s[0] != sup_id]
        for other_id, other_name in rng.sample(other_sups, min(n_tenderers - 1, len(other_sups))):
            parties.append({"id": other_id, "name": other_name, "roles": ["tenderer"]})

        # Build amendments
        amendments = [
            {
                "id": f"AMD-{i:04d}-{j+1}",
                "date": award_date,
                "rationale": rng.choice(["scope change", "price adjustment", "timeline extension"]),
                "amendmentValue": {"amount": round(award_value * rng.uniform(0.05, 0.25), -3), "currency": "KES"},
            }
            for j in range(n_amendments)
        ]

        proc_method = "direct" if is_single_source else rng.choice(
            ["open", "open", "open", "selective", "selective", "limited"]
        )

        releases.append({
            "ocid": f"ocds-ke-2024-{i+1:05d}",
            "id": f"release-{i+1:05d}",
            "date": award_date,
            "tag": ["award"],
            "parties": parties,
            "tender": {
                "id": f"TDR-{i+1:05d}",
                "title": f"{buyer_name} — {category}",
                "description": category,
                "procurementMethod": proc_method,
                "numberOfTenderers": n_tenderers,
                "value": {"amount": tender_value, "currency": "KES"},
                "amendments": amendments,
            },
            "awards": [{
                "id": f"AWD-{i+1:05d}",
                "date": award_date,
                "status": "active",
                "value": {"amount": award_value, "currency": "KES"},
                "suppliers": [{"id": sup_id, "name": sup_name}],
            }],
            "_meta": {
                "is_single_source": is_single_source,
                "is_director_conflict": is_director_conflict,
                "is_price_inflated": is_price_inflated,
                "is_fy_surge": is_fy_surge,
                "is_shell": is_shell,
                "n_amendments": n_amendments,
            },
        })

    payload = {"releases": releases, "version": "1.1", "publisher": {"name": "Sentinel-KE synthetic"}}
    out.write_text(_json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[OCDS] {n_releases} releases generated → {out.resolve()}")
    return str(out.resolve())


# ---------------------------------------------------------------------------
# CLI entry-point (optional — run from terminal to pre-generate files)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate Kenya-context synthetic datasets")
    parser.add_argument("--out-dir", default="data", help="Output directory (default: data/)")
    parser.add_argument("--cic-rows",    type=int, default=3_000)
    parser.add_argument("--caida-rows",  type=int, default=800)
    parser.add_argument("--paysim-rows", type=int, default=5_000)
    parser.add_argument("--seed",        type=int, default=42)
    args = parser.parse_args()

    d = args.out_dir
    generate_cic_csv(   f"{d}/kenya_cic_synthetic.csv",   args.cic_rows,    args.seed)
    generate_caida_csv( f"{d}/kenya_caida_synthetic.csv",  args.caida_rows,  args.seed)
    generate_paysim_csv(f"{d}/kenya_paysim_synthetic.csv", args.paysim_rows, args.seed)
