from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts import run_paysim_gnn as paysim


class _FakeDB:
    def __init__(self, *, existing: int = 0):
        self.existing = existing
        self.rows = []
        self.commit_calls = 0
        self.deleted = 0

    def query(self, model):  # noqa: ANN001
        self.model = model
        return self

    def filter(self, *args, **kwargs):  # noqa: ANN002, ARG002
        return self

    def count(self):
        return self.existing

    def delete(self, synchronize_session=False):  # noqa: ANN001, ARG002
        deleted = self.existing
        self.deleted = deleted
        self.existing = 0
        return deleted

    def bulk_insert_mappings(self, model, rows):  # noqa: ANN001
        self.model = model
        self.rows.extend(rows)

    def commit(self):
        self.commit_calls += 1


def test_entity_key_maps_consumer_and_merchant_ids():
    assert paysim._entity_key("C123") == "account_h:C123"  # noqa: SLF001
    assert paysim._entity_key("M456") == "phone_h:M456"  # noqa: SLF001


def test_load_paysim_csv_aggregates_accounts(tmp_path: Path):
    csv_path = tmp_path / "paysim.csv"
    csv_path.write_text(
        "\n".join(
            [
                "step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,nameDest,oldbalanceDest,newbalanceDest,isFraud,isFlaggedFraud",
                "1,TRANSFER,7000,C100,10000,3000,M200,0,7000,1,0",
                "2,CASH_OUT,2000,C100,3000,1000,C300,0,2000,0,0",
                "3,PAYMENT,150,C999,1000,850,M888,0,150,0,0",
            ]
        ),
        encoding="utf-8",
    )

    accounts, labels = paysim.load_paysim_csv(csv_path, max_rows=10)

    assert accounts["account_h:C100"]["event_count"] == 2
    assert accounts["phone_h:M200"]["fraud_txn_count"] == 1
    assert labels["account_h:C100"] == 1
    assert "account_h:C999" not in accounts


def test_seed_snapshots_builds_expected_feature_rows():
    accounts = {
        "account_h:C100": {
            "event_count": 4,
            "degree": 4,
            "total_amount": 10000.0,
            "fraud_txn_count": 3,
            "chain_score": 0.75,
        }
    }
    labels = {"account_h:C100": 1}
    db = _FakeDB(existing=0)

    paysim.seed_snapshots(db, accounts, labels, window_key="Wpaysim-test")

    assert len(db.rows) == 1
    row = db.rows[0]
    assert row["entity_key"] == "account_h:C100"
    assert row["entity_type"] == "account_h"
    assert "CAMPAIGN_ENTITY" in row["risk_flags"]
    assert "AIRTIME_SIPHON_MEMBER" in row["risk_flags"]
    assert row["features"]["provenance_tag"] == "paysim"
    assert db.commit_calls == 1


def test_seed_snapshots_can_reset_existing_window():
    accounts = {
        "account_h:C100": {
            "event_count": 1,
            "degree": 1,
            "total_amount": 1000.0,
            "fraud_txn_count": 1,
            "chain_score": 1.0,
        }
    }
    labels = {"account_h:C100": 1}
    db = _FakeDB(existing=3)

    info = paysim.seed_snapshots(db, accounts, labels, window_key="Wpaysim-test", reset_window=True)

    assert info["removed"] == 3
    assert info["inserted"] == 1
    assert info["reset_performed"] is True
    assert db.deleted == 3


def test_run_training_returns_metrics(monkeypatch):
    monkeypatch.setattr(
        "app.analytics.layer3.gnn_backbone.load_dataset",
        lambda *args, **kwargs: SimpleNamespace(entity_keys=["a", "b", "c"], edges=[(0, 1, 1.0)]),
    )
    monkeypatch.setattr(
        "app.analytics.layer3.gnn_model.train_graphsage",
        lambda *args, **kwargs: SimpleNamespace(metrics={"auc": 0.97, "precision": 0.93}),
    )

    metrics = paysim.run_training(db=object(), window_key="Wpaysim-test")

    assert metrics["auc"] == 0.97
    assert metrics["precision"] == 0.93


def test_save_results_writes_metrics_record(tmp_path: Path):
    out_path = tmp_path / "paysim_auc.json"
    metrics = {"auc": 0.97, "precision": 0.93}

    paysim.save_results(metrics, out_path, run_config={"window_key": "Wpaysim", "reset_window": True})

    payload = out_path.read_text(encoding="utf-8")
    assert "PaySim" in payload
    assert '"auc": 0.97' in payload
    assert '"window_key": "Wpaysim"' in payload


def test_resolve_csv_path_accepts_file_and_directory(tmp_path: Path):
    csv_path = tmp_path / "PS_demo.csv"
    csv_path.write_text("header\n", encoding="utf-8")
    assert paysim.resolve_csv_path(str(csv_path)) == csv_path
    assert paysim.resolve_csv_path(str(tmp_path)) == csv_path
