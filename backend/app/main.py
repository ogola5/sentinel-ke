import logging
import os
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from sqlalchemy import text

from app.ledger.models import Base

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.error_contract import install_error_handlers
from app.api.router_registry import build_router_mounts, build_tags_metadata
from app.auth.service import AuthService
from app.core.config import settings
from app.core.schema_contract import apply_schema_contract, schema_contract_status
from app.core.http_hardening import install_http_hardening
from app.core import metrics_store
from app.core.prometheus_metrics import prometheus_payload, record_http_request
from app.core.rate_limit import limiter
from app.core.runtime_hardening import enforce_runtime_hardening
from app.search.opensearch import get_client as get_os_client, is_opensearch_enabled
from app.graph.neo4j_driver import get_driver, is_neo4j_enabled
from app.ledger.db import SessionLocal, engine
import app.db.registry  # noqa: F401  # ensure all models are registered

log = logging.getLogger("sentinel.main")


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

        patch_out = apply_schema_contract(engine)
        log.info("schema_contract_applied=%s", patch_out)
        schema_status = schema_contract_status(engine)
        if not bool(schema_status.get("ok")):
            raise RuntimeError(
                f"schema_contract_incomplete missing={schema_status.get('missing', {})}"
            )
        try:
            db = SessionLocal()
            try:
                out = AuthService(db).bootstrap_defaults()
                log.info("auth_bootstrap=%s", out)
            finally:
                db.close()
        except Exception:
            log.exception("auth_bootstrap_failed")

        try:
            from app.ledger.seed_sources import seed as _seed_sources  # noqa: PLC0415
            _seed_sources()
            log.info("source_registry_seeded")
        except Exception:
            log.exception("source_registry_seed_failed")


def _register_operational_routes(app: FastAPI) -> None:
    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    def prometheus_metrics() -> Response:
        payload, content_type = prometheus_payload()
        return Response(content=payload, media_type=content_type)

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
                    metrics_json = dict(run.metrics_json or {})
                    real_data_gate = dict(metrics_json.get("real_data_gate") or {})
                    provenance = dict(metrics_json.get("provenance") or {})
                    gnn_model_version = str(run.model_version)
                    gnn_metrics = {
                        "auc":            round(float(run.auc), 4)       if run.auc       is not None else None,
                        "precision":      round(float(run.precision), 4) if run.precision is not None else None,
                        "node_count":     run.node_count,
                        "edge_count":     run.edge_count,
                        "positive_count": run.positive_count,
                        "feature_dim":    run.feature_dim,
                        "prediction_type": run.prediction_type,
                        "real_data_gate_passed": bool(real_data_gate.get("passed", False)),
                        "real_ratio": float(provenance.get("real_ratio") or 0.0),
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

        schema_status = schema_contract_status(engine)
        minio_mode = os.getenv("MINIO_ANCHOR_MODE", "disabled").strip().lower() or "disabled"
        immudb_mode = os.getenv("IMMUDB_ANCHOR_MODE", "disabled").strip().lower() or "disabled"
        anchor_modes = {minio_mode, immudb_mode}
        if anchor_modes <= {"disabled"}:
            legal_anchor_integrity = "disabled"
        elif "stub" in anchor_modes:
            legal_anchor_integrity = "simulated"
        elif "disabled" in anchor_modes:
            legal_anchor_integrity = "partial"
        else:
            legal_anchor_integrity = "live"

        return {
            "status":               "ok",
            "uptime_seconds":       metrics_store.snapshot()["uptime_seconds"],
            "gnn_loaded":           gnn_loaded,
            "gnn_model_version":    gnn_model_version,
            "gnn_metrics":          gnn_metrics,
            "federation_partners":  federation_partners,
            "schema_contract_ok":   bool(schema_status.get("ok")),
            "schema_missing_count": int(schema_status.get("missing_count") or 0),
            "schema_missing":       schema_status.get("missing", {}),
            "federation_signed_requests_required": bool(settings.federation_require_signed_requests),
            "legal_anchor_modes": {
                "minio": minio_mode,
                "immudb": immudb_mode,
            },
            "legal_anchor_integrity": legal_anchor_integrity,
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

        if is_opensearch_enabled():
            try:
                client = get_os_client()
                ok = client.ping()
                status["opensearch"] = "ok" if ok else "error:ping_failed"
            except Exception as exc:
                status["opensearch"] = f"error:{exc}"
        else:
            status["opensearch"] = "disabled"

        if is_neo4j_enabled():
            try:
                drv = get_driver()
                with drv.session() as sess:
                    sess.run("RETURN 1").single()
                status["neo4j"] = "ok"
            except Exception as exc:
                status["neo4j"] = f"error:{exc}"
        else:
            status["neo4j"] = "disabled"

        overall = all(value in {"ok", "disabled"} for value in status.values())
        return {"status": "ok" if overall else "degraded", "components": status}


async def _timing_middleware(request: Request, call_next):
    t0 = time.monotonic()
    is_error = False
    response = None
    try:
        response = await call_next(request)
        if response.status_code >= 500:
            is_error = True
    except Exception:
        is_error = True
        raise
    finally:
        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
        metrics_store.record(elapsed_ms, is_error=is_error)
        status_code = int(response.status_code) if response is not None else 500
        record_http_request(
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=elapsed_ms,
        )
        if response is not None:
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
