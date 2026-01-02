from __future__ import annotations

from typing import Dict, List, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.campaign.models import Campaign, CampaignEntity, CampaignEvent
from app.analytics.mitigations import Mitigation
from app.cases.builders import build_case_packet
from app.stix.ids import stix_id, now_iso
from app.stix.mapper import to_stix_object
from app.stix.attack_patterns import ddos_attack_pattern


# -------------------------
# HARDENED CAMPAIGN → STIX
# -------------------------

def _marking_definition() -> Dict:
    return {
        "type": "marking-definition",
        "spec_version": "2.1",
        "id": stix_id("marking-definition", "tlp:amber"),
        "definition_type": "tlp",
        "definition": {"tlp": "amber"},
    }


def _indicator_for_object(obj: Dict, *, campaign_id: UUID) -> Dict | None:
    if obj["type"] == "ipv4-addr":
        pattern = f"[ipv4-addr:value = '{obj['value']}']"
        name = f"Suspicious IP {obj['value']}"
    elif obj["type"] == "domain-name":
        pattern = f"[domain-name:value = '{obj['value']}']"
        name = f"Suspicious domain {obj['value']}"
    elif obj["type"] == "url":
        pattern = f"[url:value = '{obj['value']}']"
        name = f"Suspicious URL {obj['value']}"
    else:
        return None

    return {
        "type": "indicator",
        "spec_version": "2.1",
        "id": stix_id("indicator", f"{obj['id']}|campaign:{campaign_id}"),
        "created": now_iso(),
        "modified": now_iso(),
        "name": name,
        "pattern_type": "stix",
        "pattern": pattern,
        "valid_from": now_iso(),
        "confidence": 50,
    }


def _observed_data(
    *,
    object_refs: List[str],
    first_observed: str,
    last_observed: str,
    count: int,
    external_refs: List[Dict],
) -> Dict:
    return {
        "type": "observed-data",
        "spec_version": "2.1",
        "id": stix_id("observed-data", f"{first_observed}:{last_observed}:{count}"),
        "created": now_iso(),
        "modified": now_iso(),
        "first_observed": first_observed,
        "last_observed": last_observed,
        "number_observed": max(1, count),
        "object_refs": object_refs,
        "external_references": external_refs,
    }


