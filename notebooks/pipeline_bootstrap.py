from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional


def _resolve_paths() -> tuple[Path, Path, Path]:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent,  # repo root when notebooks are inside repo/notebooks
        here.parent,         # fallback if notebooks are root-mounted
        Path.cwd(),
        Path.cwd().parent,
        Path("/app"),        # docker notebook service backend mount
    ]

    seen = set()
    uniq_candidates = []
    for c in candidates:
        r = c.resolve()
        if r in seen:
            continue
        seen.add(r)
        uniq_candidates.append(r)

    for base in uniq_candidates:
        if (base / "backend" / "app").exists():
            root = base
            backend = base / "backend"
            return root, backend, root / ".env"
        if (base / "app").exists() and (base / "requirements.txt").exists():
            # backend-only mount (e.g. /app in docker notebook service)
            root = base
            backend = base
            return root, backend, root / ".env"

    # Conservative fallback for local runs.
    root = here.parent.parent
    backend = root / "backend"
    return root, backend, root / ".env"


ROOT_DIR, BACKEND_DIR, ENV_PATH = _resolve_paths()


def _sql_text():
    try:
        from sqlalchemy import text
    except Exception as exc:  # pragma: no cover - defensive import guard
        raise RuntimeError(
            "sqlalchemy is not available in this notebook kernel. "
            "Use the project notebook container/kernel where backend dependencies are installed."
        ) from exc
    return text


def _parse_dotenv(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def _is_inside_docker() -> bool:
    if Path("/.dockerenv").exists():
        return True
    cgroup = Path("/proc/1/cgroup")
    if cgroup.exists():
        txt = cgroup.read_text(encoding="utf-8", errors="ignore").lower()
        if "docker" in txt or "containerd" in txt or "kubepods" in txt:
            return True
    return False


def _normalize_database_url(url: str) -> str:
    """
    Make DATABASE_URL work in both Docker and VS Code local notebook kernels.

    If url points at docker hostname `postgres` and we are on host kernel,
    rewrite to localhost:5433 (project's compose mapping).
    """
    value = str(url or "").strip()
    if not value:
        return value

    if value.startswith("postgres://"):
        value = f"postgresql+psycopg2://{value[len('postgres://'):]}"
    elif value.startswith("postgresql://") and "+psycopg2" not in value:
        value = f"postgresql+psycopg2://{value[len('postgresql://'):]}"

    if not _is_inside_docker():
        local_port = os.environ.get("POSTGRES_PORT", "5433").strip() or "5433"
        value = re.sub(
            r"@postgres(?::\d+)?",
            f"@localhost:{local_port}",
            value,
            count=1,
        )
    return value


def bootstrap_environment(*, force_reload: bool = False) -> Dict[str, object]:
    """
    Prepare notebook runtime for backend imports and DB access.
    """
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    env_map = _parse_dotenv(ENV_PATH)
    for k, v in env_map.items():
        if force_reload or k not in os.environ:
            os.environ[k] = v

    # Build DATABASE_URL from component vars if not explicitly set.
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5433")
        db = os.environ.get("POSTGRES_DB", "sentinel")
        user = os.environ.get("POSTGRES_USER", "sentinel")
        pw = os.environ.get("POSTGRES_PASSWORD", "sentinel")
        db_url = f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{db}"

    db_url = _normalize_database_url(db_url)
    os.environ["DATABASE_URL"] = db_url

    return {
        "root_dir": str(ROOT_DIR),
        "backend_dir": str(BACKEND_DIR),
        "inside_docker": _is_inside_docker(),
        "database_url": db_url,
        "ingest_api_key_set": bool(os.environ.get("INGEST_API_KEY")),
    }


def _import_db():
    # Import lazily after env bootstrap so SessionLocal binds to the right DB URL.
    from app.ledger.db import SessionLocal

    return SessionLocal


def get_db_session():
    SessionLocal = _import_db()
    return SessionLocal()


def _migration_hint() -> str:
    return (
        "Database schema is behind code. Run migrations, then retry:\n"
        "  docker compose exec -w /app backend alembic -c alembic.ini upgrade head"
    )


def test_db_connection() -> Dict[str, object]:
    text = _sql_text()
    db = get_db_session()
    try:
        row = db.execute(text("SELECT current_database(), current_user")).fetchone()
        return {
            "ok": True,
            "database": str(row[0]) if row else None,
            "user": str(row[1]) if row else None,
        }
    finally:
        db.close()


def check_notebook_prerequisites() -> Dict[str, object]:
    """
    Validate minimum DB schema required by notebook pipeline.
    """
    text = _sql_text()
    db = get_db_session()
    checks = {
        "source_registry": {"section_code", "classification_level", "api_key_lookup"},
        "event_log": {"event_type", "occurred_at", "section_code"},
        "audit_log": {"section_code"},
        "graph_feature_snapshot": {"window_key", "features"},
        "entity_embedding": {"embedding_type"},
    }
    missing: Dict[str, list[str]] = {}
    try:
        for table_name, required in checks.items():
            rows = db.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            ).fetchall()
            existing = {str(r[0]) for r in rows}
            lacking = sorted(required - existing)
            if lacking:
                missing[table_name] = lacking
        if missing:
            return {"ok": False, "missing": missing, "hint": _migration_hint()}
        return {"ok": True, "missing": {}, "hint": None}
    finally:
        db.close()


