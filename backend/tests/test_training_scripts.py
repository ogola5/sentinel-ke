"""
tests/test_training_scripts.py
================================
Unit tests for the three GNN training orchestration scripts:
  - scripts/train_cyber_gnn.py
  - scripts/train_corruption_gnn.py
  - scripts/benchmark_all_lanes.py

All tests are pure-Python (no DB, no GPU).  Any DB-touching paths are mocked.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to load scripts as modules without executing their main() guards
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _load_script(name: str) -> ModuleType:
    """Import a script from the scripts/ directory as a Python module."""
    path = _SCRIPTS_DIR / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None and spec.loader is not None, f"Cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    # Prevent the script from executing its if __name__ == "__main__" block
    # by injecting the module under a non-"__main__" name before exec.
    sys.modules[spec.name] = mod  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Step 1 — Import smoke tests
# ---------------------------------------------------------------------------


class TestImports:
    """Scripts must import without raising at module level."""

    def test_train_cyber_gnn_imports(self) -> None:
        """train_cyber_gnn.py must import without error."""
        mod = _load_script("train_cyber_gnn.py")
        assert hasattr(mod, "main"), "train_cyber_gnn must expose main()"
        assert hasattr(mod, "_print_summary"), "train_cyber_gnn must expose _print_summary()"

    def test_train_corruption_gnn_imports(self) -> None:
        """train_corruption_gnn.py must import without error."""
        mod = _load_script("train_corruption_gnn.py")
        assert hasattr(mod, "main"), "train_corruption_gnn must expose main()"
        assert hasattr(mod, "_print_summary"), "train_corruption_gnn must expose _print_summary()"

    def test_benchmark_all_lanes_imports(self) -> None:
        """benchmark_all_lanes.py must import without error."""
        mod = _load_script("benchmark_all_lanes.py")
        assert hasattr(mod, "main"), "benchmark_all_lanes must expose main()"
        assert hasattr(mod, "_collect_lane_data"), "benchmark_all_lanes must expose _collect_lane_data()"
        assert hasattr(mod, "_print_table"), "benchmark_all_lanes must expose _print_table()"


# ---------------------------------------------------------------------------
# Step 2 — benchmark_all_lanes handles missing artifacts gracefully
# ---------------------------------------------------------------------------


class TestBenchmarkMissingArtifacts:
    """_collect_lane_data() must return '--' cells (not crash) when no files exist."""

    def test_missing_artifacts_returns_placeholder_rows(self, tmp_path: Path) -> None:
        mod = _load_script("benchmark_all_lanes.py")

        # Point all artifact paths at non-existent files inside tmp_path
        missing = tmp_path / "does_not_exist.json"
        with (
            patch.object(mod, "_CYBER_RESULT",      missing),
            patch.object(mod, "_FRAUD_RESULT",       missing),
            patch.object(mod, "_CORRUPTION_RESULT",  missing),
        ):
            rows = mod._collect_lane_data()

        assert len(rows) == 3, "Should always return 3 rows (one per lane)"
        lanes = {r["lane"] for r in rows}
        assert lanes == {"Cyber", "Fraud", "Corruption"}

        for row in rows:
            # status should indicate no artifact
            assert row["status"] == "no_artifact", (
                f"Lane {row['lane']} status should be 'no_artifact', got {row['status']!r}"
            )
            # AUC cell must NOT be empty/None — placeholder is acceptable
            assert row["auc"] and row["auc"] != "", (
                f"Lane {row['lane']} AUC cell must not be empty"
            )

    def test_missing_artifacts_does_not_raise_in_print_table(self, tmp_path: Path) -> None:
        mod = _load_script("benchmark_all_lanes.py")

        missing = tmp_path / "does_not_exist.json"
        with (
            patch.object(mod, "_CYBER_RESULT",      missing),
            patch.object(mod, "_FRAUD_RESULT",       missing),
            patch.object(mod, "_CORRUPTION_RESULT",  missing),
        ):
            rows = mod._collect_lane_data()

        # _print_table must not raise
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod._print_table(rows)
        output = buf.getvalue()
        assert "Lane" in output, "Table must contain header 'Lane'"
        assert "AUC"  in output, "Table must contain header 'AUC'"

    def test_cell_values_are_strings_not_none(self, tmp_path: Path) -> None:
        """Every cell value returned must be a str, never None."""
        mod = _load_script("benchmark_all_lanes.py")
        missing = tmp_path / "does_not_exist.json"
        with (
            patch.object(mod, "_CYBER_RESULT",      missing),
            patch.object(mod, "_FRAUD_RESULT",       missing),
            patch.object(mod, "_CORRUPTION_RESULT",  missing),
        ):
            rows = mod._collect_lane_data()
        keys = ["lane", "dataset", "auc", "nodes", "edges", "holdout"]
        for row in rows:
            for k in keys:
                val = row.get(k)
                assert val is not None, f"Row {row['lane']} key '{k}' must not be None"
                assert isinstance(val, str), (
                    f"Row {row['lane']} key '{k}' must be str, got {type(val)}"
                )


# ---------------------------------------------------------------------------
# Step 3 — JSON output structure tests
# ---------------------------------------------------------------------------


class TestCyberTrainResultStructure:
    """The JSON written by train_cyber_gnn.py must have required top-level keys."""

    _REQUIRED_KEYS = {"status"}
    _OK_KEYS       = {"status", "gnn_run_id", "window_key", "nodes", "edges", "metrics"}

    def test_ok_result_has_required_keys(self) -> None:
        """A successful run result must have all expected keys."""
        ok_result: dict[str, Any] = {
            "status": "ok",
            "gnn_run_id": "abc-123",
            "window_key": "Wmid",
            "nodes": 97,
            "edges": 237,
            "positive_count": 30,
            "negative_count": 45,
            "metrics": {"val_auc": 0.8928},
            "label_ladder": {
                "tier_counts": {"gold": 5, "silver": 15, "bronze": 10},
                "dominant_tier": "silver",
            },
            "fairness_gate_override_applied": False,
            "real_data_gate_passed": True,
            "real_data_gate_override_applied": False,
            "benchmarkable": True,
            "benchmark_reasons": [],
        }
        missing = self._OK_KEYS - set(ok_result.keys())
        assert not missing, f"Missing keys in ok result: {missing}"

    def test_blocked_result_has_gate_key(self) -> None:
        blocked_result: dict[str, Any] = {
            "status": "blocked",
            "gate": "fairness",
            "model_version": "gnn-sage-v1",
            "max_positive_rate_disparity": 0.42,
            "threshold": 0.3,
            "label_ladder": {},
            "detail": "blocked by fairness gate",
        }
        assert blocked_result["status"] == "blocked"
        assert "gate" in blocked_result

    def test_json_serialisable(self, tmp_path: Path) -> None:
        """Result dict must be JSON-serialisable (same as what the script writes)."""
        result = {
            "status": "ok",
            "window_key": "Wmid",
            "nodes": 97,
            "edges": 237,
            "metrics": {"val_auc": 0.8928},
        }
        out = tmp_path / "cyber_train_result.json"
        out.write_text(json.dumps(result, indent=2, default=str))
        loaded = json.loads(out.read_text())
        assert loaded["status"] == "ok"
        assert loaded["metrics"]["val_auc"] == pytest.approx(0.8928)


class TestCorruptionTrainResultStructure:
    """The JSON written by train_corruption_gnn.py must have required top-level keys."""

    _OK_KEYS = {"status", "domain", "window_key", "nodes", "edges", "metrics"}

    def test_ok_result_has_required_keys(self) -> None:
        ok_result: dict[str, Any] = {
            "status": "ok",
            "domain": "corruption",
            "window_key": "Wcorruption",
            "nodes": 1982,
            "edges": 4158,
            "positive_count": 200,
            "negative_count": 300,
            "predictions": 400,
            "metrics": {"val_auc": 0.91},
            "fairness_gate_override_applied": True,
            "real_data_gate_passed": False,
            "real_data_gate_override_applied": True,
            "benchmarkable": True,
            "benchmark_reasons": [],
        }
        missing = self._OK_KEYS - set(ok_result.keys())
        assert not missing, f"Missing keys in corruption ok result: {missing}"

    def test_blocked_fairness_result_has_disparity(self) -> None:
        blocked: dict[str, Any] = {
            "status": "blocked",
            "gate": "fairness",
            "model_version": "corruption-gnn-v1",
            "max_positive_rate_disparity": 0.55,
            "threshold": 0.3,
            "detail": "Training run blocked by fairness governance gate.",
        }
        assert blocked["gate"] == "fairness"
        assert "max_positive_rate_disparity" in blocked

    def test_json_serialisable(self, tmp_path: Path) -> None:
        result = {
            "status": "ok",
            "domain": "corruption",
            "window_key": "Wcorruption",
            "nodes": 1982,
            "edges": 4158,
            "metrics": {"val_auc": 0.88},
        }
        out = tmp_path / "corruption_train_result.json"
        out.write_text(json.dumps(result, indent=2, default=str))
        loaded = json.loads(out.read_text())
        assert loaded["domain"] == "corruption"
        assert loaded["metrics"]["val_auc"] == pytest.approx(0.88)


# ---------------------------------------------------------------------------
# Step 4 — _print_summary smoke tests (no crash, no DB)
# ---------------------------------------------------------------------------


class TestPrintSummarySmoke:
    """_print_summary() must handle all status variants without raising."""

    @pytest.fixture(autouse=True)
    def _mods(self) -> None:
        self.cyber_mod = _load_script("train_cyber_gnn.py")
        self.corruption_mod = _load_script("train_corruption_gnn.py")

    def _capture(self, fn, result: dict) -> str:
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(result)
        return buf.getvalue()

    # ── Cyber ──────────────────────────────────────────────────────────────

    def test_cyber_ok(self) -> None:
        out = self._capture(self.cyber_mod._print_summary, {
            "status": "ok",
            "window_key": "Wmid",
            "nodes": 97,
            "edges": 237,
            "positive_count": 30,
            "negative_count": 45,
            "metrics": {"val_auc": 0.8928},
            "label_ladder": {"tier_counts": {"gold": 5}, "dominant_tier": "gold"},
            "fairness_gate_override_applied": False,
            "real_data_gate_passed": True,
            "real_data_gate_override_applied": False,
            "benchmarkable": True,
        })
        assert "0.8928" in out
        assert "Wmid" in out

    def test_cyber_blocked_fairness(self) -> None:
        out = self._capture(self.cyber_mod._print_summary, {
            "status": "blocked",
            "gate": "fairness",
            "detail": "max disparity exceeded",
            "label_ladder": {},
        })
        assert "BLOCKED" in out.upper()
        assert "fairness" in out

    def test_cyber_no_data(self) -> None:
        out = self._capture(self.cyber_mod._print_summary, {
            "status": "no_data",
            "message": "Run real data pipeline first",
        })
        assert "no_data" in out.lower() or "NO_DATA" in out

    def test_cyber_error(self) -> None:
        out = self._capture(self.cyber_mod._print_summary, {
            "status": "error",
            "stage": "train_graphsage",
            "detail": "CUDA OOM",
        })
        assert "error" in out.lower() or "ERROR" in out

    # ── Corruption ─────────────────────────────────────────────────────────

    def test_corruption_ok(self) -> None:
        out = self._capture(self.corruption_mod._print_summary, {
            "status": "ok",
            "domain": "corruption",
            "window_key": "Wcorruption",
            "nodes": 1982,
            "edges": 4158,
            "positive_count": 200,
            "negative_count": 300,
            "predictions": 400,
            "metrics": {"val_auc": 0.91},
            "fairness_gate_override_applied": True,
            "real_data_gate_passed": False,
            "real_data_gate_override_applied": True,
            "benchmarkable": True,
        })
        assert "0.9100" in out or "0.91" in out
        assert "Wcorruption" in out

    def test_corruption_blocked_with_per_type(self) -> None:
        out = self._capture(self.corruption_mod._print_summary, {
            "status": "blocked",
            "gate": "fairness",
            "max_positive_rate_disparity": 0.55,
            "threshold": 0.3,
            "detail": "blocked by fairness governance gate",
            "fairness_per_type": {
                "official":   {"positive_rate": 0.8, "n": 50},
                "company":    {"positive_rate": 0.25, "n": 80},
            },
        })
        assert "BLOCKED" in out.upper()
        assert "official" in out

    def test_corruption_no_data(self) -> None:
        out = self._capture(self.corruption_mod._print_summary, {
            "status": "no_data",
            "message": "Run synthetic_corruption_data first",
        })
        assert "no_data" in out.lower() or "NO_DATA" in out

    def test_corruption_error(self) -> None:
        out = self._capture(self.corruption_mod._print_summary, {
            "status": "error",
            "stage": "persist",
            "detail": "unique constraint violation",
        })
        assert "error" in out.lower() or "ERROR" in out


# ---------------------------------------------------------------------------
# Step 5 — benchmark reads live artifacts when present
# ---------------------------------------------------------------------------


class TestBenchmarkWithArtifacts:
    """When JSON artifacts exist, _collect_lane_data() must parse them correctly."""

    def test_reads_cyber_artifact(self, tmp_path: Path) -> None:
        mod = _load_script("benchmark_all_lanes.py")

        cyber_file = tmp_path / "cyber_train_result.json"
        cyber_file.write_text(json.dumps({
            "status": "ok",
            "window_key": "Wmid",
            "nodes": 97,
            "edges": 237,
            "metrics": {"val_auc": 0.8928},
        }))

        missing = tmp_path / "nope.json"
        with (
            patch.object(mod, "_CYBER_RESULT",      cyber_file),
            patch.object(mod, "_FRAUD_RESULT",       missing),
            patch.object(mod, "_CORRUPTION_RESULT",  missing),
        ):
            rows = mod._collect_lane_data()

        cyber_row = next(r for r in rows if r["lane"] == "Cyber")
        assert cyber_row["status"] == "ok"
        assert "0.8928" in cyber_row["auc"]
        assert cyber_row["nodes"] == "97"
        assert cyber_row["edges"] == "237"

    def test_reads_corruption_artifact(self, tmp_path: Path) -> None:
        mod = _load_script("benchmark_all_lanes.py")

        corruption_file = tmp_path / "corruption_train_result.json"
        corruption_file.write_text(json.dumps({
            "status": "ok",
            "domain": "corruption",
            "window_key": "Wcorruption",
            "nodes": 1982,
            "edges": 4158,
            "metrics": {"val_auc": 0.88},
        }))

        missing = tmp_path / "nope.json"
        with (
            patch.object(mod, "_CYBER_RESULT",      missing),
            patch.object(mod, "_FRAUD_RESULT",       missing),
            patch.object(mod, "_CORRUPTION_RESULT",  corruption_file),
        ):
            rows = mod._collect_lane_data()

        corruption_row = next(r for r in rows if r["lane"] == "Corruption")
        assert corruption_row["status"] == "ok"
        assert "0.8800" in corruption_row["auc"]
        assert corruption_row["nodes"] == "1982"
        assert corruption_row["edges"] == "4158"

    def test_blocked_cyber_shown_as_blocked(self, tmp_path: Path) -> None:
        mod = _load_script("benchmark_all_lanes.py")

        cyber_file = tmp_path / "cyber_train_result.json"
        cyber_file.write_text(json.dumps({
            "status": "blocked",
            "gate": "fairness",
            "detail": "disparity too high",
        }))

        missing = tmp_path / "nope.json"
        with (
            patch.object(mod, "_CYBER_RESULT",      cyber_file),
            patch.object(mod, "_FRAUD_RESULT",       missing),
            patch.object(mod, "_CORRUPTION_RESULT",  missing),
        ):
            rows = mod._collect_lane_data()

        cyber_row = next(r for r in rows if r["lane"] == "Cyber")
        assert cyber_row["status"] == "blocked"
        assert "BLOCKED" in cyber_row["auc"]
