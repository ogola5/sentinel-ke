from __future__ import annotations

from typing import Dict, List, Sequence


EVENT_TYPE_TO_TECHNIQUES = {
    "PHISHING_MESSAGE_EVENT": [("T1566", "initial-access", 0.86)],
    "SIM_SWAP_EVENT": [("T1649", "credential-access", 0.8)],
    "LOGIN_EVENT": [("T1078", "credential-access", 0.7)],
    "TRANSACTION_EVENT": [("T1657", "impact", 0.65)],
    "DDOS_SIGNAL_EVENT": [("T1498", "impact", 0.9)],
    "DB_AUDIT_EVENT": [("T1005", "collection", 0.55)],
    "FILE_INTEGRITY_EVENT": [("T1485", "impact", 0.7)],
    "DFIR_FINDING_EVENT": [("T1589", "reconnaissance", 0.45)],
}

KILL_CHAIN_PRECEDENCE = [
    "impact",
    "actions-on-objectives",
    "lateral-movement",
    "command-and-control",
    "credential-access",
    "execution",
    "initial-access",
    "reconnaissance",
]

KILL_CHAIN_BY_EVENT = {
    "PHISHING_MESSAGE_EVENT": "initial-access",
    "SIM_SWAP_EVENT": "credential-access",
    "LOGIN_EVENT": "credential-access",
    "TRANSACTION_EVENT": "actions-on-objectives",
    "DDOS_SIGNAL_EVENT": "impact",
    "DB_AUDIT_EVENT": "collection",
    "FILE_INTEGRITY_EVENT": "impact",
    "DFIR_FINDING_EVENT": "reconnaissance",
}

D3FEND_BY_REASON = {
    "DDOS_ALERT_ACTIVE": ["D3-NTA", "D3-DNSAL"],
    "VPN_INFRA_REUSE": ["D3-NTA", "D3-SEG"],
    "CAMPAIGN_LINKED": ["D3-TDS", "D3-INV"],
    "PHISHING_SIGNAL": ["D3-EMAIL", "D3-ATP"],
    "SIM_SWAP_SIGNAL": ["D3-MFA", "D3-AUTHN"],
    "TXN_ACTIVITY": ["D3-BA", "D3-FRAUDDET"],
    "RISK_INDICATOR_ONLY_NOT_FINAL_PROOF": ["D3-EVIDENCE", "D3-AUDIT"],
}


def event_types_to_attack_techniques(event_types: Dict[str, int] | None) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    et = event_types or {}
    seen = set()
    for name, count in et.items():
        if int(count or 0) <= 0:
            continue
        for tech_id, tactic, base_conf in EVENT_TYPE_TO_TECHNIQUES.get(str(name), []):
            key = (tech_id, tactic)
            if key in seen:
                continue
            seen.add(key)
            confidence = min(0.99, float(base_conf) + min(0.1, 0.01 * int(count)))
            out.append(
                {
                    "technique_id": tech_id,
                    "tactic": tactic,
                    "confidence": round(confidence, 6),
                    "source_event_type": str(name),
                    "event_count": int(count),
                }
            )
    out.sort(key=lambda x: float(x["confidence"]), reverse=True)
    return out


def event_types_to_kill_chain_stage(event_types: Dict[str, int] | None) -> str | None:
    et = event_types or {}
    stages = []
    for name, count in et.items():
        if int(count or 0) <= 0:
            continue
        stage = KILL_CHAIN_BY_EVENT.get(str(name))
        if stage:
            stages.append(stage)
    if not stages:
        return None

    for stage in KILL_CHAIN_PRECEDENCE:
        if stage in stages:
            return stage
    return stages[0]


def reason_codes_to_d3fend_controls(reason_codes: Sequence[str] | None) -> List[str]:
    controls = set()
    for reason in reason_codes or []:
        for c in D3FEND_BY_REASON.get(str(reason), []):
            controls.add(str(c))
    return sorted(controls)


# ---------------------------------------------------------------------------
# MITRE ATT&CK Software Catalog
# Curated subset mapping software/tool names to the techniques they implement.
# Source: MITRE ATT&CK Enterprise v14 Software entries.
# Used to enrich technique hits with the tools that operationalise them.
# ---------------------------------------------------------------------------

