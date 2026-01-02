import os
from fastapi import FastAPI, Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.ledger.models import Base

from app.ingestion.router import router as ingest_router
from app.api.events import router as events_router
from app.api.graph import router as graph_router
from app.api.timeline import router as timeline_router
from app.api.campaigns import router as campaigns_router
from app.api.infra_clusters import router as infra_clusters_router
from app.api.ddos import router as ddos_router
from app.api.campaign_evidence import router as campaign_evidence_router
from app.cases.api import router as cases_router
from app.api.stix import router as stix_router
from app.api.infra_graph import router as infra_graph_router
from app.api.anomalies import router as anomalies_router
from app.api.mitigations import router as mitigations_router
from app.api.metrics import router as metrics_router
from app.api.ai import router as ai_router
from app.api.deps import require_api_key
from app.search.opensearch import get_client as get_os_client
from app.graph.neo4j_driver import get_driver
import app.db.registry  # noqa: F401  # ensure all models are registered

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

tags_metadata = [
    {"name": "ingest", "description": "Evidence-grade ingestion"},
    {"name": "events", "description": "Event search and timeline"},
    {"name": "campaigns", "description": "Campaigns and risk"},
    {"name": "infra-clusters", "description": "Infrastructure clusters and graph"},
    {"name": "ddos", "description": "DDoS indicators and alerts"},
    {"name": "anomalies", "description": "Anomaly scores"},
    {"name": "mitigations", "description": "IOC and mitigation bundles"},
    {"name": "ai", "description": "AI predictions and explanations"},
    {"name": "metrics", "description": "Operational metrics"},
]

app = FastAPI(title="Sentinel-KE", openapi_tags=tags_metadata)

app.include_router(ingest_router, dependencies=[Depends(require_api_key)])
app.include_router(events_router, dependencies=[Depends(require_api_key)])
app.include_router(graph_router, dependencies=[Depends(require_api_key)])
app.include_router(timeline_router, dependencies=[Depends(require_api_key)])
app.include_router(campaigns_router, dependencies=[Depends(require_api_key)])
app.include_router(infra_clusters_router, dependencies=[Depends(require_api_key)])
app.include_router(ddos_router, dependencies=[Depends(require_api_key)])
app.include_router(campaign_evidence_router, dependencies=[Depends(require_api_key)])
app.include_router(cases_router, dependencies=[Depends(require_api_key)])
app.include_router(stix_router, dependencies=[Depends(require_api_key)])
app.include_router(infra_graph_router, dependencies=[Depends(require_api_key)])
app.include_router(anomalies_router, dependencies=[Depends(require_api_key)])
app.include_router(mitigations_router, dependencies=[Depends(require_api_key)])
app.include_router(metrics_router, dependencies=[Depends(require_api_key)])
app.include_router(ai_router, dependencies=[Depends(require_api_key)])

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/ready")
def ready():
    status = {}
    # Postgres
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["postgres"] = "ok"
    except Exception as e:
        status["postgres"] = f"error:{e}"

    # OpenSearch
    try:
        client = get_os_client()
        ok = client.ping()
        status["opensearch"] = "ok" if ok else "error:ping_failed"
    except Exception as e:
        status["opensearch"] = f"error:{e}"

    # Neo4j
    try:
        drv = get_driver()
        with drv.session() as sess:
            sess.run("RETURN 1").single()
        status["neo4j"] = "ok"
    except Exception as e:
        status["neo4j"] = f"error:{e}"

    overall = all(v == "ok" for v in status.values())
    return {"status": "ok" if overall else "degraded", "components": status}
