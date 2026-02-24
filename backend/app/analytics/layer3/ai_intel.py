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
