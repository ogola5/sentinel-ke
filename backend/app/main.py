import os
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.ledger.models import Base

DATABASE_URL = os.getenv("DATABASE_URL")  # e.g. postgresql+psycopg2://user:pass@postgres:5432/sentinel
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

app = FastAPI(title="Sentinel-KE")

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
