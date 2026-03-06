from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import logging
import os

from app.ledger.models import Base, SourceRegistry
from app.core.security import hash_api_key
from app.ledger.repository import _key_lookup_hash

log = logging.getLogger("sentinel.seed_sources")

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# ---- DEFINE SOURCES HERE ----
SOURCES = [
    {
        "source_id": "safaricom",
        "source_type": "telco",
        "section_code": "telecom",
        "classification_level": "RESTRICTED",
        "api_key": "safaricom-secret-key",
    },
    {
        "source_id": "kcb",
        "source_type": "bank",
        "section_code": "banking",
        "classification_level": "RESTRICTED",
        "api_key": "kcb-secret-key",
    },
    {
        "source_id": "kra",
        "source_type": "gov",
        "section_code": "revenue",
        "classification_level": "INTERNAL",
        "api_key": "kra-secret-key",
    },
    {
        "source_id": "kpa",
        "source_type": "gov",
        "section_code": "ports",
        "classification_level": "INTERNAL",
        "api_key": "kpa-secret-key",
    },
    {
        "source_id": "osint_sim",
        "source_type": "osint",
        "section_code": "osint",
        "classification_level": "PUBLIC",
        "api_key": "osint-secret-key",
    },
    {
        "source_id": "local_net_probe",
        "source_type": "sensor",
        "section_code": "soc",
        "classification_level": "INTERNAL",
        "api_key": "local-net-probe-secret-key",
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
            log.debug("seed_sources skip existing source_id=%s", src["source_id"])
            continue

        record = SourceRegistry(
            source_id=src["source_id"],
            source_type=src["source_type"],
            section_code=src["section_code"],
            classification_level=src["classification_level"],
            api_key_hash=hash_api_key(src["api_key"]),
            api_key_lookup=_key_lookup_hash(src["api_key"]),
            is_active=True,
        )

        db.add(record)
        log.info("seed_sources added source_id=%s", src["source_id"])

    db.commit()
    db.close()


if __name__ == "__main__":
    seed()
