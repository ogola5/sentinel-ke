"""Unit tests for the four new real-data ingesters.

All DB calls are mocked via a lightweight stub session — no live Postgres
connection is required.  These run as pure unit tests (no integration mark).
"""
from __future__ import annotations

import csv
import os
import tempfile
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

import app.analytics.layer3.ddos_benchmark_ingest as _ddos_mod
import app.analytics.layer3.malwarebazaar_ingest as _mb_mod
import app.analytics.layer3.threatfox_ingest as _tf_mod
import app.analytics.layer3.vpn_benchmark_ingest as _vpn_mod
from app.analytics.layer3.ddos_benchmark_ingest import (
    aggregate_rows as ddos_aggregate,
    run_ingest as ddos_run_ingest,
)
from app.analytics.layer3.malwarebazaar_ingest import run_ingest as mb_run_ingest
from app.analytics.layer3.threatfox_ingest import run_ingest as tf_run_ingest
from app.analytics.layer3.vpn_benchmark_ingest import (
    aggregate_rows as vpn_aggregate,
    run_ingest as vpn_run_ingest,
)
from app.integrations.real_data_pipeline import run_threat_intel_pipeline


# ---------------------------------------------------------------------------
# Shared DB stub
# ---------------------------------------------------------------------------


class _StubDB:
    """Minimal SQLAlchemy session stub that records executed statements."""

    def __init__(self) -> None:
        """Initialise counters."""
        self.executed: List[Any] = []
        self.committed = False

    def execute(self, stmt: Any) -> Any:
        """Record the statement and return a dummy result."""
        self.executed.append(stmt)
        return type("R", (), {"rowcount": 1})()

    def flush(self) -> None:
        """No-op flush."""

    def commit(self) -> None:
        """Mark session as committed."""
        self.committed = True

    def close(self) -> None:
        """No-op close."""


class _ExcludedProxy:
    """Proxy for ``stmt.excluded.col_name`` used in on_conflict_do_update set_ dicts."""

    def __getattr__(self, name: str) -> str:  # noqa: ANN001
        # Return a harmless sentinel string — the value is never evaluated in tests.
        return f"excluded.{name}"


class _StubClause:
    """Minimal stand-in for a pg_insert().values(...) return value."""

    excluded = _ExcludedProxy()

    def on_conflict_do_nothing(self, **_kw: Any) -> "_StubClause":
        """Return self to allow chaining."""
        return self

    def on_conflict_do_update(self, **_kw: Any) -> "_StubClause":
        """Return self to allow chaining."""
        return self


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------

_TF_INFRA = [
    patch(f"{_tf_mod.__name__}.Base.metadata.create_all"),
    patch(f"{_tf_mod.__name__}._ensure_source"),
]
_MB_INFRA = [
    patch(f"{_mb_mod.__name__}.Base.metadata.create_all"),
    patch(f"{_mb_mod.__name__}._ensure_source"),
]
_DDOS_INFRA = [
    patch(f"{_ddos_mod.__name__}.Base.metadata.create_all"),
]
_VPN_INFRA = [
    patch(f"{_vpn_mod.__name__}.Base.metadata.create_all"),
]


def _start(patches: List[Any]) -> None:
    """Start a list of patch objects."""
    for p in patches:
        p.start()