def repair_notebook_schema() -> Dict[str, object]:
    """
    Apply minimal idempotent fixes for legacy local DBs so notebook pipeline can run.
    """
    text = _sql_text()
    db = get_db_session()
    applied: list[str] = []
    try:
        db.execute(text("ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS section_code VARCHAR"))
        applied.append("source_registry.section_code")
        db.execute(text("ALTER TABLE event_log ADD COLUMN IF NOT EXISTS section_code VARCHAR"))
        applied.append("event_log.section_code")
        db.execute(text("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS section_code VARCHAR"))
        applied.append("audit_log.section_code")
        db.execute(text("ALTER TABLE entity_embedding ADD COLUMN IF NOT EXISTS embedding_type VARCHAR DEFAULT 'gnn'"))
        applied.append("entity_embedding.embedding_type")
        db.execute(
            text(
                """
                UPDATE source_registry
                SET section_code = COALESCE(section_code, source_type, 'legacy')
                WHERE section_code IS NULL
                """
            )
        )
        db.commit()
        return {"ok": True, "applied": applied}
    finally:
        db.close()


def seed_default_sources() -> Dict[str, object]:
    from app.ledger.seed_sources import seed

    try:
        seed()
        return {"ok": True, "seeded": True}
    except Exception as exc:  # pragma: no cover - runtime guard for stale DB schema
        message = str(exc)
        if "UndefinedColumn" in message or "does not exist" in message:
            raise RuntimeError(f"{message}\n\n{_migration_hint()}") from exc
        raise


def run_feature_snapshots(
    *,
    window_keys: Iterable[str] = ("Wshort", "Wmid", "Wlong"),
    max_entities: int = 5000,
) -> Dict[str, int]:
    from app.analytics.layer3.graph_feature_worker import run_once

    out: Dict[str, int] = {}
    db = get_db_session()
    try:
        for key in window_keys:
            out[str(key)] = int(
                run_once(
                    db=db,
                    window_key=str(key),
                    max_entities=max_entities,
                )
                or 0
            )
        return out
    finally:
        db.close()


