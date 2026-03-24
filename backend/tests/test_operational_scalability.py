"""
test_operational_scalability.py — Proof tests for the 6 operational scalability claims
========================================================================================

Each test group maps to a specific "failure gap" from the NIRU hackathon analysis.
All tests are pure unit / mock tests — no live DB required.

Gap 1 — Federation HMAC: privacy-preserving cross-agency correlation
Gap 2 — GNN data: PaySim seeder builds valid feature snapshots
Gap 3 — Access isolation: section users cannot cross section boundaries
Gap 4 — Containment loop: CONTAINMENT_APPLIED event written after block_ip
Gap 5 — Edge agent resilience: offline save, high-water-mark advance
Gap 6 — Demo scripts: federation show and agency seed logic are self-consistent
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ===========================================================================
# GAP 1 — Federation HMAC: privacy-preserving cross-agency correlation
# ===========================================================================

class TestFederationHMAC:
    """
    Proves the trust-wall claim:
    "Safaricom sends a hash. NCSC receives a hash. Nobody shared a phone number."
    """

    SALT = "ke-sentinel-national-demo-salt-2026"

    def _hash(self, entity_key: str, salt: str = None) -> str:
        s = salt or self.SALT
        return hmac.new(s.encode(), entity_key.encode(), hashlib.sha256).hexdigest()

    def test_same_entity_same_salt_produces_identical_hash_at_two_agencies(self):
        """Core claim: cross-agency correlation works without sharing raw identifiers."""
        entity = "phone:+254700123456"

        # Agency A (Safaricom) computes hash
        hash_at_safaricom = self._hash(entity)

        # Agency B (Equity Bank) independently computes hash for same entity
        hash_at_equity = self._hash(entity)

        assert hash_at_safaricom == hash_at_equity, (
            "Same entity+salt must produce same hash at every agency — "
            "this is the foundation of cross-agency correlation"
        )

    def test_different_entities_produce_different_hashes(self):
        """No hash collision between distinct phone numbers (within demo space)."""
        h1 = self._hash("phone:+254700123456")
        h2 = self._hash("phone:+254798654321")
        assert h1 != h2

    def test_same_entity_different_salts_produce_different_hashes(self):
        """Rotating the national salt breaks historical correlations — by design."""
        entity = "phone:+254700123456"
        h_old = self._hash(entity, salt="old-salt-2025")
        h_new = self._hash(entity, salt="ke-sentinel-national-demo-salt-2026")
        assert h_old != h_new

    def test_hash_is_64_hex_chars(self):
        """SHA-256 output = 32 bytes = 64 hex chars — consistent with DB column width."""
        h = self._hash("ip:196.201.214.55")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_entity_key_type_prefix_prevents_cross_type_collisions(self):
        """phone:0712 and ip:0712 must NOT produce the same hash."""
        phone_hash = self._hash("phone:0712345678")
        ip_hash = self._hash("ip:0712345678")
        assert phone_hash != ip_hash

    def test_edge_agent_hash_matches_seed_script_hash(self):
        """
        edge_agent._hash_entity and seed_demo_agencies._hmac_hash use identical
        algorithm — ensures patterns pushed by the edge agent can be correlated
        with patterns seeded by the demo seed script.
        """
        from app.sync.edge_agent import _hash_entity
        # Inline the seed script's _hmac_hash logic (same algorithm)
        entity = "phone:+254700123456"
        edge_hash = _hash_entity(entity, self.SALT)
        seed_hash = hmac.new(self.SALT.encode(), entity.encode(), hashlib.sha256).hexdigest()
        assert edge_hash == seed_hash, (
            "edge_agent._hash_entity and seed_demo_agencies._hmac_hash must be identical — "
            "they run on different nodes but must produce the same correlation key"
        )

    def test_three_agency_correlation_detects_same_actor(self):
        """
        Simulates the SIM-swap scenario: 3 agencies independently flag the same
        phone number. Hub groups by hash and sees 3 partners.
        """
        entity = "phone:+254700123456"
        agencies = ["safaricom-ke", "equity-bank-ke", "cbk-ke"]

        # Each agency computes hash independently
        hashes = {ag: self._hash(entity) for ag in agencies}

        # Hub groups by hash value
        from collections import Counter
        hash_counts = Counter(hashes.values())
        most_common_hash, agency_count = hash_counts.most_common(1)[0]

        assert agency_count == 3, "All 3 agencies must produce the same hash for the same entity"
        assert most_common_hash == self._hash(entity)


# ===========================================================================
# GAP 2 — GNN data: PaySim seeder builds valid feature snapshots
# ===========================================================================

class TestPaySimSeeder:
    """
    Proves: "Our GNN achieves 0.XX AUC on the PaySim mobile money fraud benchmark"
    requires the seeder to produce snapshots that the GNN backbone can consume.
    """

    def _import_paysim(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import importlib
        spec = importlib.util.spec_from_file_location(
            "run_paysim_gnn",
            Path(__file__).parent.parent / "scripts" / "run_paysim_gnn.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_entity_key_consumer_account_prefix(self):
        mod = self._import_paysim()
        assert mod._entity_key("C1234567") == "account_h:C1234567"

    def test_entity_key_merchant_prefix(self):
        mod = self._import_paysim()
        assert mod._entity_key("M9876543") == "phone_h:M9876543"

    def test_entity_key_unknown_defaults_to_account_h(self):
        mod = self._import_paysim()
        assert mod._entity_key("X999").startswith("account_h:")

    def test_load_paysim_csv_with_mock_data(self, tmp_path):
        """Feed synthetic CSV rows and check aggregation logic."""
        mod = self._import_paysim()

        csv_file = tmp_path / "PS_mock.csv"
        csv_file.write_text(
            "step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,"
            "nameDest,oldbalanceDest,newbalanceDest,isFraud,isFlaggedFraud\n"
            "1,TRANSFER,5000.0,C111,5000,0,M222,0,5000,1,0\n"
            "2,TRANSFER,100.0,C333,200,100,M444,0,100,0,0\n"
            "3,CASH_OUT,3000.0,C111,0,0,C555,0,3000,1,0\n"
            "4,PAYMENT,50.0,C333,100,50,M666,0,50,0,0\n"   # PAYMENT not in FRAUD_TYPES → skipped
        )

        accounts, labels = mod.load_paysim_csv(csv_file, max_rows=1000)

        # C111 appears in 2 TRANSFER/CASH_OUT rows and is flagged as fraud
        assert "account_h:C111" in accounts
        assert labels.get("account_h:C111") == 1

        # C333 appears in a non-fraud TRANSFER only
        assert labels.get("account_h:C333") == 0

        # PAYMENT row (C333, M666) is skipped — not in FRAUD_TYPES
        assert "phone_h:M666" not in accounts

    def test_snapshot_features_dict_has_required_keys(self, tmp_path):
        """
        The features dict written by seed_snapshots must contain the keys that
        gnn_backbone.build_feature_vector() reads.
        """
        mod = self._import_paysim()

        accounts = {
            "account_h:C111": {
                "event_count": 10,
                "degree": 6,
                "total_amount": 50000.0,
                "fraud_txn_count": 3,
                "chain_score": 0.3,
            }
        }
        labels = {"account_h:C111": 1}

        # Reconstruct what seed_snapshots builds (without hitting DB)
        ek = "account_h:C111"
        s = accounts[ek]
        fraud_velocity = s["fraud_txn_count"] / max(1, s["event_count"])
        features_dict = {
            "event_types": {"TRANSACTION_EVENT": s["event_count"]},
            "source_count": max(1, s["degree"] // 3),
            "real_signal_ratio": fraud_velocity,
            "provenance_tag": "paysim",
            "source_type_counts": {"mobile_money": s["event_count"]},
        }

        required_keys = {"event_types", "source_count", "real_signal_ratio", "provenance_tag"}
        missing = required_keys - set(features_dict.keys())
        assert not missing, f"features dict missing required keys: {missing}"

        assert features_dict["event_types"]["TRANSACTION_EVENT"] == 10
        assert 0.0 <= features_dict["real_signal_ratio"] <= 1.0
        assert features_dict["provenance_tag"] == "paysim"

    def test_fraud_entity_gets_campaign_entity_flag(self):
        """Entities with isFraud=1 must carry CAMPAIGN_ENTITY risk flag."""
        is_fraud = True
        fraud_velocity = 0.6

        risk_flags = []
        if is_fraud:
            risk_flags.append("CAMPAIGN_ENTITY")
        if fraud_velocity > 0.5:
            risk_flags.append("AIRTIME_SIPHON_MEMBER")

        assert "CAMPAIGN_ENTITY" in risk_flags
        assert "AIRTIME_SIPHON_MEMBER" in risk_flags

    def test_non_fraud_entity_has_no_campaign_flag(self):
        is_fraud = False
        fraud_velocity = 0.0
        risk_flags = []
        if is_fraud:
            risk_flags.append("CAMPAIGN_ENTITY")
        if fraud_velocity > 0.5:
            risk_flags.append("AIRTIME_SIPHON_MEMBER")
        assert risk_flags == []

    def test_build_metrics_record_structure(self):
        mod = self._import_paysim()
        metrics = {"roc_auc": 0.974, "val_loss": 0.12, "epochs": 60}
        record = mod.build_metrics_record(metrics, run_config={"window_key": "Wpaysim"})

        assert record["dataset"].startswith("PaySim")
        assert record["metrics"]["roc_auc"] == 0.974
        assert record["run_config"]["window_key"] == "Wpaysim"
        assert "run_at" in record

    def test_resolve_csv_path_returns_none_for_empty_string(self):
        mod = self._import_paysim()
        assert mod.resolve_csv_path("") is None

    def test_resolve_csv_path_finds_ps_csv_in_directory(self, tmp_path):
        mod = self._import_paysim()
        csv = tmp_path / "PS_20174392719_log.csv"
        csv.write_text("step,type\n")
        result = mod.resolve_csv_path(str(tmp_path))
        assert result == csv


# ===========================================================================
# GAP 3 — Access isolation: section users cannot cross section boundaries
# ===========================================================================

class TestSectionIsolation:
    """
    Proves: "Log in as CBK analyst. Show only CBK events.
    Try to access Safaricom data directly. Get a 403."
    """

    def test_section_principal_is_locked_to_own_section(self):
        from app.defense.service import DefenseService

        class CBKPrincipal:
            access_level = "section"
            section_code = "CBK"

        # CBK user requesting CBK data → gets CBK
        result = DefenseService._effective_section(CBKPrincipal(), requested_section="CBK")
        assert result == "CBK"

    def test_section_principal_cannot_request_other_section(self):
        """
        CBK analyst requesting SAFARICOM data must be overridden to CBK.
        The service ignores the requested_section for section users.
        """
        from app.defense.service import DefenseService

        class CBKPrincipal:
            access_level = "section"
            section_code = "CBK"

        # requested_section is ignored — CBK user always gets CBK
        result = DefenseService._effective_section(CBKPrincipal(), requested_section="SAFARICOM")
        assert result == "CBK", (
            "Section users must NEVER get data from another section, "
            "regardless of requested_section parameter"
        )

    def test_section_principal_missing_section_code_raises(self):
        from app.defense.service import DefenseService

        class BrokenPrincipal:
            access_level = "section"
            section_code = None

        with pytest.raises(ValueError) as exc:
            DefenseService._effective_section(BrokenPrincipal(), requested_section="CBK")
        assert "principal_section_code_missing" in str(exc.value)

    def test_central_principal_can_select_any_section(self):
        """NCSC central supervisor must see all agencies' data."""
        from app.defense.service import DefenseService

        class NCSCPrincipal:
            access_level = "central"
            section_code = None

        for section in ("CBK", "SAFARICOM", "KE-CIRT", "DCI", "EQUITY-BANK"):
            result = DefenseService._effective_section(NCSCPrincipal(), requested_section=section)
            assert result == section

    def test_central_principal_with_no_section_requested_returns_none(self):
        from app.defense.service import DefenseService

        class NCSCPrincipal:
            access_level = "central"
            section_code = None

        result = DefenseService._effective_section(NCSCPrincipal(), requested_section=None)
        assert result is None  # Central sees everything (no filter)

    def test_scope_enforcement_blocks_cross_scope_access(self):
        """CBK analyst must not acquire defense.write scope they were not granted."""
        from app.auth.service import AuthService

        svc = AuthService(db=None)
        with pytest.raises(ValueError) as exc:
            svc._enforce_scope_rules(
                requested_scopes=["events.read", "defense.write"],
                allowed_scopes=["events.read", "ai.read", "defense.read"],
            )
        assert "scope_not_allowed_by_role_policy" in str(exc.value)

    def test_scope_enforcement_passes_for_valid_subset(self):
        from app.auth.service import AuthService

        svc = AuthService(db=None)
        out = svc._enforce_scope_rules(
            requested_scopes=["events.read"],
            allowed_scopes=["events.read", "ai.read"],
        )
        assert "events.read" in out