def _stop(patches: List[Any]) -> None:
    """Stop a list of patch objects."""
    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def _write_csv(headers: List[str], rows: List[List[str]]) -> str:
    """Write a CSV to a temp file and return the file path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    )
    writer = csv.writer(f)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# Capture helper: intercept pg_insert calls for graph_feature_snapshot
# ---------------------------------------------------------------------------


def _make_snapshot_capturer(target_module: Any) -> tuple:
    """Return (captured_rows list, pg_insert side-effect function).

    The side-effect replaces pg_insert in *target_module* and records
    every dict passed as a row destined for graph_feature_snapshot.
    """
    captured: List[Dict[str, Any]] = []

    def _fake_pg_insert(model: Any) -> Any:
        class _Clause:
            def values(self, rows: Any = None, **kwargs: Any) -> _StubClause:  # noqa: ANN001
                """Capture snapshot rows — supports both .values([...]) and .values(**row)."""
                tname = getattr(model, "__tablename__", "")
                if tname == "graph_feature_snapshot":
                    if rows is None:
                        # called as .values(col=val, ...) — single row as kwargs
                        captured.append(dict(kwargs))
                    else:
                        batch = rows if isinstance(rows, list) else [rows]
                        captured.extend(batch)
                return _StubClause()

            def on_conflict_do_nothing(self, **_kw: Any) -> _StubClause:
                return _StubClause()

            def on_conflict_do_update(self, **_kw: Any) -> _StubClause:
                return _StubClause()

        return _Clause()

    return captured, patch(f"{target_module.__name__}.pg_insert", side_effect=_fake_pg_insert)


def _make_eventlog_capturer(target_module: Any) -> tuple:
    """Return (captured_payloads list, pg_insert side-effect function)."""
    captured: List[Dict[str, Any]] = []

    def _fake_pg_insert(model: Any) -> Any:
        class _Clause:
            def values(self, rows: Any = None, **kwargs: Any) -> _StubClause:  # noqa: ANN001
                """Capture event_log payload_json — supports both call forms."""
                tname = getattr(model, "__tablename__", "")
                if tname == "event_log":
                    if rows is None:
                        captured.append(kwargs.get("payload_json", {}))
                    else:
                        batch = rows if isinstance(rows, list) else [rows]
                        for row in batch:
                            captured.append(row.get("payload_json", {}))
                return _StubClause()

            def on_conflict_do_nothing(self, **_kw: Any) -> _StubClause:
                return _StubClause()

            def on_conflict_do_update(self, **_kw: Any) -> _StubClause:
                return _StubClause()

        return _Clause()

    return captured, patch(f"{target_module.__name__}.pg_insert", side_effect=_fake_pg_insert)


# ===========================================================================
# Task 3 — threatfox_ingest
# ===========================================================================


class TestThreatfoxIngest:
    """Unit tests for app.analytics.layer3.threatfox_ingest."""

    def _run(self, iocs: List[Dict[str, Any]]) -> tuple:
        """Run tf_run_ingest with patched DB infra; return (result, db)."""
        db = _StubDB()
        _start(_TF_INFRA)
        try:
            result = tf_run_ingest(db, iocs=iocs)
        finally:
            _stop(_TF_INFRA)
        return result, db

    def test_ip_port_ioc_maps_to_ip_entity(self) -> None:
        """ip:port IOC type produces one event and one snapshot."""
        iocs = [{
            "ioc_type": "ip:port",
            "ioc": "192.168.1.10:4444",
            "malware": "Cobalt Strike",
            "first_seen": "2026-03-01T00:00:00Z",
        }]
        result, db = self._run(iocs)
        assert result["status"] == "ok"
        assert result["events"] == 1
        assert result["snapshots"] == 1
        assert db.committed

    def test_domain_ioc_maps_to_domain_entity(self) -> None:
        """domain IOC type is accepted and produces exactly one entity."""
        iocs = [{
            "ioc_type": "domain",
            "ioc": "evil.example.com",
            "malware": "AsyncRAT",
            "first_seen": "2026-03-01T00:00:00Z",
        }]
        result, _ = self._run(iocs)
        assert result["status"] == "ok"
        assert result["events"] == 1
        assert result["snapshots"] == 1

    def test_url_ioc_maps_to_url_entity(self) -> None:
        """url IOC type creates a url entity key."""
        iocs = [{
            "ioc_type": "url",
            "ioc": "http://bad.example.com/payload.exe",
            "malware": "Emotet",
            "first_seen": "2026-03-01T00:00:00Z",
        }]
        result, _ = self._run(iocs)
        assert result["status"] == "ok"
        assert result["events"] == 1
        assert result["entities"] == 1

    def test_multiple_iocs_same_ip_aggregated(self) -> None:
        """Two ip:port IOCs sharing the same IP collapse to one entity."""
        iocs = [
            {
                "ioc_type": "ip:port",
                "ioc": "10.0.0.1:443",
                "first_seen": "2026-03-01T00:00:00Z",
            },
            {
                "ioc_type": "ip:port",
                "ioc": "10.0.0.1:80",
                "first_seen": "2026-03-02T00:00:00Z",
            },
        ]
        result, _ = self._run(iocs)
        assert result["events"] == 2
        assert result["entities"] == 1
        assert result["snapshots"] == 1

    def test_empty_iocs_returns_no_data(self) -> None:
        """Empty input returns no_data status without touching the DB."""
        result, _ = self._run([])
        assert result["status"] == "no_data"
        assert result["events"] == 0

    def test_rows_missing_ioc_field_skipped(self) -> None:
        """Rows without an ioc value are silently skipped."""
        iocs = [
            {"ioc_type": "domain"},
            {
                "ioc": "ok.example.com",
                "ioc_type": "domain",
                "first_seen": "2026-03-01T00:00:00Z",
            },
        ]
        result, _ = self._run(iocs)
        assert result["events"] == 1

    def test_risk_flags_always_contain_required_values(self) -> None:
        """Snapshots must carry THREAT_INTEL_HIT and MALWARE_INDICATOR."""
        captured, cap_patch = _make_snapshot_capturer(_tf_mod)
        _start(_TF_INFRA)
        with cap_patch:
            db = _StubDB()
            tf_run_ingest(
                db,
                iocs=[{
                    "ioc_type": "domain",
                    "ioc": "test.bad",
                    "first_seen": "2026-03-01T00:00:00Z",
                }],
            )
        _stop(_TF_INFRA)
        assert len(captured) == 1
        assert "THREAT_INTEL_HIT" in captured[0]["risk_flags"]
        assert "MALWARE_INDICATOR" in captured[0]["risk_flags"]

    def test_fetch_error_returns_error_status(self) -> None:
        """A network error during fetch returns status=fetch_error."""
        def _bad_poster(*_a: Any, **_kw: Any) -> None:
            raise ConnectionError("network down")

        _start(_TF_INFRA)
        try:
            result = tf_run_ingest(_StubDB(), poster=_bad_poster)
        finally:
            _stop(_TF_INFRA)
        assert result["status"] == "fetch_error"
        assert "network down" in result["error"]

    def test_max_records_cap_limits_events(self) -> None:
        """max_records=3 processes only the first 3 IOCs."""
        iocs = [
            {
                "ioc_type": "domain",
                "ioc": f"host{i}.bad",
                "first_seen": "2026-03-01T00:00:00Z",
            }
            for i in range(10)
        ]
        _start(_TF_INFRA)
        try:
            result = tf_run_ingest(_StubDB(), iocs=iocs, max_records=3)
        finally:
            _stop(_TF_INFRA)
        assert result["events"] == 3


# ===========================================================================
# Task 4 — malwarebazaar_ingest
# ===========================================================================


class TestMalwarebazaarIngest:
    """Unit tests for app.analytics.layer3.malwarebazaar_ingest."""

    def _run(self, samples: List[Dict[str, Any]]) -> tuple:
        """Run mb_run_ingest with patched DB infra; return (result, db)."""
        db = _StubDB()
        _start(_MB_INFRA)
        try:
            result = mb_run_ingest(db, samples=samples)
        finally:
            _stop(_MB_INFRA)
        return result, db

    def test_delivery_url_maps_to_domain_entity(self) -> None:
        """A sample with a delivery URL creates a domain entity."""
        samples = [{
            "sha256_hash": "a" * 64,
            "delivery_url": "http://malware-drop.example.com/evil.exe",
            "signature": "AgentTesla",
            "tags": ["stealer", "agent-tesla"],
            "first_seen": "2026-03-01 12:00:00",
        }]
        result, _ = self._run(samples)
        assert result["status"] == "ok"
        assert result["events"] == 1
        assert result["snapshots"] == 1

    def test_risk_flags_contain_required_values(self) -> None:
        """Snapshots must carry MALWARE_INDICATOR and CAMPAIGN_ENTITY."""
        captured, cap_patch = _make_snapshot_capturer(_mb_mod)
        _start(_MB_INFRA)
        with cap_patch:
            db = _StubDB()
            mb_run_ingest(
                db,
                samples=[{
                    "sha256_hash": "b" * 64,
                    "delivery_url": "http://drop.example.org/x.dll",
                    "signature": "Ryuk",
                    "tags": ["ransomware"],
                    "first_seen": "2026-03-01 00:00:00",
                }],
            )
        _stop(_MB_INFRA)
        assert len(captured) == 1
        assert "MALWARE_INDICATOR" in captured[0]["risk_flags"]
        assert "CAMPAIGN_ENTITY" in captured[0]["risk_flags"]

    def test_fraud_family_from_first_tag(self) -> None:
        """fraud_family in the event payload equals tags[0]."""
        captured, cap_patch = _make_eventlog_capturer(_mb_mod)
        _start(_MB_INFRA)
        with cap_patch:
            db = _StubDB()
            mb_run_ingest(
                db,
                samples=[{
                    "sha256_hash": "c" * 64,
                    "delivery_url": "http://c2.example.net/bin",
                    "tags": ["formbook", "stealer"],
                    "first_seen": "2026-03-01 00:00:00",
                }],
            )
        _stop(_MB_INFRA)
        assert len(captured) == 1
        assert captured[0]["fraud_family"] == "formbook"

    def test_sample_without_url_uses_hash_entity(self) -> None:
        """A sample with no delivery URL falls back to a hash-based entity."""
        samples = [{
            "sha256_hash": "d" * 64,
            "signature": "Mirai",
            "tags": [],
            "first_seen": "2026-03-01 00:00:00",
        }]
        result, _ = self._run(samples)
        assert result["events"] == 1
        assert result["entities"] == 1

    def test_empty_samples_returns_no_data(self) -> None:
        """Empty input short-circuits to no_data status."""
        result, _ = self._run([])
        assert result["status"] == "no_data"

    def test_samples_missing_sha256_skipped(self) -> None:
        """Rows without a sha256_hash value are silently skipped."""
        samples = [
            {"delivery_url": "http://x.com/a.exe"},
            {
                "sha256_hash": "e" * 64,
                "delivery_url": "http://x.com/b.exe",
                "first_seen": "2026-03-01 00:00:00",
            },
        ]
        result, _ = self._run(samples)
        assert result["events"] == 1


# ===========================================================================
# Task 5 — ddos_benchmark_ingest
# ===========================================================================


class TestDdosBenchmarkIngest:
    """Unit tests for app.analytics.layer3.ddos_benchmark_ingest."""

    def _run(self, path: str, fmt: str | None = None) -> tuple:
        """Run ddos_run_ingest with patched DB infra; return (result, db)."""
        db = _StubDB()
        _start(_DDOS_INFRA)
        try:
            result = ddos_run_ingest(db, csv_path=path, fmt=fmt)
        finally:
            _stop(_DDOS_INFRA)
        return result, db

    def test_cic_format_detected_from_headers(self) -> None:
        """CIC-DDoS2019 format is auto-detected from column names."""
        path = _write_csv(
            [
                "Source IP",
                "Destination IP",
                "Label",
                "Total Length of Fwd Packets",
                "Total Length of Bwd Packets",
            ],
            [
                ["10.0.0.1", "192.168.1.1", "DDoS", "1000", "500"],
                ["10.0.0.2", "192.168.1.2", "BENIGN", "200", "100"],
            ],
        )
        try:
            result, _ = self._run(path)
            assert result["status"] == "ok"
            assert result["format"] == "cic_ddos2019"
            assert result["total_source_ips"] == 2
            assert result["snapshots"] == 2
        finally:
            os.unlink(path)

    def test_cic_attack_row_gets_ddos_alert_service_flag(self) -> None:
        """A CIC attack flow produces the DDOS_ALERT_SERVICE risk flag."""
        captured, cap_patch = _make_snapshot_capturer(_ddos_mod)
        path = _write_csv(
            ["Source IP", "Destination IP", "Label"],
            [["1.2.3.4", "5.6.7.8", "UDP Flood"]],
        )
        try:
            _start(_DDOS_INFRA)
            with cap_patch:
                ddos_run_ingest(_StubDB(), csv_path=path)
            _stop(_DDOS_INFRA)
        finally:
            os.unlink(path)
        assert len(captured) == 1
        assert "DDOS_ALERT_SERVICE" in captured[0]["risk_flags"]

    def test_cic_benign_row_has_no_ddos_flag(self) -> None:
        """A CIC BENIGN flow produces an empty risk_flags list."""
        captured, cap_patch = _make_snapshot_capturer(_ddos_mod)
        path = _write_csv(
            ["Source IP", "Destination IP", "Label"],
            [["9.9.9.9", "1.1.1.1", "BENIGN"]],
        )
        try:
            _start(_DDOS_INFRA)
            with cap_patch:
                ddos_run_ingest(_StubDB(), csv_path=path)
            _stop(_DDOS_INFRA)
        finally:
            os.unlink(path)
        assert len(captured) == 1
        assert "DDOS_ALERT_SERVICE" not in captured[0]["risk_flags"]

    def test_unsw_format_detected_from_headers(self) -> None:
        """UNSW-NB15 format is auto-detected from column names."""
        path = _write_csv(
            ["srcip", "dstip", "Label", "sbytes", "dbytes"],
            [
                ["172.16.0.1", "10.0.0.1", "1", "4000", "1000"],
                ["172.16.0.2", "10.0.0.2", "0", "200", "100"],
            ],
        )
        try:
            result, _ = self._run(path)
            assert result["status"] == "ok"
            assert result["format"] == "unsw_nb15"
            assert result["total_source_ips"] == 2
        finally:
            os.unlink(path)

    def test_unsw_label_1_gets_ddos_flag(self) -> None:
        """UNSW label=1 (attack) produces the DDOS_ALERT_SERVICE flag."""
        captured, cap_patch = _make_snapshot_capturer(_ddos_mod)
        path = _write_csv(
            ["srcip", "dstip", "Label"],
            [["11.22.33.44", "55.66.77.88", "1"]],
        )
        try:
            _start(_DDOS_INFRA)
            with cap_patch:
                ddos_run_ingest(_StubDB(), csv_path=path)
            _stop(_DDOS_INFRA)
        finally:
            os.unlink(path)
        assert len(captured) == 1
        assert "DDOS_ALERT_SERVICE" in captured[0]["risk_flags"]

    def test_aggregate_counts_unique_destinations(self) -> None:
        """Three flows from the same src IP to different dsts = 3 unique dests."""
        path = _write_csv(
            ["Source IP", "Destination IP", "Label"],
            [
                ["10.10.10.1", "1.1.1.1", "DDoS"],
                ["10.10.10.1", "2.2.2.2", "DDoS"],
                ["10.10.10.1", "3.3.3.3", "DDoS"],
            ],
        )
        try:
            _, stats = ddos_aggregate(path)
            s = stats["ip:10.10.10.1"]
            assert s["event_count"] == 3
            assert len(s["unique_dests"]) == 3
        finally:
            os.unlink(path)

    def test_unknown_format_raises_value_error(self) -> None:
        """A CSV with unrecognised headers raises ValueError."""
        path = _write_csv(
            ["timestamp", "bytes", "packets"],
            [["2026-01-01", "100", "5"]],
        )
        try:
            with pytest.raises(ValueError, match="Cannot detect DDoS CSV format"):
                ddos_aggregate(path)
        finally:
            os.unlink(path)

    def test_window_key_is_wddos(self) -> None:
        """GraphFeatureSnapshot rows use window_key='Wddos'."""
        captured, cap_patch = _make_snapshot_capturer(_ddos_mod)
        path = _write_csv(
            ["Source IP", "Destination IP", "Label"],
            [["8.8.8.8", "1.1.1.1", "SYN Flood"]],
        )
        try:
            _start(_DDOS_INFRA)
            with cap_patch:
                ddos_run_ingest(_StubDB(), csv_path=path)
            _stop(_DDOS_INFRA)
        finally:
            os.unlink(path)
        assert captured[0]["window_key"] == "Wddos"
        assert captured[0]["entity_type"] == "ip"


# ===========================================================================
# Task 6 — vpn_benchmark_ingest
# ===========================================================================


class TestVpnBenchmarkIngest:
    """Unit tests for app.analytics.layer3.vpn_benchmark_ingest."""

    def _run(self, path: str) -> tuple:
        """Run vpn_run_ingest with patched DB infra; return (result, db)."""
        db = _StubDB()
        _start(_VPN_INFRA)
        try:
            result = vpn_run_ingest(db, csv_path=path)
        finally:
            _stop(_VPN_INFRA)
        return result, db

    def test_vpn_label_gets_vpn_cluster_member_flag(self) -> None:
        """A VPN-labelled flow produces the VPN_CLUSTER_MEMBER risk flag."""
        captured, cap_patch = _make_snapshot_capturer(_vpn_mod)
        path = _write_csv(
            ["src_ip", "label", "Flow Duration", "Total Fwd Packets"],
            [["192.168.1.50", "VPN", "5000", "1200"]],
        )
        try:
            _start(_VPN_INFRA)
            with cap_patch:
                vpn_run_ingest(_StubDB(), csv_path=path)
            _stop(_VPN_INFRA)
        finally:
            os.unlink(path)
        assert len(captured) == 1
        assert "VPN_CLUSTER_MEMBER" in captured[0]["risk_flags"]

    def test_nonvpn_label_has_empty_risk_flags(self) -> None:
        """A nonVPN-labelled flow produces an empty risk_flags list."""
        captured, cap_patch = _make_snapshot_capturer(_vpn_mod)
        path = _write_csv(
            ["src_ip", "label", "Flow Duration"],
            [["10.10.10.10", "nonVPN", "100"]],
        )
        try:
            _start(_VPN_INFRA)
            with cap_patch:
                vpn_run_ingest(_StubDB(), csv_path=path)
            _stop(_VPN_INFRA)
        finally:
            os.unlink(path)
        assert len(captured) == 1
        assert captured[0]["risk_flags"] == []

    def test_window_key_is_wvpn(self) -> None:
        """GraphFeatureSnapshot rows use window_key='Wvpn'."""
        captured, cap_patch = _make_snapshot_capturer(_vpn_mod)
        path = _write_csv(
            ["src_ip", "label"],
            [["172.31.0.1", "VPN"]],
        )
        try:
            _start(_VPN_INFRA)
            with cap_patch:
                vpn_run_ingest(_StubDB(), csv_path=path)
            _stop(_VPN_INFRA)
        finally:
            os.unlink(path)
        assert captured[0]["window_key"] == "Wvpn"
        assert captured[0]["entity_type"] == "ip"

    def test_is_vpn_column_overrides_label(self) -> None:
        """is_vpn=1 column triggers VPN classification regardless of label."""
        path = _write_csv(
            ["src_ip", "is_vpn", "label"],
            [
                ["1.2.3.4", "1", "other"],
                ["5.6.7.8", "0", "http"],
            ],
        )
        try:
            result, _ = self._run(path)
            assert result["status"] == "ok"
            assert result["vpn_ips"] == 1
        finally:
            os.unlink(path)

    def test_mixed_traffic_per_ip_aggregated(self) -> None:
        """VPN and nonVPN flows for the same IP are aggregated together."""
        path = _write_csv(
            ["src_ip", "label", "Flow Duration", "Total Fwd Packets"],
            [
                ["192.168.100.1", "VPN", "2000", "500"],
                ["192.168.100.1", "nonVPN", "1000", "200"],
                ["192.168.100.1", "VPN", "3000", "700"],
            ],
        )
        try:
            stats = vpn_aggregate(path)
            s = stats["ip:192.168.100.1"]
            assert s["conn_count"] == 3
            assert s["vpn_count"] == 2
            assert s["nonvpn_count"] == 1
        finally:
            os.unlink(path)

    def test_vpn_entity_requires_majority_vpn_traffic(self) -> None:
        """A mixed IP stays negative when VPN is not the strict majority."""
        captured, cap_patch = _make_snapshot_capturer(_vpn_mod)
        path = _write_csv(
            ["src_ip", "label", "Flow Duration", "Total Fwd Packets"],
            [
                ["192.168.100.2", "VPN", "2000", "500"],
                ["192.168.100.2", "nonVPN", "1000", "200"],
                ["192.168.100.2", "nonVPN", "3000", "700"],
            ],
        )
        try:
            _start(_VPN_INFRA)
            with cap_patch:
                vpn_run_ingest(_StubDB(), csv_path=path)
            _stop(_VPN_INFRA)
        finally:
            os.unlink(path)
        assert len(captured) == 1
        assert captured[0]["risk_flags"] == []

    def test_row_missing_src_ip_skipped(self) -> None:
        """Rows with an empty src_ip are skipped silently."""
        path = _write_csv(
            ["src_ip", "label"],
            [["", "VPN"]],
        )
        try:
            result, _ = self._run(path)
            assert result["snapshots"] == 0
        finally:
            os.unlink(path)


# ===========================================================================
# Import-time smoke tests
# ===========================================================================


def test_all_modules_importable() -> None:
    """All four new ingester modules must be importable at collection time."""
    # Importing at the top of this file is the real test; this is a checkpoint.
    assert _tf_mod is not None
    assert _mb_mod is not None
    assert _ddos_mod is not None
    assert _vpn_mod is not None


def test_pipeline_runner_importable() -> None:
    """run_threat_intel_pipeline must be importable from real_data_pipeline."""
    assert callable(run_threat_intel_pipeline)


# ===========================================================================
# Task 7 — run_threat_intel_pipeline wiring
# ===========================================================================


class TestPipelineRunner:
    """Unit tests for the THREATFOX/MALWAREBAZAAR wiring in real_data_pipeline."""

    _TF_TARGET = "app.analytics.layer3.threatfox_ingest.run_ingest"
    _MB_TARGET = "app.analytics.layer3.malwarebazaar_ingest.run_ingest"

    def _ok_tf(self, _db: Any, **_kw: Any) -> Dict[str, Any]:
        return {"status": "ok", "events": 3, "snapshots": 2}

    def _ok_mb(self, _db: Any, **_kw: Any) -> Dict[str, Any]:
        return {"status": "ok", "events": 5, "snapshots": 4}

    def _run(self, env: Dict[str, str]) -> Dict[str, Any]:
        """Run pipeline with env overrides and both sub-jobs mocked."""
        db = _StubDB()
        with patch.dict(os.environ, env, clear=False):
            with patch(self._TF_TARGET, side_effect=self._ok_tf):
                with patch(self._MB_TARGET, side_effect=self._ok_mb):
                    return run_threat_intel_pipeline(db=db)

    def test_both_disabled_by_default(self) -> None:
        """With neither env var set both jobs report disabled."""
        result = self._run({"THREATFOX_ENABLED": "", "MALWAREBAZAAR_ENABLED": ""})
        assert result["threatfox"]["status"] == "disabled"
        assert result["malwarebazaar"]["status"] == "disabled"

    def test_threatfox_enabled_runs_ingest(self) -> None:
        """THREATFOX_ENABLED=true triggers the ThreatFox sub-job."""
        result = self._run({"THREATFOX_ENABLED": "true", "MALWAREBAZAAR_ENABLED": ""})
        assert result["threatfox"]["status"] == "ok"
        assert result["malwarebazaar"]["status"] == "disabled"

    def test_malwarebazaar_enabled_runs_ingest(self) -> None:
        """MALWAREBAZAAR_ENABLED=true triggers the MalwareBazaar sub-job."""
        result = self._run({"THREATFOX_ENABLED": "", "MALWAREBAZAAR_ENABLED": "true"})
        assert result["threatfox"]["status"] == "disabled"
        assert result["malwarebazaar"]["status"] == "ok"

    def test_both_enabled(self) -> None:
        """Both env vars true → both sub-jobs run successfully."""
        result = self._run({"THREATFOX_ENABLED": "true", "MALWAREBAZAAR_ENABLED": "true"})
        assert result["threatfox"]["status"] == "ok"
        assert result["malwarebazaar"]["status"] == "ok"

    def test_threatfox_failure_does_not_abort_malwarebazaar(self) -> None:
        """A ThreatFox exception must not prevent MalwareBazaar from running."""
        def _fail(_db: Any, **_kw: Any) -> None:
            raise RuntimeError("TF boom")

        db = _StubDB()
        with patch.dict(
            os.environ,
            {"THREATFOX_ENABLED": "true", "MALWAREBAZAAR_ENABLED": "true"},
            clear=False,
        ):
            with patch(self._TF_TARGET, side_effect=_fail):
                with patch(self._MB_TARGET, side_effect=self._ok_mb):
                    result = run_threat_intel_pipeline(db=db)

        assert result["threatfox"]["status"] == "error"
        assert "TF boom" in result["threatfox"]["error"]
        assert result["malwarebazaar"]["status"] == "ok"
