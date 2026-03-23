# app/graph/queries.py
from __future__ import annotations


def _with_label(label: str | None) -> str:
    return f":{label}" if label else ""


def q_entity_by_key(label: str | None = None) -> str:
    node_label = _with_label(label)
    return f"""
    MATCH (n{node_label} {{key:$key}})
    RETURN labels(n)[0] AS type, n.key AS key, n.last_seen AS last_seen
    """


def q_neighbors_subgraph(depth: int, label: str | None = None) -> str:
    # depth is validated before use
    node_label = _with_label(label)
    return f"""
    MATCH (n{node_label} {{key:$key}})
    CALL {{
      WITH n
      MATCH p=(n)-[r*1..{depth}]-(m)
      RETURN p
      LIMIT $limit
    }}
    RETURN p
    """


def q_shortest_path(max_hops: int, from_label: str | None = None, to_label: str | None = None) -> str:
    # max_hops is validated before use
    src_label = _with_label(from_label)
    dst_label = _with_label(to_label)
    return f"""
    MATCH p = shortestPath((a{src_label} {{key:$from}})-[*1..{max_hops}]-(b{dst_label} {{key:$to}}))
    RETURN p
    LIMIT 1
    """
