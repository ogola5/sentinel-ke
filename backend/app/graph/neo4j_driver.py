from __future__ import annotations

import os
from neo4j import GraphDatabase, Driver


_DISABLED_VALUES = {"", "disabled", "none", "off", "false", "inactive"}


class Neo4jDisabledError(RuntimeError):
    pass


def is_neo4j_enabled() -> bool:
    uri = os.getenv("NEO4J_URI", "").strip().lower()
    return uri not in _DISABLED_VALUES


def is_neo4j_disabled_error(exc: Exception) -> bool:
    return isinstance(exc, Neo4jDisabledError) or str(exc).strip().lower() == "neo4j_disabled"


def get_driver() -> Driver:
    if not is_neo4j_enabled():
        raise Neo4jDisabledError("neo4j_disabled")
    uri = os.environ["NEO4J_URI"]

    # 🔒 Force direct mode for single-node Neo4j
    if uri.startswith("neo4j://"):
        uri = uri.replace("neo4j://", "bolt://", 1)

    user = os.environ["NEO4J_USER"]
    pwd = os.environ["NEO4J_PASSWORD"]

    return GraphDatabase.driver(uri, auth=(user, pwd))