def train_gnn(
    *,
    domain: str = "cyber",
    window_key: Optional[str] = None,
    epochs: Optional[int] = None,
    model_version: Optional[str] = None,
) -> Dict[str, object]:
    d = str(domain or "cyber").strip().lower()
    db = get_db_session()
    try:
        if d == "corruption":
            from app.analytics.corruption.train_worker import run_once as run_corruption
            from app.analytics.corruption.feature_builder import CORRUPTION_WINDOW_KEY
            return dict(
                run_corruption(
                    db=db,
                    window_key=window_key or CORRUPTION_WINDOW_KEY,
                    epochs=int(epochs or 60),
                    model_version=model_version or "corruption-gnn-v1",
                )
            )
        from app.analytics.layer3.gnn_train_worker import run_once as run_cyber
        from app.core.config import settings
        return dict(
            run_cyber(
                db=db,
                window_key=window_key or settings.gnn_window_key,
                edge_backend=settings.gnn_edge_backend,
                max_entities=settings.gnn_max_entities,
                max_edges=settings.gnn_max_edges,
                min_edge_weight=settings.gnn_min_edge_weight,
                epochs=int(epochs or settings.gnn_epochs),
                hidden_dim=settings.gnn_hidden_dim,
                embed_dim=settings.gnn_embed_dim,
                dropout=settings.gnn_dropout,
                learning_rate=settings.gnn_learning_rate,
                weight_decay=settings.gnn_weight_decay,
                seed=settings.gnn_seed,
                model_version=model_version or settings.gnn_model_version,
                prediction_type=settings.gnn_prediction_type,
                artifact_dir=settings.gnn_artifact_dir,
            )
        )
    finally:
        db.close()


def ingest_kev_epss(
    *,
    source_api_key: str,
    asset_id: str,
    kev_file: Optional[str] = None,
) -> Dict[str, object]:
    from app.integrations.real_data_pipeline import (
        build_kev_epss_records,
        fetch_epss_lookup,
        ingest_records_via_connectors,
        load_kev_rows,
    )

    kev_rows = load_kev_rows(kev_file=kev_file)
    cves = [str(r.get("cveID") or r.get("cve") or "").strip().upper() for r in kev_rows]
    epss = fetch_epss_lookup(cves)
    records = build_kev_epss_records(kev_rows, asset_id=asset_id, epss_lookup=epss, confidence=0.95)

    db = get_db_session()
    try:
        stats = ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=source_api_key,
            classification="RESTRICTED",
        )
        return {
            "job": "kev-epss",
            "total_records": stats.total_records,
            "accepted": stats.accepted,
            "duplicates": stats.duplicates,
            "skipped": stats.skipped,
            "errors": stats.errors,
        }
    finally:
        db.close()


def ingest_traffic_file(
    *,
    dataset: str,
    input_file: str,
    source_api_key: str,
    service_id_prefix: str = "external",
    dataset_name: Optional[str] = None,
) -> Dict[str, object]:
    from app.integrations.real_data_pipeline import (
        _iter_caida_records,
        _iter_cic_records,
        ingest_records_via_connectors,
        iter_rows_from_path,
    )

    if input_file is None:
        raise ValueError(
            "input_file is None — generate a synthetic file first:\n"
            "  from seed_realistic_data import generate_cic_csv, generate_caida_csv\n"
            "  cic_path   = generate_cic_csv('data/kenya_cic_synthetic.csv')\n"
            "  caida_path = generate_caida_csv('data/kenya_caida_synthetic.csv')\n"
            "Then pass the returned path as input_file."
        )
    ds = str(dataset).strip().lower()
    rows = iter_rows_from_path(input_file)
    if ds == "cic":
        records = _iter_cic_records(
            rows,
            service_id_prefix=service_id_prefix,
            dataset_name=dataset_name or "cic_ids2018",
        )
    elif ds == "caida":
        records = _iter_caida_records(
            rows,
            service_id_prefix=service_id_prefix,
            dataset_name=dataset_name or "caida_ddos",
        )
    else:
        raise ValueError("dataset must be one of: cic, caida")

    db = get_db_session()
    try:
        stats = ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=source_api_key,
            classification="RESTRICTED",
        )
        return {
            "job": f"traffic:{ds}",
            "input_file": input_file,
            "total_records": stats.total_records,
            "accepted": stats.accepted,
            "duplicates": stats.duplicates,
            "skipped": stats.skipped,
            "errors": stats.errors,
        }
    finally:
        db.close()