def build_stix_bundle_from_campaign(*, db: Session, campaign_id: UUID) -> Dict:
    """
    Export a SINGLE campaign as a STIX 2.1 bundle.

    Semantics:
    - Campaign == Report
    - Entities == Observables (SCOs)
    - Relationships encode attacker → target (for DDOS)
    - Events are evidence references only (bounded)
    """

    # ------------------------------------------------------------------
    # 1) Load campaign (source of truth)
    # ------------------------------------------------------------------
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise KeyError("campaign_not_found")

    entities = (
        db.query(CampaignEntity)
        .filter(CampaignEntity.campaign_id == campaign_id)
        .all()
    )

    events = (
        db.query(CampaignEvent)
        .filter(CampaignEvent.campaign_id == campaign_id)
        .order_by(CampaignEvent.occurred_at.asc())
        .all()
    )

    # ------------------------------------------------------------------
    # 2) Producer identity (stable)
    # ------------------------------------------------------------------
    producer = {
        "type": "identity",
        "spec_version": "2.1",
        "id": stix_id("identity", "sentinel-ke"),
        "name": "Sentinel-KE",
        "identity_class": "organization",
        "created": now_iso(),
        "modified": now_iso(),
    }

    marking = _marking_definition()
    objects: List[Dict] = [producer, marking]
    object_ids: Set[str] = {producer["id"]}

    # ------------------------------------------------------------------
    # 3) Resolve TARGET (campaign primary key)
    # ------------------------------------------------------------------
    target_obj = to_stix_object(campaign.primary_key)
    if target_obj:
        if target_obj["id"] not in object_ids:
            objects.append(target_obj)
            object_ids.add(target_obj["id"])
        target_id = target_obj["id"]
    else:
        # DDOS without a target makes no sense → explicit failure
        raise ValueError(f"primary_key not mappable to STIX: {campaign.primary_key}")

    # ------------------------------------------------------------------
    # 4) Build observable objects (entities)
    # ------------------------------------------------------------------
    obj_by_entity_key: Dict[str, Dict] = {}
    indicators: List[Dict] = []

    for e in entities:
        # Skip primary key duplicate
        if e.entity_key == campaign.primary_key:
            continue

        o = to_stix_object(e.entity_key)
        if not o:
            # Hardening: skip unmappable entity safely
            continue

        if o["id"] not in object_ids:
            objects.append(o)
            object_ids.add(o["id"])

        obj_by_entity_key[e.entity_key] = o
        ind = _indicator_for_object(o, campaign_id=campaign.id)
        if ind:
            indicators.append(ind)

    # ------------------------------------------------------------------
    # 5) Evidence references (bounded, deterministic)
    # ------------------------------------------------------------------
    event_hashes = [ev.event_hash for ev in events[:200]]

    external_refs = [
        {
            "source_name": "sentinel-ke",
            "external_id": h,
            "description": "ledger_event_hash",
        }
        for h in event_hashes
    ]

    # ------------------------------------------------------------------
    # 6) Relationships (DDOS-aware)
    # ------------------------------------------------------------------
    relationships: List[Dict] = []

    for e in entities:
        src_obj = obj_by_entity_key.get(e.entity_key)
        if not src_obj:
            continue

        # No self-loops
        if src_obj["id"] == target_id:
            continue

        # HARDENED LOGIC:
        # DDOS → IPs TARGET the endpoint
        if campaign.type == "DDOS_ENDPOINT_FANIN":
            rel_type = "targets"
        else:
            # fallback for non-DDOS campaigns
            rel_type = "related-to"

        rel = {
            "type": "relationship",
            "spec_version": "2.1",
            "id": stix_id(
                "relationship",
                f"{src_obj['id']}|{rel_type}|{target_id}|campaign:{campaign.id}",
            ),
            "relationship_type": rel_type,
            "source_ref": src_obj["id"],
            "target_ref": target_id,
            "created_by_ref": producer["id"],
            "created": now_iso(),
            "modified": now_iso(),
            "external_references": external_refs,
            "object_marking_refs": [marking["id"]],
        }

        relationships.append(rel)

    # ------------------------------------------------------------------
    # 7) Report (campaign container)
    # ------------------------------------------------------------------
    report_id = stix_id("report", f"campaign:{campaign.id}")

    report = {
        "type": "report",
        "spec_version": "2.1",
        "id": report_id,
        "created_by_ref": producer["id"],
        "created": campaign.first_seen.isoformat(),
        "modified": campaign.last_seen.isoformat(),
        "name": f"Sentinel-KE Campaign: {campaign.type} {campaign.primary_key}",
        "description": (
            f"Campaign type={campaign.type}, "
            f"events={campaign.event_count}, "
            f"window={campaign.first_seen.isoformat()} → {campaign.last_seen.isoformat()}"
        ),
        "report_types": ["threat-report"],
        "published": campaign.last_seen.isoformat(),
        "confidence": min(100, int(campaign.score * 100)),
        "object_refs": (
            list(object_ids)
            + [r["id"] for r in relationships]
            + [i["id"] for i in indicators]
        ),
        "external_references": [
            {
                "source_name": "sentinel-ke",
                "external_id": str(campaign.id),
                "description": "campaign_id",
            }
        ],
        "object_marking_refs": [marking["id"]],
    }

    # ------------------------------------------------------------------
    # 8) Bundle assembly
    # ------------------------------------------------------------------
    # Observed-data object (bounded evidence)
    if events:
        first_observed = events[0].occurred_at.isoformat()
        last_observed = events[-1].occurred_at.isoformat()
        observed = _observed_data(
            object_refs=list(object_ids),
            first_observed=first_observed,
            last_observed=last_observed,
            count=len(event_hashes),
            external_refs=external_refs,
        )
        observed["object_marking_refs"] = [marking["id"]]
        objects.append(observed)
        report["object_refs"].append(observed["id"])

    # Add attack pattern if DDoS campaign
    if "DDOS" in campaign.type.upper():
        ap = ddos_attack_pattern()
        ap["object_marking_refs"] = [marking["id"]]
        objects.append(ap)
        report["object_refs"].append(ap["id"])

    for ind in indicators:
        ind["object_marking_refs"] = [marking["id"]]
    objects.extend(indicators)
    objects.extend(relationships)
    objects.append(report)

    bundle = {
        "type": "bundle",
        "id": stix_id("bundle", f"campaign:{campaign.id}"),
        "objects": objects,
    }

    return bundle


def build_stix_bundle_from_case(*, db: Session, campaign_id: UUID) -> Dict:
    """
    Export a case packet as STIX bundle (built from campaign).
    """
    case = build_case_packet(campaign_id=campaign_id, db=db)

    producer = {
        "type": "identity",
        "spec_version": "2.1",
        "id": stix_id("identity", "sentinel-ke"),
        "name": "Sentinel-KE",
        "identity_class": "organization",
        "created": now_iso(),
        "modified": now_iso(),
    }
    marking = _marking_definition()

    objects: List[Dict] = [producer, marking]
    object_ids: Set[str] = {producer["id"]}

    for e in case["entities"]:
        obj = to_stix_object(e["entity_key"])
        if not obj:
            continue
        if obj["id"] not in object_ids:
            objects.append(obj)
            object_ids.add(obj["id"])

    evidence_hashes = [ev["event_hash"] for ev in case.get("evidence", [])][:200]
    external_refs = [
        {
            "source_name": "sentinel-ke",
            "external_id": h,
            "description": "ledger_event_hash",
        }
        for h in evidence_hashes
    ]

    if case.get("evidence"):
        first_observed = case["evidence"][0]["occurred_at"]
        last_observed = case["evidence"][-1]["occurred_at"]
        observed = _observed_data(
            object_refs=list(object_ids),
            first_observed=first_observed,
            last_observed=last_observed,
            count=len(evidence_hashes),
            external_refs=external_refs,
        )
        observed["object_marking_refs"] = [marking["id"]]
        objects.append(observed)
        object_ids.add(observed["id"])

    report_id = stix_id("report", f"case:{case['case_id']}")
    report = {
        "type": "report",
        "spec_version": "2.1",
        "id": report_id,
        "created_by_ref": producer["id"],
        "created": now_iso(),
        "modified": now_iso(),
        "name": f"Sentinel-KE Case: {case['campaign']['type']} {case['campaign']['primary_key']}",
        "description": "Case packet exported from Sentinel-KE",
        "report_types": ["threat-report"],
        "published": case["generated_at"],
        "confidence": min(100, int(case["campaign"]["score"] * 100)),
        "object_refs": list(object_ids),
        "external_references": [
            {
                "source_name": "sentinel-ke",
                "external_id": case["case_id"],
                "description": "case_id",
            }
        ],
        "object_marking_refs": [marking["id"]],
    }

    objects.append(report)
    return {
        "type": "bundle",
        "id": stix_id("bundle", f"case:{case['case_id']}"),
        "objects": objects,
    }