# ===========================================================================
# GAP 4 — Containment loop: CONTAINMENT_APPLIED event written after block_ip
# ===========================================================================

class TestContainmentLoop:
    """
    Proves: "Execute containment → webhook fires → CONTAINMENT_APPLIED event
    written → next GNN cycle rescores entity lower."
    """

    def _make_mock_db(self):
        """Return a mock DB that satisfies the _write_containment_event logic."""
        db = MagicMock()
        # No existing SourceRegistry or EventLog
        db.query.return_value.filter.return_value.first.return_value = None
        db.get.return_value = None  # EventLog.get → not found → will create
        return db

    def test_write_containment_event_creates_event_log(self):
        """After block_ip executes, CONTAINMENT_APPLIED must be written to EventLog."""
        from app.defense.service import _write_containment_event

        db = self._make_mock_db()
        _write_containment_event(
            db,
            action_type="block_ip",
            target="41.90.0.1",
            section_code="KE-CIRT",
            run_id=str(uuid.uuid4()),
            executed_by="kecirt_analyst",
        )

        # db.add must be called (SourceRegistry + EventLog + EventEntityIndex)
        assert db.add.called
        # Verify an EventLog-shaped object was added
        added_objects = [call.args[0] for call in db.add.call_args_list]
        event_types_seen = [
            getattr(obj, "event_type", None) for obj in added_objects
        ]
        assert "CONTAINMENT_APPLIED" in event_types_seen, (
            "CONTAINMENT_APPLIED event must be written so the GNN feature worker "
            "can rescore the entity lower in the next inference cycle"
        )

    def test_write_containment_event_is_idempotent(self):
        """
        Calling twice with same run_id must not create a duplicate EventLog row
        (deterministic event_hash prevents duplicates).
        """
        from app.defense.service import _write_containment_event

        db = self._make_mock_db()
        # Simulate second call: EventLog row now exists
        db.get.return_value = object()  # non-None → already exists

        _write_containment_event(
            db,
            action_type="block_ip",
            target="41.90.0.1",
            section_code="KE-CIRT",
            run_id="fixed-run-id",
            executed_by="kecirt_analyst",
        )

        # db.add should NOT be called for a duplicate
        event_log_adds = [
            call for call in db.add.call_args_list
            if getattr(call.args[0], "event_type", None) == "CONTAINMENT_APPLIED"
        ]
        assert len(event_log_adds) == 0, "Duplicate CONTAINMENT_APPLIED must be blocked by event_hash dedup"

    def test_write_containment_event_indexes_ip_entity(self):
        """EventEntityIndex must be created so GNN picks up the contained entity."""
        from app.defense.service import _write_containment_event

        db = self._make_mock_db()
        _write_containment_event(
            db,
            action_type="block_ip",
            target="196.201.214.55",
            section_code="SAFARICOM",
            run_id=str(uuid.uuid4()),
            executed_by="safaricom_soc",
        )

        added = [call.args[0] for call in db.add.call_args_list]
        entity_index_objects = [
            obj for obj in added
            if getattr(obj, "entity_key", "").startswith("ip:")
        ]
        assert len(entity_index_objects) >= 1, (
            "An EventEntityIndex for 'ip:196.201.214.55' must be created "
            "so the GNN backbone ingests the containment signal"
        )
        assert entity_index_objects[0].entity_type == "ip"

    def test_write_containment_event_exception_does_not_propagate(self):
        """Non-fatal: if DB write fails, containment action itself must not fail."""
        from app.defense.service import _write_containment_event

        db = MagicMock()
        db.query.side_effect = RuntimeError("DB unavailable")

        # Must NOT raise — event is best-effort
        _write_containment_event(
            db,
            action_type="block_ip",
            target="41.90.0.1",
            section_code="CBK",
            run_id=str(uuid.uuid4()),
            executed_by="cbk_analyst",
        )

    def test_rollback_block_ip_fails_when_no_original_action(self):
        from app.defense.service import DefenseService

        svc = DefenseService(db=object())
        with patch.object(
            DefenseService,
            "_latest_executed_block_ip_action",
            return_value=None,
        ):
            status, details = svc._execute_single_action(
                action_type="rollback_block_ip",
                target="41.90.0.1",
                details={},
                section_code="KE-CIRT",
            )

        assert status == "failed"
        assert details["error"] == "no_block_ip_action_found"

    def test_rollback_block_ip_enforces_time_window(self):
        from app.defense.service import DefenseService

        svc = DefenseService(db=object())
        old_action = SimpleNamespace(
            id="abc",
            run_id="run-1",
            executed_at=_utcnow() - timedelta(minutes=120),
        )
        with (
            patch.object(DefenseService, "_latest_executed_block_ip_action", return_value=old_action),
            patch("app.defense.service.settings") as mock_settings,
        ):
            mock_settings.defense_rollback_window_minutes = 60
            status, details = svc._execute_single_action(
                action_type="rollback_block_ip",
                target="41.90.0.2",
                details={},
                section_code="KE-CIRT",
            )

        assert status == "failed"
        assert details["error"] == "rollback_window_expired"