def ingest_paysim_file(
    *,
    input_file: str,
    source_api_key: str,
    dataset_name: Optional[str] = None,
) -> Dict[str, object]:
    """
    Ingest a PaySim-format CSV (real or synthetic) as M-Pesa TRANSACTION_EVENTs.

    Only fraud rows (isFraud=1) are ingested — they produce the mule-chain graph
    structure (TRANSFER → TRANSFER → CASH_OUT) that the cyber GNN learns from.
    Benign transactions are represented by other event sources already in the graph.

    Real PaySim CSV: https://www.kaggle.com/datasets/ntnu-testimon/paysim1
    Synthetic:       generate_paysim_csv() in seed_realistic_data.py
    """
    from app.integrations.real_data_pipeline import (
        _iter_paysim_records,
        ingest_records_via_connectors,
        iter_rows_from_path,
    )

    if input_file is None:
        raise ValueError(
            "input_file is None — generate a synthetic file first:\n"
            "  from seed_realistic_data import generate_paysim_csv\n"
            "  paysim_path = generate_paysim_csv('data/kenya_paysim_synthetic.csv')\n"
            "Then pass the returned path as input_file."
        )

    rows = iter_rows_from_path(input_file)
    records = _iter_paysim_records(
        rows,
        dataset_name=dataset_name or "paysim_ke",
    )

    db = get_db_session()
    try:
        stats = ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=source_api_key,
            classification="RESTRICTED",
        )
        return {
            "job": "paysim",
            "input_file": input_file,
            "total_records": stats.total_records,
            "accepted": stats.accepted,
            "duplicates": stats.duplicates,
            "skipped": stats.skipped,
            "errors": stats.errors,
        }
    finally:
        db.close()


