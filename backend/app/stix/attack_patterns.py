from app.stix.ids import stix_id


def ddos_attack_pattern() -> dict:
    """
    Canonical STIX Attack Pattern for DDoS.
    Stable ID so multiple campaigns reference the same pattern.
    """
    return {
        "type": "attack-pattern",
        "spec_version": "2.1",
        "id": stix_id("attack-pattern", "ddos"),
        "name": "Distributed Denial of Service",
        "description": (
            "An attacker attempts to make a service unavailable "
            "by overwhelming it with traffic from multiple sources."
        ),
        "external_references": [
            {
                "source_name": "mitre-attack",
                "external_id": "T1499",
                "url": "https://attack.mitre.org/techniques/T1499/",
            }
        ],
    }
