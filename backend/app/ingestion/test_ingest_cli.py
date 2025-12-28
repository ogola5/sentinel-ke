from datetime import datetime, timezone

from app.ledger.db import SessionLocal
from app.ingestion.schemas import CanonicalEvent
from app.ingestion.service import IngestionService


def main():
    db = SessionLocal()
    try:
        svc = IngestionService(db, pseudonym_salt="demo-salt")

        e = CanonicalEvent(
            event_type="LOGIN_EVENT",
            occurred_at=datetime.now(timezone.utc),
            confidence=0.8,
            payload={"outcome": "failure", "ip": "1.2.3.4", "phone": "254700000000"},
            anchors={"ip": "1.2.3.4"},
        )

        # use seeded source key (from seed_sources.py)
        res1 = svc.ingest_event(event=e, source_api_key="safaricom-secret-key")
        print("INGEST 1:", res1)

        # ingest same event again -> should be duplicate
        res2 = svc.ingest_event(event=e, source_api_key="safaricom-secret-key")
        print("INGEST 2:", res2)

    finally:
        db.close()


if __name__ == "__main__":
    main()