def build_stix_bundle_from_mitigations(
    *, db: Session, kind: str | None = None, limit: int = 200
) -> Dict:
    """
    Export IOC bundles from Mitigation rows as STIX indicators.
    """
    q = db.query(Mitigation)
    if kind:
        q = q.filter(Mitigation.kind == kind)
    rows = q.order_by(Mitigation.created_at.desc()).limit(limit).all()

    producer = {
        "type": "identity",
        "spec_version": "2.1",
        "id": stix_id("identity", "sentinel-ke"),
        "name": "Sentinel-KE",
        "identity_class": "organization",
        "created": now_iso(),
        "modified": now_iso(),
    }
    marking = _marking_definition()

    objects: List[Dict] = [producer, marking]
    object_ids: Set[str] = {producer["id"]}
    indicators: List[Dict] = []

    def _indicator_for_obj(obj: Dict, stable_key: str) -> Dict | None:
        if obj["type"] == "ipv4-addr":
            pattern = f"[ipv4-addr:value = '{obj['value']}']"
            name = f"Suspicious IP {obj['value']}"
        elif obj["type"] == "domain-name":
            pattern = f"[domain-name:value = '{obj['value']}']"
            name = f"Suspicious domain {obj['value']}"
        elif obj["type"] == "url":
            pattern = f"[url:value = '{obj['value']}']"
            name = f"Suspicious URL {obj['value']}"
        else:
            return None
        return {
            "type": "indicator",
            "spec_version": "2.1",
            "id": stix_id("indicator", stable_key),
            "created": now_iso(),
            "modified": now_iso(),
            "name": name,
            "pattern_type": "stix",
            "pattern": pattern,
            "valid_from": now_iso(),
            "confidence": 50,
            "object_marking_refs": [marking["id"]],
        }

    def _add_obj(entity_key: str, stable_key: str) -> None:
        obj = to_stix_object(entity_key)
        if not obj:
            return
        if obj["id"] not in object_ids:
            objects.append(obj)
            object_ids.add(obj["id"])
        ind = _indicator_for_obj(obj, stable_key)
        if ind:
            indicators.append(ind)

    for r in rows:
        payload = r.payload or {}
        ioc = payload.get("ioc") or {}

        for ip in payload.get("ips", []) + ioc.get("ips", []):
            _add_obj(f"ip:{ip}", f"mitigation:{r.id}:ip:{ip}")
        for dom in payload.get("domains", []) + ioc.get("domains", []):
            _add_obj(f"domain:{dom}", f"mitigation:{r.id}:domain:{dom}")
        for url in payload.get("urls", []) + ioc.get("urls", []):
            _add_obj(f"url:{url}", f"mitigation:{r.id}:url:{url}")
        for ep in payload.get("endpoints", []) + ioc.get("endpoints", []):
            _add_obj(f"endpoint:{ep}", f"mitigation:{r.id}:endpoint:{ep}")
        for provider in payload.get("providers", []) + ioc.get("providers", []):
            _add_obj(f"provider:{provider}", f"mitigation:{r.id}:provider:{provider}")
        if ioc.get("service_id"):
            _add_obj(f"service_id:{ioc['service_id']}", f"mitigation:{r.id}:service:{ioc['service_id']}")

    for ind in indicators:
        if ind["id"] not in object_ids:
            objects.append(ind)
            object_ids.add(ind["id"])

    latest = rows[0].created_at.isoformat() if rows else "none"
    report = {
        "type": "report",
        "spec_version": "2.1",
        "id": stix_id("report", f"mitigations:{kind or 'all'}:{latest}"),
        "created_by_ref": producer["id"],
        "created": now_iso(),
        "modified": now_iso(),
        "name": f"Sentinel-KE Mitigations ({kind or 'all'})",
        "description": "IOC export from mitigation bundles",
        "report_types": ["threat-report"],
        "published": now_iso(),
        "confidence": 60,
        "object_refs": list(object_ids),
        "object_marking_refs": [marking["id"]],
    }

    objects.append(report)
    return {
        "type": "bundle",
        "id": stix_id("bundle", f"mitigations:{kind or 'all'}:{latest}"),
        "objects": objects,
    }