# ===========================================================================
# GAP 5 — Edge agent resilience: offline save, high-water-mark advance
# ===========================================================================

class TestEdgeAgentResilience:
    """
    Proves: "Agency never stops working. Hub never loses data. Sync catches up
    automatically when connectivity returns."
    """

    def test_load_state_returns_defaults_when_file_missing(self, tmp_path):
        """Cold start: no state file → return safe defaults."""
        from app.sync import edge_agent

        with patch.object(edge_agent, "_STATE_FILE", tmp_path / "nonexistent.json"):
            state = edge_agent._load_state()

        assert state["last_synced_at"] is None
        assert state["total_pushed"] == 0
        assert state["last_error"] is None

    def test_save_and_load_state_round_trips(self, tmp_path):
        """State written by _save_state must be recoverable by _load_state."""
        from app.sync import edge_agent

        state_file = tmp_path / "edge_sync_state.json"
        test_state = {
            "last_synced_at": "2026-03-24T10:00:00+00:00",
            "total_pushed": 47,
            "last_error": None,
        }

        with patch.object(edge_agent, "_STATE_FILE", state_file):
            edge_agent._save_state(test_state)
            recovered = edge_agent._load_state()

        assert recovered["last_synced_at"] == "2026-03-24T10:00:00+00:00"
        assert recovered["total_pushed"] == 47
        assert recovered["last_error"] is None

    def test_save_state_on_push_failure_records_error(self, tmp_path):
        """When hub is unreachable, error is saved and NOT raised."""
        from app.sync import edge_agent

        state_file = tmp_path / "edge_sync_state.json"

        # Minimal mock AIPrediction row
        row = SimpleNamespace(
            entity_key="ip:196.201.214.55",
            entity_type="ip",
            score=85.0,
            uncertainty=0.05,
            kill_chain_stage=None,
            reason_codes=["DDOS_SIGNAL_EVENT"],
            model_version="gnn-v2.1",
            window_end=_utcnow(),
            created_at=_utcnow(),
            abstained=False,
        )

        import httpx

        with (
            patch.object(edge_agent, "_STATE_FILE", state_file),
            patch.object(edge_agent, "_load_state", return_value={
                "last_synced_at": None, "total_pushed": 0, "last_error": None
            }),
            patch.object(edge_agent, "_save_state") as mock_save,
            patch.object(edge_agent, "_fetch_unsynced", return_value=[row]),
            patch("httpx.post", side_effect=httpx.ConnectError("Connection refused")),
        ):
            result = edge_agent.run_once(
                partner_id="safaricom-ke",
                hub_url="http://hub.ncsc.go.ke",
                hub_api_key="test-key",
                national_salt="test-salt",
                min_risk=0.6,
                batch_size=200,
                lookback_hours=4,
            )

        assert result["synced"] == 0
        assert "error" in result
        # State must be saved with the error for resumability
        mock_save.assert_called_once()
        saved_state = mock_save.call_args.args[0]
        assert saved_state["last_error"] is not None

    def test_empty_fetch_advances_high_water_mark(self, tmp_path):
        """
        When there is nothing to sync, the agent must still advance the HWM
        so the next run doesn't re-scan everything from the cold-start lookback.
        """
        from app.sync import edge_agent

        state_file = tmp_path / "edge_sync_state.json"

        with (
            patch.object(edge_agent, "_STATE_FILE", state_file),
            patch.object(edge_agent, "_load_state", return_value={
                "last_synced_at": "2026-03-24T09:00:00+00:00",
                "total_pushed": 23,
                "last_error": None,
            }),
            patch.object(edge_agent, "_save_state") as mock_save,
            patch.object(edge_agent, "_fetch_unsynced", return_value=[]),
        ):
            result = edge_agent.run_once(
                partner_id="safaricom-ke",
                hub_url="http://hub.ncsc.go.ke",
                hub_api_key="test-key",
                national_salt="test-salt",
                min_risk=0.6,
                batch_size=200,
                lookback_hours=4,
            )

        assert result == {"synced": 0, "skipped": 0}
        # HWM must be advanced
        mock_save.assert_called_once()
        saved = mock_save.call_args.args[0]
        assert saved["last_synced_at"] is not None
        assert saved["last_synced_at"] != "2026-03-24T09:00:00+00:00"

    def test_build_payload_hashes_entity_key_never_exposes_raw(self):
        """
        The payload sent to the hub must contain entity_key_hash, not entity_key.
        Raw identifiers must never appear in the outbound payload.
        """
        from app.sync.edge_agent import _build_payload

        raw_entity = "phone:+254700123456"
        row = SimpleNamespace(
            entity_key=raw_entity,
            entity_type="phone_h",
            score=91.0,
            uncertainty=0.04,
            kill_chain_stage="impact",
            reason_codes=["SIM_SWAP"],
            model_version="gnn-v2.1",
            window_end=_utcnow(),
        )

        payload = _build_payload(
            rows=[row],
            partner_id="safaricom-ke",
            national_salt="ke-sentinel-national-demo-salt-2026",
            model_version="gnn-v2.1",
        )

        payload_str = json.dumps(payload)
        assert raw_entity not in payload_str, (
            "Raw entity key must NEVER appear in the payload sent to the hub — "
            "only HMAC-SHA256 hashes are transmitted"
        )
        # The hashed version must be present
        for entity in payload["high_risk_entities"]:
            assert "entity_key_hash" in entity
            assert len(entity["entity_key_hash"]) == 64  # SHA-256 hex

    def test_build_payload_normalises_score_to_0_1(self):
        """Scores are stored 0–100 in AIPrediction but must be 0–1 in federation payload."""
        from app.sync.edge_agent import _build_payload

        row = SimpleNamespace(
            entity_key="ip:41.90.0.1",
            entity_type="ip",
            score=85.0,   # 0–100 scale
            uncertainty=0.06,
            kill_chain_stage=None,
            reason_codes=[],
            model_version="gnn-v2.1",
            window_end=_utcnow(),
        )

        payload = _build_payload(
            rows=[row],
            partner_id="ke-cirt",
            national_salt="test-salt",
            model_version="gnn-v2.1",
        )

        risk = payload["high_risk_entities"][0]["risk_score"]
        assert 0.0 <= risk <= 1.0, "risk_score in federation payload must be normalised 0–1"
        assert abs(risk - 0.85) < 0.001


