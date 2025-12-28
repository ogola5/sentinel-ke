from datetime import datetime, timezone

from app.ingestion.schemas import CanonicalEvent
from app.graph.projector import project_event_to_delta


def main():
    e = CanonicalEvent(
        event_type="LOGIN_EVENT",
        occurred_at=datetime(2025, 12, 28, 10, 18, 0, tzinfo=timezone.utc),
        confidence=0.9,
        payload={"outcome": "failure", "ip": "5.6.7.8", "endpoint": "/api/login"},
        anchors={
            "ip": "5.6.7.8",
            "person_h": "abc123",
            "device_id": "device-001",
            "service_id": "eCitizen",
            "endpoint": "/api/login",
        },
    )

    h = "718fbd8579a9936e53be9985584d22ebec91d924a642626b9000d04d6256a998"
    d = project_event_to_delta(event=e, event_hash=h)

    print("EVENT_HASH:", d.event_hash)
    print("NODES:", len(d.nodes))
    for n in d.nodes:
        print("  ", n)

    print("EDGES:", len(d.edges))
    for ed in d.edges:
        print("  ", ed)


if __name__ == "__main__":
    main()