def ingest_ocds_file(
    *,
    input_file: str,
    source_api_key: str,
) -> Dict[str, object]:
    """
    Parse an OCDS-1.1 JSON releases file and write aggregated procurement
    signals directly to graph_feature_snapshot (corruption domain).

    Bypasses the connector/event_log path because the corruption GNN reads
    directly from graph_feature_snapshot via snapshot_to_corruption_vector().
    """
    import json
    from datetime import datetime, timezone
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if input_file is None:
        raise ValueError(
            "input_file is None — generate a synthetic file first:\n"
            "  from seed_realistic_data import generate_ocds_json\n"
            "  ocds_path = generate_ocds_json('data/kenya_ocds_synthetic.json')\n"
            "Then pass the returned path as input_file."
        )

    with open(input_file, encoding="utf-8") as fh:
        releases = json.load(fh)

    # ── aggregate per-party (buyer + supplier) ────────────────────────────────
    from collections import defaultdict

    party_stats: Dict[str, dict] = defaultdict(
        lambda: {
            "total_value_ksh": 0.0,
            "counterparty_ids": set(),
            "amendment_count": 0,
            "total_contracts": 0,
            "fy_end_count": 0,
            "director_conflict": False,
            "price_inflated": False,
            "single_source": False,
            "shell_company": False,
        }
    )

    for rel in releases:
        meta = rel.get("_meta", {})
        awards = rel.get("awards", [])
        buyer_id = (rel.get("buyer") or {}).get("id", "")
        amendments = rel.get("contracts", [{}])[0].get("amendments", [])
        n_amendments = len(amendments)

        # date for FY-end detection (Kenya FY ends 30 Jun)
        date_str = rel.get("date", "")
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            is_fy_end = dt.month in (5, 6)
        except Exception:
            is_fy_end = False

        for award in awards:
            value_ksh = float((award.get("value") or {}).get("amount", 0) or 0)
            supplier_id = ""
            for s in award.get("suppliers", []):
                supplier_id = s.get("id", "")
                if not supplier_id:
                    continue

                for pid in (buyer_id, supplier_id):
                    if not pid:
                        continue
                    ps = party_stats[pid]
                    ps["total_value_ksh"] += value_ksh
                    ps["total_contracts"] += 1
                    ps["amendment_count"] += n_amendments
                    if is_fy_end:
                        ps["fy_end_count"] += 1
                    if buyer_id and supplier_id:
                        ps["counterparty_ids"].add(
                            supplier_id if pid == buyer_id else buyer_id
                        )
                    if meta.get("is_director_conflict"):
                        ps["director_conflict"] = True
                    if meta.get("is_price_inflated"):
                        ps["price_inflated"] = True
                    if meta.get("is_single_source"):
                        ps["single_source"] = True
                    if meta.get("is_shell"):
                        ps["shell_company"] = True

    # ── build feature vectors and upsert ─────────────────────────────────────
    from app.analytics.ai_models import GraphFeatureSnapshot

    text = _sql_text()
    db = get_db_session()
    upserted = 0
    try:
        now = datetime.now(timezone.utc)
        # Fixed window: full FY 2024/25 (Kenya fiscal year)
        window_start = datetime(2024, 7, 1, tzinfo=timezone.utc)
        window_end = datetime(2025, 6, 30, 23, 59, 59, tzinfo=timezone.utc)

        for entity_key, ps in party_stats.items():
            n_contracts = max(1, ps["total_contracts"])
            amendment_ratio = ps["amendment_count"] / n_contracts
            fy_end_fraction = ps["fy_end_count"] / n_contracts
            counterparty_count = len(ps["counterparty_ids"])

            risk_flags: list[str] = []
            if ps["price_inflated"]:
                risk_flags.append("PRICE_INFLATION")
            if ps["director_conflict"]:
                risk_flags.append("DIRECTOR_CONFLICT")
            if ps["shell_company"]:
                risk_flags.append("SHELL_COMPANY")
            if ps["single_source"] and ps["total_value_ksh"] > 5_000_000:
                risk_flags.append("AUDIT_FINDING")

            features = {
                "entity_type": "procurement_entity",
                "total_value_ksh": ps["total_value_ksh"],
                "counterparty_count": counterparty_count,
                "amendment_ratio": amendment_ratio,
                "fy_end_fraction": fy_end_fraction,
                "total_contracts": n_contracts,
                "director_conflict": ps["director_conflict"],
                "price_inflated": ps["price_inflated"],
                "single_source": ps["single_source"],
                "shell_company": ps["shell_company"],
                "risk_flags": risk_flags,
                "source": "ocds_ingest",
            }

            stmt = pg_insert(GraphFeatureSnapshot).values(
                entity_key=entity_key,
                entity_type="procurement_entity",
                window_key="Wcorruption",
                window_start=window_start,
                window_end=window_end,
                features=features,
                risk_flags=risk_flags,
                created_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["entity_key", "window_key", "window_end"],
                set_={
                    "features": stmt.excluded.features,
                    "risk_flags": stmt.excluded.risk_flags,
                    "created_at": stmt.excluded.created_at,
                },
            )
            db.execute(stmt)
            upserted += 1

        db.commit()
        return {
            "job": "ocds",
            "input_file": input_file,
            "parties_upserted": upserted,
            "releases_parsed": len(releases),
        }
    finally:
        db.close()


