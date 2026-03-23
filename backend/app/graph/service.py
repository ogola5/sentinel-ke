# app/graph/service.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from neo4j import Driver
from sqlalchemy.orm import Session

from app.graph.neo4j_driver import get_driver
from app.graph import queries as Q
from app.ledger.models import EventLog

LABEL_TO_PREFIX: Dict[str, str] = {
    "IP": "ip",
    "Domain": "domain",
    "URL": "url",
    "Service": "service_id",
    "Endpoint": "endpoint",
    "Provider": "provider_id",
    "Device": "device_id",
    "Account": "account_h",
    "Phone": "phone_h",
    "Person": "person_h",
}

PREFIX_TO_LABEL: Dict[str, str] = {v: k for k, v in LABEL_TO_PREFIX.items()}

COMMUNITY_BY_LABEL: Dict[str, str] = {
    "Service": "target",
    "Endpoint": "target",
    "IP": "infra",
    "Domain": "infra",
    "URL": "infra",
    "Provider": "infra",
    "InfraCluster": "infra",
    "Campaign": "campaign",
}


def _stored_key_from_node(node: Any, label: str) -> Optional[str]:
    return node.get("key") or node.get("cluster_id") or node.get("campaign_id") or node.get("case_id")


def _canonical_key(label: str, key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    prefix = LABEL_TO_PREFIX.get(label)
    if not prefix:
        lowered = label.lower()
        if lowered == "campaign":
            return f"campaign:{key}"
        if lowered == "infracluster":
            return f"cluster:{key}"
        if lowered == "case":
            return f"case:{key}"
        return f"{label}:{key}"
    if key.startswith(f"{prefix}:"):
        return key
    return f"{prefix}:{key}"


def _display_label(label: str, key: Optional[str]) -> str:
    if not key:
        return label
    if label == "Endpoint" and ":" in key:
        _, tail = key.split(":", 1)
        return tail
    prefix = LABEL_TO_PREFIX.get(label)
    if prefix and key.startswith(f"{prefix}:"):
        return key[len(prefix) + 1 :]
    return key


def _normalize_lookup_key(key: str) -> tuple[str, Optional[str], str]:
    trimmed = key.strip()
    prefix, sep, rest = trimmed.partition(":")
    if not sep:
        return trimmed, None, trimmed
    label = PREFIX_TO_LABEL.get(prefix)
    if not label:
        return trimmed, None, trimmed
    if prefix in {"ip", "domain", "url", "service_id", "endpoint", "provider_id", "device_id"}:
        return trimmed, label, rest
    return trimmed, label, trimmed


def _node_identity(node: Any) -> str:
    """
    Convert a Neo4j node into stable frontend id:
    e.g. "Person:person_h:abc123" or "IP:10.10.10.10"
    """
    labels = list(node.labels)
    label = labels[0] if labels else "Unknown"
    key = _stored_key_from_node(node, label)
    return _canonical_key(label, key) or f"{label}:unknown"


def _node_to_payload(node: Any) -> dict:
    labels = list(node.labels)
    label = labels[0] if labels else "Unknown"
    key = _stored_key_from_node(node, label)
    last_seen = node.get("last_seen")
    canonical_id = _canonical_key(label, key) or f"{label}:unknown"
    return {
        "id": canonical_id,
        "type": label,
        "key": key,
        "label": _display_label(label, key),
        "community": COMMUNITY_BY_LABEL.get(label, "support"),
        "last_seen": str(last_seen) if last_seen is not None else None,
    }


def _rel_to_payload(rel: Any, src_id: str, dst_id: str) -> dict:
    # evidence is stored on relationships as a list
    ev = rel.get("evidence") or []
    last_seen = rel.get("last_seen")
    return {
        "type": rel.type,
        "src": src_id,
        "dst": dst_id,
        "source": src_id,
        "target": dst_id,
        "evidence": ev,
        "last_seen": str(last_seen) if last_seen is not None else None,
    }


class GraphService:
    def __init__(self, db: Session, *, neo4j_database: str = "neo4j"):
        self.db = db
        self.neo4j_database = neo4j_database
        self.driver: Driver = get_driver()

    def close(self) -> None:
        try:
            self.driver.close()
        except Exception:
            pass

    # ---------- Entity profile ----------
    def get_entity(self, *, key: str) -> dict:
        _, label_hint, stored_key = _normalize_lookup_key(key)
        with self.driver.session(database=self.neo4j_database) as s:
            rec = s.run(Q.q_entity_by_key(label_hint), key=stored_key).single()
            if not rec:
                raise KeyError("entity_not_found")
            entity_label = rec["type"]
            entity_key = rec["key"]
            return {
                "type": entity_label,
                "key": entity_key,
                "entity_key": _canonical_key(entity_label, entity_key),
                "label": _display_label(entity_label, entity_key),
                "last_seen": str(rec["last_seen"]) if rec["last_seen"] is not None else None,
            }

    # ---------- Neighborhood expansion ----------
    def neighbors(self, *, key: str, depth: int = 1, limit: int = 50) -> dict:
        depth = int(depth)
        limit = int(limit)
        canonical_lookup_key, label_hint, stored_key = _normalize_lookup_key(key)

        if depth < 1 or depth > 3:
            raise ValueError("depth must be 1..3")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be 1..500")

        nodes: Dict[str, dict] = {}
        edges: Dict[Tuple[str, str, str], dict] = {}

        with self.driver.session(database=self.neo4j_database) as s:
            res = s.run(Q.q_neighbors_subgraph(depth, label_hint), key=stored_key, limit=limit)
            found_any = False
            for rec in res:
                found_any = True
                path = rec["p"]
                # nodes
                for n in path.nodes:
                    payload = _node_to_payload(n)
                    nodes[payload["id"]] = payload
                # relationships
                for r in path.relationships:
                    start = path.start_node
                    # Neo4j Path relationships do not directly expose endpoints,
                    # so we reconstruct via relationship.start_node/end_node (Neo4j 5 returns them)
                # safer: rebuild edges by iterating consecutive nodes in path
                path_nodes = list(path.nodes)
                path_rels = list(path.relationships)
                for i, rel in enumerate(path_rels):
                    src = path_nodes[i]
                    dst = path_nodes[i + 1]
                    src_id = _node_identity(src)
                    dst_id = _node_identity(dst)
                    ep = _rel_to_payload(rel, src_id, dst_id)
                    ek = (ep["type"], ep["src"], ep["dst"])
                    # merge evidence if same edge appears multiple times
                    if ek in edges:
                        cur = edges[ek]
                        cur_ev = set(cur.get("evidence") or [])
                        new_ev = set(ep.get("evidence") or [])
                        cur["evidence"] = list(cur_ev.union(new_ev))
                        # last_seen keep latest string lexicographically is not guaranteed.
                        # in MVP we keep whichever is non-null and prefer the newer by string compare.
                        if ep["last_seen"] and (not cur["last_seen"] or ep["last_seen"] > cur["last_seen"]):
                            cur["last_seen"] = ep["last_seen"]
                    else:
                        edges[ek] = ep

            if not found_any:
                # Could be isolated node or not present
                # If node exists but has no edges, return node-only
                try:
                    ent = self.get_entity(key=canonical_lookup_key)
                    nid = ent["entity_key"] or canonical_lookup_key
                    nodes[nid] = {
                        "id": nid,
                        "type": ent["type"],
                        "key": ent["key"],
                        "label": ent["label"],
                        "community": COMMUNITY_BY_LABEL.get(ent["type"], "support"),
                        "last_seen": ent["last_seen"],
                    }
                    return {
                        "entity_key": canonical_lookup_key,
                        "node": nodes[nid],
                        "neighbours": [],
                        "nodes": list(nodes.values()),
                        "edges": [],
                    }
                except KeyError:
                    raise KeyError("entity_not_found")

        root_node = nodes.get(canonical_lookup_key)
        neighbours = [payload for node_id, payload in nodes.items() if node_id != canonical_lookup_key]
        return {
            "entity_key": canonical_lookup_key,
            "node": root_node,
            "neighbours": neighbours,
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
        }

    # ---------- Shortest explanation path ----------
    def explain_path(self, *, from_key: str, to_key: str, max_hops: int = 4) -> dict:
        max_hops = int(max_hops)
        if max_hops < 1 or max_hops > 8:
            raise ValueError("max_hops must be 1..8")
        canonical_from_key, from_label, stored_from_key = _normalize_lookup_key(from_key)
        canonical_to_key, to_label, stored_to_key = _normalize_lookup_key(to_key)

        with self.driver.session(database=self.neo4j_database) as s:
            rec = s.run(
                Q.q_shortest_path(max_hops, from_label=from_label, to_label=to_label),
                **{"from": stored_from_key, "to": stored_to_key},
            ).single()
            if not rec:
                raise KeyError("path_not_found")

            path = rec["p"]
            nodes = list(path.nodes)
            rels = list(path.relationships)

            items: List[dict] = []
            path_nodes = [_node_to_payload(node) for node in nodes]
            path_edges: List[dict] = []
            for i, rel in enumerate(rels):
                src = nodes[i]
                dst = nodes[i + 1]
                src_id = _node_identity(src)
                dst_id = _node_identity(dst)
                ep = _rel_to_payload(rel, src_id, dst_id)
                path_edges.append(ep)
                items.append(
                    {
                        "src": src_id,
                        "edge": ep["type"],
                        "dst": dst_id,
                        "evidence": ep["evidence"],
                        "last_seen": ep["last_seen"],
                    }
                )

            summary = self._summarize_path(items)
            return {
                "found": True,
                "from": canonical_from_key,
                "to": canonical_to_key,
                "hop_count": len(path_edges),
                "path": path_nodes,
                "edges": path_edges,
                "steps": items,
                "summary": summary,
            }

    def _summarize_path(self, items: List[dict]) -> str:
        if not items:
            return "No path"
        # MVP: simple deterministic phrasing
        parts = []
        for it in items:
            parts.append(f"{it['src']} -[{it['edge']}]-> {it['dst']}")
        return " ; ".join(parts)

    # ---------- Evidence bridge: event_hash -> ledger event ----------
    def get_evidence_event(self, *, event_hash: str) -> dict:
        row: Optional[EventLog] = self.db.get(EventLog, event_hash)
        if not row:
            raise KeyError("event_not_found")

        anchors = row.anchors_json or {}
        anchors_flat = [f"{k}:{v}" for k, v in anchors.items()]

        return {
            "event_hash": row.event_hash,
            "event_type": row.event_type,
            "source_id": row.source_id,
            "classification": row.classification,
            "schema_version": row.schema_version,
            "signature_valid": bool(row.signature_valid),
            "occurred_at": row.occurred_at.isoformat(),
            "received_at": row.received_at.isoformat(),
            "anchors": anchors,
            "anchors_flat": anchors_flat,
            "payload": row.payload_json,
        }
