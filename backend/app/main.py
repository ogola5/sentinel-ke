import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.ledger.models import Base

from app.api.error_contract import install_error_handlers
from app.api.router_registry import build_router_mounts, build_tags_metadata
from app.auth.service import AuthService
from app.core.config import settings
from app.core.http_hardening import install_http_hardening
from app.core.runtime_hardening import enforce_runtime_hardening
from app.search.opensearch import get_client as get_os_client
from app.graph.neo4j_driver import get_driver
from app.ledger.db import SessionLocal, engine
import app.db.registry  # noqa: F401  # ensure all models are registered

log = logging.getLogger("sentinel.main")


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

        _ensure_infra_cluster_schema()
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

        # Check whether a trained GNN artifact is available
        gnn_loaded = False
        gnn_model_version = None
        try:
            from app.analytics.ai_models import GNNTrainingRun  # noqa: PLC0415
            from pathlib import Path  # noqa: PLC0415
            db = SessionLocal()
            try:
                run = (
                    db.query(GNNTrainingRun)
                    .filter(GNNTrainingRun.artifact_path.isnot(None))
                    .order_by(GNNTrainingRun.created_at.desc())
                    .first()
                )
                if run and run.artifact_path and Path(str(run.artifact_path)).exists():
                    gnn_loaded = True
                    gnn_model_version = str(run.model_version)
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            pass  # table may not exist yet on first boot

        return {
            "status": "ok",
            "gnn_loaded": gnn_loaded,
            "gnn_model_version": gnn_model_version,
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


def create_application() -> FastAPI:
    tags_metadata = build_tags_metadata(ai_enabled=settings.ai_api_enabled)
    app = FastAPI(title="Sentinel-KE", openapi_tags=tags_metadata)

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
