from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict
from uuid import uuid4

from sqlalchemy.orm import Session

from app.campaign.models import Campaign, CampaignEvent, CampaignEntity
from app.analytics.ddos_stages import classify_ddos_stage
from app.graph.service import GraphService
from app.cases.hasher import hash_packet


def build_case_packet(*, campaign_id, db: Session) -> Dict:
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise KeyError("campaign_not_found")

    events = (
        db.query(CampaignEvent)
        .filter(CampaignEvent.campaign_id == campaign_id)
        .order_by(CampaignEvent.occurred_at.asc())
        .all()
    )

    entities = (
        db.query(CampaignEntity)
        .filter(CampaignEntity.campaign_id == campaign_id)
        .all()
    )

    # entity summary
    entity_list = [
        {
            "entity_key": e.entity_key,
            "type": e.entity_type,
            "role": e.role,
        }
        for e in entities
    ]

    # evidence chain
    evidence = [
        {
            "event_hash": ev.event_hash,
            "occurred_at": ev.occurred_at.isoformat(),
            "entities": [
                {
                    "entity_key": e.entity_key,
                    "role": e.role,
                }
                for e in entities
            ],
        }
        for ev in events
    ]

    # graph snapshot
    gsvc = GraphService(db, neo4j_database="neo4j")
    graph_nodes = list({e["entity_key"] for e in entity_list})
    graph_edges = []

    for ev in events:
        for e in entities:
            graph_edges.append(
                {
                    "from": e.entity_key,
                    "to": campaign.primary_key,
                    "type": "TARGETED",
                    "evidence_event": ev.event_hash,
                }
            )

    gsvc.close()

    # stage (only meaningful for DDoS)
    stage = classify_ddos_stage(campaign.stats) if campaign.type.startswith("DDOS") else None

    packet = {
        "case_id": str(uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "campaign": {
            "id": str(campaign.id),
            "type": campaign.type,
            "primary_key": campaign.primary_key,
            "status": campaign.status,
            "score": campaign.score,
            "first_seen": campaign.first_seen.isoformat(),
            "last_seen": campaign.last_seen.isoformat(),
        },
        "summary": {
            "event_count": campaign.event_count,
            "distinct_entities": len(entities),
            "stage": stage,
        },
        "entities": entity_list,
        "evidence": evidence,
        "graph": {
            "nodes": graph_nodes,
            "edges": graph_edges,
        },
    }

    packet["integrity"] = hash_packet(packet)
    return packet
