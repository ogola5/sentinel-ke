from __future__ import annotations

import os
import time
from dataclasses import asdict
from typing import Dict, Iterable, List, Tuple

from neo4j import Driver
from sqlalchemy.orm import Session

from app.graph.neo4j_driver import get_driver
from app.graph.neo4j_schema import ensure_schema
from app.graph.delta_store import DeltaStore
from app.ledger.db import SessionLocal

# Allowed labels/types (hard validation)
ALLOWED_LABELS = {
    "Person", "Phone", "Account", "Device", "IP", "Domain", "URL",
    "Service", "Endpoint", "Provider", "Campaign", "InfraCluster", "Case",
}
ALLOWED_EDGE_TYPES = {
    "LOGGED_IN_FROM",
    "USED_DEVICE",
    "ACCESSED_ENDPOINT",
    "PART_OF_SERVICE",
    "HAS_SIM",
    "SIM_ASSOCIATED_DEVICE",
    "SIM_SWAPPED_TO",
    "OWNS_ACCOUNT",
    "TRANSFERRED_TO",
    "RESOLVES_TO",
    "HOSTED_ON",
    "PHISHES",
    "TARGETS",
    "TARGETS_SERVICE",
    "USES_INFRA",
    "MEMBER_OF",
    "INVOLVES",
    "SUPPORTED_BY",
    "EVIDENCED_BY",
}


def _merge_node(tx, label: str, key: str, last_seen_iso: str) -> None:
    # label is injected only after validation against ALLOWED_LABELS
    q = f"""
    MERGE (n:{label} {{key: $key}})
    ON CREATE SET n.created_at = datetime(), n.last_seen = datetime($last_seen)
    ON MATCH  SET n.last_seen = datetime($last_seen)
    """
    tx.run(q, key=key, last_seen=last_seen_iso)


def _merge_edge(tx, rel_type: str, src_label: str, src_key: str, dst_label: str, dst_key: str,
                event_hash: str, last_seen_iso: str) -> None:
    # rel_type injected only after validation against ALLOWED_EDGE_TYPES
    q = f"""
    MATCH (s:{src_label} {{key: $src_key}})
    MATCH (t:{dst_label} {{key: $dst_key}})
    MERGE (s)-[r:{rel_type}]->(t)
    ON CREATE SET
      r.created_at = datetime(),
      r.last_seen = datetime($last_seen),
      r.evidence = [$event_hash]
    ON MATCH SET
      r.last_seen = datetime($last_seen),
      r.evidence = CASE
        WHEN r.evidence IS NULL THEN [$event_hash]
        WHEN $event_hash IN r.evidence THEN r.evidence
        ELSE r.evidence + $event_hash
      END
    """
    tx.run(q, src_key=src_key, dst_key=dst_key, event_hash=event_hash, last_seen=last_seen_iso)


def apply_delta(driver: Driver, database: str, *, event_hash: str, nodes: list[dict], edges: list[dict], last_seen_iso: str) -> None:
    # Build node lookup by id -> (type,labelkey)
    id_to_node: Dict[str, Tuple[str, str]] = {}
    for n in nodes:
        ntype = n.get("type")
        nkey = n.get("key")
        nid = n.get("id")
        if ntype not in ALLOWED_LABELS:
            raise ValueError(f"Invalid node type: {ntype}")
        if not isinstance(nkey, str) or not nkey:
            raise ValueError("Invalid node key")
        if not isinstance(nid, str) or not nid:
            raise ValueError("Invalid node id")
        id_to_node[nid] = (ntype, nkey)

    def _write(tx):
        # nodes first
        for nid, (label, key) in id_to_node.items():
            _merge_node(tx, label, key, last_seen_iso)

        # then edges
        for e in edges:
            etype = e.get("type")
            src = e.get("src")
            dst = e.get("dst")
            if etype not in ALLOWED_EDGE_TYPES:
                raise ValueError(f"Invalid edge type: {etype}")
            if src not in id_to_node or dst not in id_to_node:
                # refuse partial writes: projection must be consistent
                raise ValueError("Edge references missing node(s)")

            src_label, src_key = id_to_node[src]
            dst_label, dst_key = id_to_node[dst]
            _merge_edge(tx, etype, src_label, src_key, dst_label, dst_key, event_hash, last_seen_iso)

    with driver.session(database=database) as s:
        s.execute_write(_write)


def run_once(batch_size: int = 500) -> int:
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    db: Session = SessionLocal()
    store = DeltaStore(db)

    driver = get_driver()
    ensure_schema(driver, database)

    after = store.get_cursor("neo4j")
    batch = store.fetch_batch(after=after, limit=batch_size)
    if not batch:
        return 0

    processed = 0
    # Use created_at as monotonic cursor
    for row in batch:
        # created_at is a datetime from PG
        last_seen_iso = row.created_at.replace(tzinfo=None).isoformat() + "Z"
        apply_delta(
            driver,
            database,
            event_hash=row.event_hash,
            nodes=row.nodes_json,
            edges=row.edges_json,
            last_seen_iso=last_seen_iso,
        )
        processed += 1
        store.set_cursor(row.created_at, "neo4j")

    driver.close()
    db.close()
    return processed


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--loop", action="store_true")
    p.add_argument("--sleep", type=float, default=1.0)
    args = p.parse_args()

    if not args.loop:
        n = run_once(batch_size=args.batch_size)
        print(f"neo4j_worker processed={n}")
        return

    while True:
        try:
            n = run_once(batch_size=args.batch_size)
            if n == 0:
                time.sleep(args.sleep)
        except Exception as e:
            print(f"neo4j_worker error: {e}")
            time.sleep(max(args.sleep, 2.0))


if __name__ == "__main__":
    main()