ATTACK_SOFTWARE_CATALOG: List[Dict[str, object]] = [
    # ── Remote Access / C2 ──────────────────────────────────────────────────
    {"software_id": "S0154", "name": "Cobalt Strike",    "type": "tool",    "techniques": ["T1055", "T1059", "T1071", "T1105", "T1566", "T1078"]},
    {"software_id": "S0002", "name": "Mimikatz",         "type": "tool",    "techniques": ["T1003", "T1558", "T1649", "T1078"]},
    {"software_id": "S0357", "name": "Impacket",         "type": "tool",    "techniques": ["T1021", "T1003", "T1558"]},
    {"software_id": "S0106", "name": "Lazarus njRAT",    "type": "malware", "techniques": ["T1071", "T1059", "T1027", "T1105"]},
    {"software_id": "S0099", "name": "Orcus RAT",        "type": "malware", "techniques": ["T1071", "T1059", "T1560"]},
    {"software_id": "S0043", "name": "Empire",           "type": "tool",    "techniques": ["T1059", "T1071", "T1105", "T1078"]},
    {"software_id": "S0111", "name": "Metasploit",       "type": "tool",    "techniques": ["T1059", "T1190", "T1021", "T1105"]},
    # ── DDoS / Network Flood ────────────────────────────────────────────────
    {"software_id": "S0375", "name": "Mirai",            "type": "malware", "techniques": ["T1498", "T1499", "T1584"]},
    {"software_id": "S0099", "name": "LOIC",             "type": "tool",    "techniques": ["T1498"]},
    {"software_id": "S0100", "name": "HOIC",             "type": "tool",    "techniques": ["T1498"]},
    {"software_id": "S0376", "name": "SlowLoris",        "type": "tool",    "techniques": ["T1499"]},
    # ── Phishing / Social Engineering ───────────────────────────────────────
    {"software_id": "S0200", "name": "Evilginx2",        "type": "tool",    "techniques": ["T1566", "T1557", "T1539"]},
    {"software_id": "S0201", "name": "GoPhish",          "type": "tool",    "techniques": ["T1566"]},
    # ── Credential / SIM Fraud ──────────────────────────────────────────────
    {"software_id": "S0174", "name": "Carbanak",         "type": "malware", "techniques": ["T1649", "T1078", "T1190", "T1657"]},
    {"software_id": "S0175", "name": "FIN7 BOOSTWRITE", "type": "malware", "techniques": ["T1657", "T1078", "T1059"]},
    # ── Data Exfiltration ───────────────────────────────────────────────────
    {"software_id": "S0002", "name": "Exfiltron",        "type": "malware", "techniques": ["T1041", "T1048", "T1005"]},
    {"software_id": "S0050", "name": "CozyDuke",         "type": "malware", "techniques": ["T1071", "T1041", "T1560"]},
    # ── Ransomware / Destructive ────────────────────────────────────────────
    {"software_id": "S0366", "name": "WannaCry",         "type": "malware", "techniques": ["T1486", "T1485", "T1190"]},
    {"software_id": "S0367", "name": "NotPetya",         "type": "malware", "techniques": ["T1486", "T1485", "T1003"]},
    {"software_id": "S0368", "name": "REvil/Sodinokibi", "type": "malware", "techniques": ["T1486", "T1490", "T1059"]},
    # ── Reconnaissance ──────────────────────────────────────────────────────
    {"software_id": "S0269", "name": "Nmap",             "type": "tool",    "techniques": ["T1046", "T1589"]},
    {"software_id": "S0270", "name": "Shodan (attacker use)", "type": "tool", "techniques": ["T1589", "T1590"]},
    # ── File Integrity / Persistence ────────────────────────────────────────
    {"software_id": "S0111", "name": "Rootkit Generic",  "type": "malware", "techniques": ["T1014", "T1485", "T1547"]},
]

# Index: technique_id → list of software entries
_TECHNIQUE_TO_SOFTWARE: Dict[str, List[Dict[str, object]]] = {}
for _sw in ATTACK_SOFTWARE_CATALOG:
    for _tid in (_sw.get("techniques") or []):
        _TECHNIQUE_TO_SOFTWARE.setdefault(str(_tid), []).append(_sw)


def techniques_to_tools(technique_ids: Sequence[str] | None) -> List[Dict[str, object]]:
    """
    Given a list of MITRE ATT&CK technique IDs, return the known software /
    tools that implement those techniques, deduped by software_id.
    """
    seen_sw: set = set()
    tools: List[Dict[str, object]] = []
    for tid in technique_ids or []:
        for sw in _TECHNIQUE_TO_SOFTWARE.get(str(tid), []):
            sw_id = str(sw.get("software_id") or sw.get("name"))
            if sw_id in seen_sw:
                continue
            seen_sw.add(sw_id)
            tools.append({
                "software_id": sw.get("software_id"),
                "name":        sw.get("name"),
                "type":        sw.get("type"),
                "matched_techniques": [
                    t for t in (sw.get("techniques") or []) if t in set(technique_ids or [])
                ],
            })
    return tools


def build_counterfactual(*, probability: float, threshold_score: float, top_feature_hint: str) -> Dict[str, object]:
    thr_prob = max(0.0, min(1.0, float(threshold_score) / 100.0))
    prob = max(0.0, min(1.0, float(probability)))
    delta = round(abs(prob - thr_prob), 6)
    direction = "decrease" if prob >= thr_prob else "increase"
    return {
        "target_probability": round(thr_prob, 6),
        "current_probability": round(prob, 6),
        "required_probability_shift": delta,
        "recommended_direction": direction,
        "top_feature_hint": top_feature_hint,
    }
