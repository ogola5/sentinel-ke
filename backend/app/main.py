import os
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import app.ledger.infra_clusters
import app.ledger.infra_evidence
from app.ledger.models import Base
import app.ledger.source
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


DATABASE_URL = os.getenv("DATABASE_URL")  # e.g. postgresql+psycopg2://user:pass@postgres:5432/sentinel
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

app = FastAPI(title="Sentinel-KE")
# Include routers
app.include_router(ingest_router)
app.include_router(events_router)
app.include_router(graph_router)
app.include_router(timeline_router)
app.include_router(campaigns_router)
app.include_router(infra_clusters_router)
app.include_router(ddos_router)
app.include_router(campaign_evidence_router)
app.include_router(cases_router)
app.include_router(stix_router)



@app.on_event("startup")
def startup():
    # MVP bootstrap: create tables automatically
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    # quick DB ping too, so judges see “real infra”
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}

@app.get("/debug/tables")
def debug_tables():
    # useful for verifying the schema is actually created
    q = """
    SELECT tablename
    FROM pg_catalog.pg_tables
    WHERE schemaname = 'public'
    ORDER BY tablename;
    """
    with engine.connect() as conn:
        rows = conn.execute(text(q)).fetchall()
    return {"tables": [r[0] for r in rows]}
