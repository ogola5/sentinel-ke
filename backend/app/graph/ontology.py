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
    # O(n) dedupe by (type, src, dst). Merge evidence lists.
    m: Dict[Tuple[str, str, str], GraphEdge] = {}
    for e in edges:
        k = (e.type, e.src, e.dst)
        if k not in m:
            m[k] = e
        else:
            merged_ev = sorted(set(m[k].evidence + e.evidence))
            m[k] = GraphEdge(
                type=e.type,
                src=e.src,
                dst=e.dst,
                evidence=merged_ev,
                props=m[k].props or e.props or {},
            )
    return list(m.values())
