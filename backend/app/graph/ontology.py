from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Tuple

# ---- Node types (labels) ----
NodeType = Literal[
    "Person",
    "Phone",
    "Account",
    "Device",
    "IP",
    "Domain",
    "URL",
    "Service",
    "Endpoint",
    "Provider",
    "Campaign",
    "InfraCluster",
    "Case",
]

# ---- Edge types ----
EdgeType = Literal[
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
]


@dataclass(frozen=True)
class NodeRef:
    type: NodeType
    key: str  # canonical key (string)

    @property
    def id(self) -> str:
        # stable node id used in graph deltas
        return f"{self.type}:{self.key}"


@dataclass(frozen=True)
class GraphNode:
    id: str
    type: NodeType
    key: str
    props: Dict


@dataclass(frozen=True)
class GraphEdge:
    type: EdgeType
    src: str  # NodeRef.id
    dst: str  # NodeRef.id
    evidence: list[str]
    props: Dict


def make_node(ref: NodeRef, **props) -> GraphNode:
    return GraphNode(id=ref.id, type=ref.type, key=ref.key, props=props or {})


def make_edge(edge_type: EdgeType, src: NodeRef, dst: NodeRef, *, evidence: list[str], **props) -> GraphEdge:
    return GraphEdge(
        type=edge_type,
        src=src.id,
        dst=dst.id,
        evidence=evidence,
        props=props or {},
    )


def dedupe_nodes(nodes: list[GraphNode]) -> list[GraphNode]:
    # O(n) dedupe by id, keeping first occurrence
    seen: set[str] = set()
    out: list[GraphNode] = []
    for n in nodes:
        if n.id in seen:
            continue
        seen.add(n.id)
        out.append(n)
    return out


def dedupe_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    # O(n) dedupe by (type, src, dst). Merge evidence lists and basic props.
    m: Dict[Tuple[str, str, str], GraphEdge] = {}
    for e in edges:
        k = (e.type, e.src, e.dst)
        if k not in m:
            m[k] = e
        else:
            merged_ev = sorted(set(m[k].evidence + e.evidence))
            # Merge props: sum counts, min first_seen, max last_seen, carry other keys from latest.
            p_old = m[k].props or {}
            p_new = e.props or {}
            count = (p_old.get("count", 0) or 0) + (p_new.get("count", 0) or 0)

            def _min_iso(a: str | None, b: str | None) -> str | None:
                if a and b:
                    return a if a <= b else b
                return a or b

            def _max_iso(a: str | None, b: str | None) -> str | None:
                if a and b:
                    return a if a >= b else b
                return a or b

            first_seen = _min_iso(p_old.get("first_seen"), p_new.get("first_seen"))
            last_seen = _max_iso(p_old.get("last_seen"), p_new.get("last_seen"))

            merged_props = dict(p_old)
            merged_props.update(p_new)
            merged_props["count"] = count or 1
            if first_seen:
                merged_props["first_seen"] = first_seen
            if last_seen:
                merged_props["last_seen"] = last_seen

            m[k] = GraphEdge(
                type=e.type,
                src=e.src,
                dst=e.dst,
                evidence=merged_ev,
                props=merged_props,
            )
    return list(m.values())
