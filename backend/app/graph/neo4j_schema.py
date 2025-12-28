from __future__ import annotations

from neo4j import Driver


NODE_LABELS = [
    "Person", "Phone", "Account", "Device", "IP", "Domain", "URL",
    "Service", "Endpoint", "Provider", "Campaign", "InfraCluster", "Case",
]


def ensure_schema(driver: Driver, database: str) -> None:
    """
    Create uniqueness constraints for each label on (key).
    Neo4j 5 supports IF NOT EXISTS.
    """
    cyphers: list[str] = []
    for label in NODE_LABELS:
        cyphers.append(
            f"CREATE CONSTRAINT {label.lower()}_key_unique IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.key IS UNIQUE"
        )
        cyphers.append(
            f"CREATE INDEX {label.lower()}_last_seen IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.last_seen)"
        )

    with driver.session(database=database) as s:
        for q in cyphers:
            s.run(q)
