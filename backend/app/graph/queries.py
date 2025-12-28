# app/graph/queries.py
from __future__ import annotations


def q_entity_by_key() -> str:
    return """
    MATCH (n {key:$key})
    RETURN labels(n)[0] AS type, n.key AS key, n.last_seen AS last_seen
    """


def q_neighbors_subgraph(depth: int) -> str:
    # depth is validated before use
    return f"""
    MATCH (n {{key:$key}})
    CALL {{
      WITH n
      MATCH p=(n)-[r*1..{depth}]-(m)
      RETURN p
      LIMIT $limit
    }}
    RETURN p
    """


def q_shortest_path(max_hops: int) -> str:
    # max_hops is validated before use
    return f"""
    MATCH p = shortestPath((a {{key:$from}})-[*1..{max_hops}]-(b {{key:$to}}))
    RETURN p
    LIMIT 1
    """
