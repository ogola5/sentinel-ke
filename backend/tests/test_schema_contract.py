from __future__ import annotations

from sqlalchemy import create_engine

from app.core.schema_contract import apply_schema_contract, schema_contract_status


def test_schema_contract_noop_on_non_postgres_engine():
    engine = create_engine("sqlite:///:memory:")
    out = apply_schema_contract(engine)
    assert out["applied"] == 0
    assert out["skipped"] == 1

    status = schema_contract_status(engine)
    assert status["ok"] is True
    assert status["missing_count"] == 0
