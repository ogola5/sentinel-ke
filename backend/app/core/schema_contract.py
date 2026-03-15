from __future__ import annotations

import logging
from typing import Dict, Iterable, Mapping

from sqlalchemy import Engine, text


log = logging.getLogger("sentinel.schema_contract")


REQUIRED_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "source_registry": ("section_code", "api_key_lookup"),
    "event_log": ("section_code",),
    "audit_log": ("section_code",),
    "event_entity_index": ("entity_type",),
    "entity_embedding": ("embedding_type",),
    "infra_cluster": ("cluster_key",),
    "containment_webhook": ("secret_enc",),
    "federation_partner": ("correlation_salt", "webhook_url", "webhook_secret_hash", "metadata_json"),
    "legal_authorization_grant": ("policy_version", "model_action_scope_json"),
}


def _column_exists(conn, *, table_name: str, column_name: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).fetchone()
    return bool(row)


def apply_schema_contract(engine: Engine) -> Dict[str, int]:
    """
    Apply idempotent DDL patches required by current backend models.

    This intentionally does not replace Alembic migrations; it is a safety net
    for environments where schema drift would otherwise break startup.
    """
    if engine.dialect.name != "postgresql":
        return {"applied": 0, "skipped": 1}

    statements: Iterable[str] = (
        "ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS section_code VARCHAR",
        "ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS api_key_lookup VARCHAR(64)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_source_registry_api_key_lookup ON source_registry (api_key_lookup)",
        "ALTER TABLE event_log ADD COLUMN IF NOT EXISTS section_code VARCHAR",
        "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS section_code VARCHAR",
        "ALTER TABLE event_entity_index ADD COLUMN IF NOT EXISTS entity_type VARCHAR",
        "UPDATE event_entity_index SET entity_type = split_part(entity_key, ':', 1) WHERE COALESCE(entity_type, '') = '' AND position(':' in entity_key) > 0",
        "CREATE INDEX IF NOT EXISTS ix_event_entity_type ON event_entity_index (entity_type)",
        "ALTER TABLE entity_embedding ADD COLUMN IF NOT EXISTS embedding_type VARCHAR DEFAULT 'gnn'",
        "ALTER TABLE infra_cluster ADD COLUMN IF NOT EXISTS cluster_key TEXT",
        "UPDATE infra_cluster SET cluster_key = concat('legacy:', cluster_id::text) WHERE COALESCE(cluster_key, '') = ''",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_infra_cluster_cluster_key ON infra_cluster (cluster_key)",
        "ALTER TABLE containment_webhook ADD COLUMN IF NOT EXISTS secret_enc TEXT",
        "ALTER TABLE containment_webhook DROP COLUMN IF EXISTS secret_hash",
        "ALTER TABLE federation_partner ADD COLUMN IF NOT EXISTS correlation_salt VARCHAR(64) DEFAULT ''",
        "ALTER TABLE federation_partner ADD COLUMN IF NOT EXISTS webhook_url VARCHAR(512)",
        "ALTER TABLE federation_partner ADD COLUMN IF NOT EXISTS webhook_secret_hash VARCHAR(64)",
        "ALTER TABLE federation_partner ADD COLUMN IF NOT EXISTS metadata_json JSONB DEFAULT '{}'::jsonb",
        "ALTER TABLE legal_authorization_grant ADD COLUMN IF NOT EXISTS policy_version VARCHAR DEFAULT 'v1'",
        "ALTER TABLE legal_authorization_grant ADD COLUMN IF NOT EXISTS model_action_scope_json JSONB DEFAULT '{}'::jsonb",
    )

    applied = 0
    skipped = 0
    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.execute(text(sql))
                applied += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                log.warning("schema_contract_patch_skipped sql=%s err=%s", sql[:80], exc)
    return {"applied": applied, "skipped": skipped}


def schema_contract_status(engine: Engine) -> Dict[str, object]:
    if engine.dialect.name != "postgresql":
        return {"ok": True, "missing": {}, "missing_count": 0}

    missing: Dict[str, list[str]] = {}
    with engine.connect() as conn:
        for table_name, columns in REQUIRED_COLUMNS.items():
            absent = [c for c in columns if not _column_exists(conn, table_name=table_name, column_name=c)]
            if absent:
                missing[table_name] = absent
    missing_count = sum(len(v) for v in missing.values())
    return {"ok": missing_count == 0, "missing": missing, "missing_count": missing_count}
