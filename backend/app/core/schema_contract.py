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


def _constraint_matches(conn, *, table_name: str, constraint_name: str, definition: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = :table_name
              AND c.conname = :constraint_name
              AND pg_get_constraintdef(c.oid) = :definition
            LIMIT 1
            """
        ),
        {
            "table_name": table_name,
            "constraint_name": constraint_name,
            "definition": definition,
        },
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
        """
        DO $$
        DECLARE
            expected_def text := 'UNIQUE (entity_key, prediction_type, window_key, window_end)';
            current_def text;
        BEGIN
            SELECT pg_get_constraintdef(c.oid)
            INTO current_def
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'ai_prediction'
              AND c.conname = 'uq_ai_prediction'
            LIMIT 1;

            IF current_def IS NOT NULL AND current_def <> expected_def THEN
                DELETE FROM ai_prediction stale
                USING ai_prediction newer
                WHERE stale.entity_key = newer.entity_key
                  AND stale.prediction_type = newer.prediction_type
                  AND stale.window_key = newer.window_key
                  AND stale.window_end = newer.window_end
                  AND (
                    stale.created_at < newer.created_at
                    OR (
                        stale.created_at = newer.created_at
                        AND stale.id::text < newer.id::text
                    )
                  );
                ALTER TABLE ai_prediction DROP CONSTRAINT uq_ai_prediction;
                current_def := NULL;
            ELSIF current_def IS NULL AND EXISTS (
                SELECT 1
                FROM pg_class i
                JOIN pg_index ix ON i.oid = ix.indexrelid
                JOIN pg_class t ON t.oid = ix.indrelid
                WHERE t.relname = 'ai_prediction'
                  AND i.relname = 'uq_ai_prediction'
            ) THEN
                DROP INDEX IF EXISTS uq_ai_prediction;
            END IF;

            IF current_def IS DISTINCT FROM expected_def THEN
                DELETE FROM ai_prediction stale
                USING ai_prediction newer
                WHERE stale.entity_key = newer.entity_key
                  AND stale.prediction_type = newer.prediction_type
                  AND stale.window_key = newer.window_key
                  AND stale.window_end = newer.window_end
                  AND (
                    stale.created_at < newer.created_at
                    OR (
                        stale.created_at = newer.created_at
                        AND stale.id::text < newer.id::text
                    )
                  );
                ALTER TABLE ai_prediction
                ADD CONSTRAINT uq_ai_prediction UNIQUE (entity_key, prediction_type, window_key, window_end);
            END IF;
        END $$;
        """,
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
    for sql in statements:
        try:
            with engine.begin() as conn:
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
        if not _constraint_matches(
            conn,
            table_name="ai_prediction",
            constraint_name="uq_ai_prediction",
            definition="UNIQUE (entity_key, prediction_type, window_key, window_end)",
        ):
            missing.setdefault("ai_prediction", []).append("uq_ai_prediction(window_key)")
    missing_count = sum(len(v) for v in missing.values())
    return {"ok": missing_count == 0, "missing": missing, "missing_count": missing_count}
