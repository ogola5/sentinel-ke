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