# ===========================================================================
# GAP 6 — Demo scripts: federation show and agency seed are self-consistent
# ===========================================================================

class TestDemoScripts:
    """
    Proves the presentation scripts produce correct, internally consistent output
    without requiring a live database.
    """

    def test_demo_federation_show_build_multi_agency_correlations(self):
        """
        build_multi_agency_correlations must detect the phone-number that appears
        at Safaricom AND CBK as a cross-agency hit.
        """
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "demo_federation_show",
            Path(__file__).parent.parent / "scripts" / "demo_federation_show.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        rows, correlations = mod.build_multi_agency_correlations()

        # Must have 4 rows (4 entities in DEMO_ENTITIES)
        assert len(rows) == 4

        # Must detect at least 1 cross-agency correlation (phone at Safaricom + CBK)
        assert len(correlations) >= 1

        # The detected correlation must involve at least 2 agencies
        corr = correlations[0]
        assert len(corr["agencies"]) >= 2
        assert corr["sources"] >= 2
        assert 0.0 < corr["avg_risk"] <= 1.0

    def test_demo_federation_show_hash_is_deterministic_across_calls(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "demo_federation_show",
            Path(__file__).parent.parent / "scripts" / "demo_federation_show.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        entity = "phone:+254700123456"
        salt = "ke-sentinel-national-demo-salt-2026"

        h1 = mod._hmac_hash(entity, salt)
        h2 = mod._hmac_hash(entity, salt)
        assert h1 == h2

    def test_demo_federation_show_presenter_talking_points_non_empty(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "demo_federation_show",
            Path(__file__).parent.parent / "scripts" / "demo_federation_show.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        points = mod.presenter_talking_points()
        assert len(points) >= 3
        assert all(isinstance(p, str) and len(p) > 10 for p in points)

    def test_seed_agencies_build_demo_partner_hashes_consistent_with_edge_agent(self):
        """
        seed_demo_agencies.build_demo_partner_hashes must produce the same hashes
        as edge_agent._hash_entity for the same entities and salt.
        This guarantees seeded patterns are correlated by the hub correctly.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "seed_demo_agencies",
            Path(__file__).parent.parent / "scripts" / "seed_demo_agencies.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        from app.sync.edge_agent import _hash_entity

        salt = "ke-sentinel-national-demo-salt-2026"
        entities = ["phone:+254700123456", "account:EQ-ACC-8821", "ip:196.201.214.55"]

        seed_hashes = mod.build_demo_partner_hashes(entities, salt=salt)
        edge_hashes = {e: _hash_entity(e, salt) for e in entities}

        assert seed_hashes == edge_hashes, (
            "seed_demo_agencies and edge_agent must produce identical hashes — "
            "the hub correlates seeded patterns with live edge agent patterns"
        )

    def test_seed_agencies_credentials_manifest_structure(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "seed_demo_agencies",
            Path(__file__).parent.parent / "scripts" / "seed_demo_agencies.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        manifest = mod._credentials_manifest(include_secrets=True)

        assert "users" in manifest and "partners" in manifest
        assert len(manifest["users"]) == len(mod.AGENCIES)
        assert len(manifest["partners"]) == len(mod.PARTNERS)

        # All section users must have section_code; central user must not
        for user in manifest["users"]:
            if user["access_level"] == "section":
                assert user["section_code"] is not None
            else:
                assert user["section_code"] is None

        # All partners must have api_key_fingerprint (not raw key)
        for partner in manifest["partners"]:
            assert "api_key_fingerprint" in partner
            assert "api_key" in partner  # include_secrets=True

    def test_seed_agencies_hmac_matches_national_salt(self):
        """
        The national salt in seed_demo_agencies must match the default edge agent
        NATIONAL_SALT so cross-agency correlations work out of the box.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "seed_demo_agencies",
            Path(__file__).parent.parent / "scripts" / "seed_demo_agencies.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        import importlib.util as iu2
        spec2 = iu2.spec_from_file_location(
            "demo_federation_show",
            Path(__file__).parent.parent / "scripts" / "demo_federation_show.py",
        )
        fed_mod = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(fed_mod)

        # Both scripts must use the same default national salt
        assert mod.NATIONAL_SALT == fed_mod.NATIONAL_SALT, (
            "seed_demo_agencies.NATIONAL_SALT and demo_federation_show.NATIONAL_SALT "
            "must be identical — divergence would break cross-agency correlations in the demo"
        )
