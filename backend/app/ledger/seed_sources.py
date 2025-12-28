from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

from app.ledger.models import Base, SourceRegistry
from app.core.security import hash_api_key

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# ---- DEFINE SOURCES HERE ----
SOURCES = [
    {
        "source_id": "safaricom",
        "source_type": "telco",
        "classification_level": "RESTRICTED",
        "api_key": "safaricom-secret-key",
    },
    {
        "source_id": "kcb",
        "source_type": "bank",
        "classification_level": "RESTRICTED",
        "api_key": "kcb-secret-key",
    },
    {
        "source_id": "kra",
        "source_type": "gov",
        "classification_level": "INTERNAL",
        "api_key": "kra-secret-key",
    },
    {
        "source_id": "kpa",
        "source_type": "gov",
        "classification_level": "INTERNAL",
        "api_key": "kpa-secret-key",
    },
    {
        "source_id": "osint_sim",
        "source_type": "osint",
        "classification_level": "PUBLIC",
        "api_key": "osint-secret-key",
    },
]


def seed():
    db = SessionLocal()

    for src in SOURCES:
        exists = (
            db.query(SourceRegistry)
            .filter(SourceRegistry.source_id == src["source_id"])
            .first()
        )

        if exists:
            print(f"[SKIP] {src['source_id']} already exists")
            continue

        record = SourceRegistry(
            source_id=src["source_id"],
            source_type=src["source_type"],
            classification_level=src["classification_level"],
            api_key_hash=hash_api_key(src["api_key"]),
            is_active=True,
        )

        db.add(record)
        print(f"[ADD] {src['source_id']}")

    db.commit()
    db.close()


if __name__ == "__main__":
    seed()
