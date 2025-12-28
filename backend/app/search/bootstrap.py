import os
from opensearchpy import OpenSearch


def ensure_events_index(client: OpenSearch) -> str:
    index_name = os.getenv("OPENSEARCH_INDEX_EVENTS", "sentinel-events-v1")

    if client.indices.exists(index=index_name):
        return index_name

    body = {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "refresh_interval": "1s",
            }
        },
        "mappings": {
            "properties": {
                "event_hash": {"type": "keyword"},
                "event_type": {"type": "keyword"},
                "source_id": {"type": "keyword"},
                "source_type": {"type": "keyword"},
                "classification": {"type": "keyword"},
                "schema_version": {"type": "keyword"},
                "signature_valid": {"type": "boolean"},
                "occurred_at": {"type": "date"},
                "received_at": {"type": "date"},
                "anchors": {"type": "object", "enabled": True},
                "anchors_flat": {"type": "keyword"},  # e.g. ["ip:1.2.3.4","phone_h:abc..."]
                "payload": {"type": "object", "enabled": True},
            }
        },
    }

    client.indices.create(index=index_name, body=body)
    return index_name
