# app/graph/service.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from neo4j import Driver
from sqlalchemy.orm import Session

from app.graph.neo4j_driver import get_driver
from app.graph import queries as Q
from app.ledger.models import EventLog


def _node_identity(node: Any) -> str:
    """
    Convert a Neo4j node into stable frontend id:
    e.g. "Person:person_h:abc123" or "IP:10.10.10.10"
    """
    labels = list(node.labels)
    label = labels[0] if labels else "Unknown"
    key = node.get("key")
    return f"{label}:{key}"


def _node_to_payload(node: Any) -> dict:
    labels = list(node.labels)
    label = labels[0] if labels else "Unknown"
    key = node.get("key")
    last_seen = node.get("last_seen")
    return {
        "id": f"{label}:{key}",
        "type": label,
        "key": key,
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
        with self.driver.session(database=self.neo4j_database) as s:
            rec = s.run(Q.q_entity_by_key(), key=key).single()
            if not rec:
                raise KeyError("entity_not_found")
            return {
                "type": rec["type"],
                "key": rec["key"],
                "last_seen": str(rec["last_seen"]) if rec["last_seen"] is not None else None,
            }

    # ---------- Neighborhood expansion ----------
    def neighbors(self, *, key: str, depth: int = 1, limit: int = 50) -> dict:
        depth = int(depth)
        limit = int(limit)

        if depth < 1 or depth > 3:
            raise ValueError("depth must be 1..3")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be 1..500")

        nodes: Dict[str, dict] = {}
        edges: Dict[Tuple[str, str, str], dict] = {}

        with self.driver.session(database=self.neo4j_database) as s:
            res = s.run(Q.q_neighbors_subgraph(depth), key=key, limit=limit)
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
                    ent = self.get_entity(key=key)
                    nid = f"{ent['type']}:{ent['key']}"
                    nodes[nid] = {"id": nid, **ent}
                    return {"nodes": list(nodes.values()), "edges": []}
                except KeyError:
                    raise KeyError("entity_not_found")

        return {"nodes": list(nodes.values()), "edges": list(edges.values())}

    # ---------- Shortest explanation path ----------
    def explain_path(self, *, from_key: str, to_key: str, max_hops: int = 4) -> dict:
        max_hops = int(max_hops)
        if max_hops < 1 or max_hops > 8:
            raise ValueError("max_hops must be 1..8")

        with self.driver.session(database=self.neo4j_database) as s:
            rec = s.run(Q.q_shortest_path(max_hops), **{"from": from_key, "to": to_key}).single()
            if not rec:
                raise KeyError("path_not_found")

            path = rec["p"]
            nodes = list(path.nodes)
            rels = list(path.relationships)

            items: List[dict] = []
            for i, rel in enumerate(rels):
                src = nodes[i]
                dst = nodes[i + 1]
                src_id = _node_identity(src)
                dst_id = _node_identity(dst)
                ep = _rel_to_payload(rel, src_id, dst_id)
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
            return {"path": items, "summary": summary}

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