def query_active_learning(
    *,
    domain: str = "cyber",
    window_key: Optional[str] = None,
    top_k: int = 50,
) -> list:
    """
    Return the top-k most uncertain entities for analyst review.

    Uses MC Dropout uncertainty scores stored in ai_prediction to surface
    nodes where the model is least confident — the core of uncertainty-based
    active learning (as used in Anthropic's RLHF pipeline and Scale AI).

    Analysts should review these entities next; calling apply_feedback_to_snapshots()
    after labelling them gives maximum accuracy improvement per annotation hour.

    Returns a list of dicts: {entity_key, uncertainty, score, prediction_type}
    sorted by uncertainty descending.
    """
    text = _sql_text()
    db = get_db_session()
    wk = window_key or ("Wcorruption" if domain == "corruption" else "Wmid")
    try:
        rows = db.execute(
            text(
                """
                SELECT entity_key, uncertainty, score, prediction_type
                FROM ai_prediction
                WHERE window_key = :wk
                  AND uncertainty IS NOT NULL
                ORDER BY uncertainty DESC
                LIMIT :top_k
                """
            ),
            {"wk": wk, "top_k": top_k},
        ).fetchall()
        return [
            {
                "entity_key":      str(r[0]),
                "uncertainty":     round(float(r[1] or 0), 4),
                "score":           round(float(r[2] or 0), 4),
                "prediction_type": str(r[3] or ""),
            }
            for r in rows
        ]
    finally:
        db.close()


def apply_feedback_to_snapshots(
    *,
    domain: str = "cyber",
    window_key: Optional[str] = None,
    limit: int = 10_000,
) -> Dict[str, int]:
    """
    Pull accepted AIFeedbackLabel rows and stamp their risk_flags into the
    corresponding graph_feature_snapshot rows before the next GNN training run.

    This does NOT modify GNN code — it writes ground-truth signal directly
    into the feature store so the trainer picks it up on next epoch.
    """
    text = _sql_text()
    db = get_db_session()
    wk = window_key or ("Wcorruption" if domain == "corruption" else "Wmid")
    updated = 0
    skipped = 0
    try:
        # feedback_label=1 → analyst confirmed threat; 0 → false positive
        rows = db.execute(
            text(
                """
                SELECT entity_key, feedback_label
                FROM ai_feedback_label
                WHERE status = 'accepted'
                  AND feedback_label = 1
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"lim": limit},
        ).fetchall()

        for entity_key, feedback_label in rows:
            flag = "ANALYST_CONFIRMED_THREAT"
            existing = db.execute(
                text(
                    """
                    SELECT id, risk_flags
                    FROM graph_feature_snapshot
                    WHERE entity_key = :ek AND window_key = :wk
                    ORDER BY window_end DESC
                    LIMIT 1
                    """
                ),
                {"ek": entity_key, "wk": wk},
            ).fetchone()
            if not existing:
                skipped += 1
                continue
            snap_id, current_flags = existing
            flags: list = list(current_flags or [])
            if flag not in flags:
                flags.append(flag)
            db.execute(
                text(
                    "UPDATE graph_feature_snapshot "
                    "SET risk_flags = :flags::jsonb "
                    "WHERE id = :sid"
                ),
                {"flags": str(flags).replace("'", '"'), "sid": str(snap_id)},
            )
            updated += 1

        db.commit()
        return {"domain": domain, "window_key": wk, "updated": updated, "skipped": skipped}
    finally:
        db.close()


def retrain_with_feedback(
    *,
    domain: str = "cyber",
    window_key: Optional[str] = None,
    epochs: Optional[int] = None,
    model_version: Optional[str] = None,
    feedback_limit: int = 10_000,
) -> Dict[str, object]:
    """
    One-shot: apply analyst feedback labels → retrain GNN on the updated snapshots.
    Returns combined feedback stats + training result.
    """
    feedback_stats = apply_feedback_to_snapshots(
        domain=domain,
        window_key=window_key,
        limit=feedback_limit,
    )
    train_result = train_gnn(
        domain=domain,
        window_key=window_key,
        epochs=epochs,
        model_version=model_version,
    )
    return {"feedback": feedback_stats, "training": train_result}


def event_type_counts_last_24h() -> Dict[str, int]:
    text = _sql_text()
    db = get_db_session()
    try:
        rows = db.execute(
            text(
                """
                SELECT event_type, COUNT(*)
                FROM event_log
                WHERE occurred_at >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '24 hours'
                GROUP BY event_type
                ORDER BY COUNT(*) DESC
                """
            )
        ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}
    finally:
        db.close()
