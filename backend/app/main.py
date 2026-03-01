import logging
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text

from app.ledger.models import Base

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.error_contract import install_error_handlers
from app.api.router_registry import build_router_mounts, build_tags_metadata
from app.auth.service import AuthService
from app.core.config import settings
from app.core.http_hardening import install_http_hardening
from app.core.rate_limit import limiter
from app.core.runtime_hardening import enforce_runtime_hardening
from app.search.opensearch import get_client as get_os_client
from app.graph.neo4j_driver import get_driver
from app.ledger.db import SessionLocal, engine
import app.db.registry  # noqa: F401  # ensure all models are registered

log = logging.getLogger("sentinel.main")


def _ensure_webhook_schema() -> None:
    """Migrate containment_webhook: rename secret_hash → secret_enc (Fernet ciphertext)."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'containment_webhook'
                    ) THEN
                        ALTER TABLE containment_webhook
                            ADD COLUMN IF NOT EXISTS secret_enc TEXT;
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'containment_webhook'
                              AND column_name = 'secret_hash'
                        ) THEN
                            ALTER TABLE containment_webhook DROP COLUMN secret_hash;
                        END IF;
                    END IF;
                END $$;
                """
            )
        )


def _ensure_api_key_lookup_column() -> None:
    """Add api_key_lookup index column to source_registry for O(1) key resolution."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE source_registry "
            "ADD COLUMN IF NOT EXISTS api_key_lookup VARCHAR(64);"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_source_registry_api_key_lookup "
            "ON source_registry (api_key_lookup);"
        ))


def _ensure_infra_cluster_schema() -> None:
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE infra_cluster
                ADD COLUMN IF NOT EXISTS cluster_key TEXT
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE infra_cluster
                SET cluster_key = concat('legacy:', cluster_id::text)
                WHERE COALESCE(cluster_key, '') = ''
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_infra_cluster_cluster_key
                ON infra_cluster (cluster_key)
                """
            )
        )


def _register_routers(app: FastAPI) -> None:
    for mount in build_router_mounts(ai_enabled=settings.ai_api_enabled):
        if mount.dependencies:
            app.include_router(mount.router, dependencies=list(mount.dependencies))
        else:
            app.include_router(mount.router)


def _register_lifecycle(app: FastAPI) -> None:
    @app.on_event("startup")
    def startup() -> None:
        enforce_runtime_hardening(settings, logger=log)

        if settings.db_auto_create:
            Base.metadata.create_all(bind=engine)
        else:
            log.info("db_auto_create_disabled; skipping Base.metadata.create_all")

        _ensure_api_key_lookup_column()
        _ensure_infra_cluster_schema()
        _ensure_webhook_schema()
        try:
            db = SessionLocal()
            try:
                out = AuthService(db).bootstrap_defaults()
                log.info("auth_bootstrap=%s", out)
            finally:
                db.close()
        except Exception:
            log.exception("auth_bootstrap_failed")


def _register_operational_routes(app: FastAPI) -> None:
    @app.get("/health", tags=["ops"])
    def health() -> dict:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        # Check whether a trained GNN artifact is available.
        # Trust the DB record — the .pt file may live on the GNN worker's disk,
        # not on the web service's filesystem.
        gnn_loaded = False
        gnn_model_version = None
        gnn_metrics: dict = {}
        federation_partners = 0
        try:
            from app.analytics.ai_models import GNNTrainingRun  # noqa: PLC0415
            from app.federation.models import FederationPartner   # noqa: PLC0415
            db = SessionLocal()
            try:
                run = (
                    db.query(GNNTrainingRun)
                    .filter(GNNTrainingRun.artifact_path.isnot(None))
                    .order_by(GNNTrainingRun.created_at.desc())
                    .first()
                )
                if run and run.artifact_path:
                    gnn_loaded = True
                    gnn_model_version = str(run.model_version)
                    gnn_metrics = {
                        "auc":            round(float(run.auc), 4)       if run.auc       is not None else None,
                        "precision":      round(float(run.precision), 4) if run.precision is not None else None,
                        "node_count":     run.node_count,
                        "edge_count":     run.edge_count,
                        "positive_count": run.positive_count,
                        "feature_dim":    run.feature_dim,
                        "prediction_type": run.prediction_type,
                    }
                federation_partners = (
                    db.query(FederationPartner)
                    .filter(FederationPartner.is_active == True)  # noqa: E712
                    .count()
                )
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            pass  # table may not exist yet on first boot

        return {
            "status":               "ok",
            "gnn_loaded":           gnn_loaded,
            "gnn_model_version":    gnn_model_version,
            "gnn_metrics":          gnn_metrics,
            "federation_partners":  federation_partners,
            "capabilities": [
                "cyber_gnn",
                "corruption_gnn",
                "ddos_detection",
                "federated_intelligence",
                "post_quantum_crypto",
                "legal_framework",
                "containment_webhooks",
            ],
        }

    @app.get("/ready", tags=["ops"])
    def ready() -> dict[str, object]:
        status = {}

        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            status["postgres"] = "ok"
        except Exception as exc:
            status["postgres"] = f"error:{exc}"

        try:
            client = get_os_client()
            ok = client.ping()
            status["opensearch"] = "ok" if ok else "error:ping_failed"
        except Exception as exc:
            status["opensearch"] = f"error:{exc}"

        try:
            drv = get_driver()
            with drv.session() as sess:
                sess.run("RETURN 1").single()
            status["neo4j"] = "ok"
        except Exception as exc:
            status["neo4j"] = f"error:{exc}"

        overall = all(value == "ok" for value in status.values())
        return {"status": "ok" if overall else "degraded", "components": status}


async def _timing_middleware(request: Request, call_next):
    t0 = time.monotonic()
    response = await call_next(request)
    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
    return response


def create_application() -> FastAPI:
    tags_metadata = build_tags_metadata(ai_enabled=settings.ai_api_enabled)
    app = FastAPI(title="Sentinel-KE", openapi_tags=tags_metadata)

    app.add_middleware(BaseHTTPMiddleware, dispatch=_timing_middleware)
    app.add_middleware(SlowAPIMiddleware)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    install_http_hardening(app)
    install_error_handlers(app)

    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    _register_routers(app)
    _register_operational_routes(app)
    _register_lifecycle(app)
    return app


app = create_application()
