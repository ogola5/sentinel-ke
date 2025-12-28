from __future__ import annotations

import os
from neo4j import GraphDatabase, Driver


def get_driver() -> Driver:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    pwd = os.environ["NEO4J_PASSWORD"]
    return GraphDatabase.driver(uri, auth=(user, pwd))
