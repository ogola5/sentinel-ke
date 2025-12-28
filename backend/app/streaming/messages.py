# app/streaming/messages.py
from __future__ import annotations

from typing import Any, Dict, List


def build_event_message(*, event_hash: str, source: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canonical envelope pushed to internal bus.
    Consumers should not need DB to parse it.
    """
    return {
        "event_hash": event_hash,
        "source": {
            "source_id": source["source_id"],
            "source_type": source["source_type"],
            "classification": source["classification"],
        },
        "event": event,  # canonical event doc (post-pseudonymization)
    }


def build_graph_delta_message(*, event_hash: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "event_hash": event_hash,
        "nodes": nodes,
        "edges": edges,
    }
