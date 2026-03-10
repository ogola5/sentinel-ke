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


def _env_key(env_var: str, fallback: str) -> str:
    """Read API key from environment variable; fall back to placeholder if not set."""
    return os.environ.get(env_var, "").strip() or fallback


# ---- DEFINE SOURCES HERE ----
# API keys are read from environment variables so .env controls them.
# Fallback values are only used when the env var is absent (first-time dev setup).
SOURCES = [
    {
        "source_id": "safaricom",
        "source_type": "telco",
        "section_code": "telecom",
        "classification_level": "RESTRICTED",
        "api_key": _env_key("SAFARICOM_SOURCE_API_KEY", "safaricom-secret-key"),
    },
    {
        "source_id": "kcb",
        "source_type": "bank",
        "section_code": "banking",
        "classification_level": "RESTRICTED",
        "api_key": _env_key("KCB_SOURCE_API_KEY", "kcb-secret-key"),
    },
    {
        "source_id": "kra",
        "source_type": "gov",
        "section_code": "revenue",
        "classification_level": "INTERNAL",
        "api_key": _env_key("KRA_SOURCE_API_KEY", "kra-secret-key"),
    },
    {
        "source_id": "kpa",
        "source_type": "gov",
        "section_code": "ports",
        "classification_level": "INTERNAL",
        "api_key": _env_key("KPA_SOURCE_API_KEY", "kpa-secret-key"),
    },
    {
        "source_id": "osint_sim",
        "source_type": "osint",
        "section_code": "osint",
        "classification_level": "PUBLIC",
        "api_key": _env_key("OSINT_SOURCE_API_KEY", "osint-secret-key"),
    },
    {
        "source_id": "feodo_live",
        "source_type": "osint",
        "section_code": "osint",
        "classification_level": "PUBLIC",
        "api_key": _env_key("FEODO_SOURCE_API_KEY", "feodo-live-secret-key"),
    },
    {
        "source_id": "urlhaus_live",
        "source_type": "osint",
        "section_code": "osint",
        "classification_level": "PUBLIC",
        "api_key": _env_key("URLHAUS_SOURCE_API_KEY", "urlhaus-live-secret-key"),
    },
    {
        "source_id": "otx_live",
        "source_type": "osint",
        "section_code": "osint",
        "classification_level": "PUBLIC",
        "api_key": _env_key("OTX_SOURCE_API_KEY", "otx-live-secret-key"),
    },
    {
        "source_id": "ppra_ocds",
        "source_type": "gov",
        "section_code": "economy",
        "classification_level": "PUBLIC",
        "api_key": _env_key("PPRA_SOURCE_API_KEY", "ppra-ocds-secret-key"),
    },
    {
        "source_id": "paysim",
        "source_type": "osint",
        "section_code": "economy",
        "classification_level": "PUBLIC",
        "api_key": _env_key("PAYSIM_SOURCE_API_KEY", "paysim-secret-key"),
    },
    {
        "source_id": "unsw_nb15",
        "source_type": "osint",
        "section_code": "soc",
        "classification_level": "PUBLIC",
        "api_key": _env_key("UNSW_SOURCE_API_KEY", "unsw-nb15-secret-key"),
    },
    {
        "source_id": "local_net_probe",
        "source_type": "sensor",
        "section_code": "soc",
        "classification_level": "INTERNAL",
        "api_key": _env_key("LOCAL_NET_PROBE_SOURCE_API_KEY", "local-net-probe-secret-key"),
    },
]


def seed():
    db = SessionLocal()

    for src in SOURCES:
        existing = (
            db.query(SourceRegistry)
            .filter(SourceRegistry.source_id == src["source_id"])
            .first()
        )

        new_hash = hash_api_key(src["api_key"])
        new_lookup = _key_lookup_hash(src["api_key"])

        if existing:
            # Update the key hashes if the env var has changed since last seed
            if existing.api_key_hash != new_hash:
                existing.api_key_hash = new_hash
                existing.api_key_lookup = new_lookup
                db.add(existing)
                log.info("seed_sources updated key source_id=%s", src["source_id"])
            else:
                log.debug("seed_sources skip unchanged source_id=%s", src["source_id"])
            continue

        record = SourceRegistry(
            source_id=src["source_id"],
            source_type=src["source_type"],
            section_code=src["section_code"],
            classification_level=src["classification_level"],
            api_key_hash=new_hash,
            api_key_lookup=new_lookup,
            is_active=True,
        )

        db.add(record)
        log.info("seed_sources added source_id=%s", src["source_id"])

    db.commit()
    db.close()


if __name__ == "__main__":
    seed()
