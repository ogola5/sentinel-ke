from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.layer3.threat_pattern_worker import run_once as run_threat_pattern_once
from app.analytics.threat_alerts import ThreatAlert
from app.auth.models import AuthUser
from app.auth.service import AuthService
from app.core.config import settings
from app.defense.executor import dispatch_containment_action
from app.defense.models import (
    BackupAttestation,
    ContainmentAction,
    ContainmentWebhook,
    CryptoPostureSnapshot,
    IncidentPlaybookRun,
    PatchSlaDecision,
    RestoreDrill,
    VulnerabilityFinding,
    WebhookDelivery,
)
from app.defense.schemas import (
    BackupAttestationRequest,
    CryptoSnapshotRequest,
    IncidentRunActionBatchRequest,
    IncidentRunCreateRequest,
    RestoreDrillRequest,
    ThreatAlertRefreshRequest,
    VulnerabilityUpsertRequest,
)
from app.ledger.models import SourceRegistry
from app.ledger.repository import LedgerRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _severity_weight(sev: str) -> float:
    x = str(sev or "").lower()
    if x == "critical":
        return 1.0
    if x == "high":
        return 0.85
    if x == "medium":
        return 0.6
    if x == "low":
        return 0.35
    return 0.5


def _status_from_score(score: float) -> str:
    if score >= 85:
        return "critical"
    if score >= 70:
        return "overdue"
    if score >= 50:
        return "warning"
    return "on_track"


def _alert_severity(score: float) -> str:
    if score >= 90:
        return "critical"
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


class DefenseService:
    def __init__(self, db: Session):
        self.db = db
        self.ledger = LedgerRepository(db)

    @staticmethod
    def _principal_section(principal: Any) -> str | None:
        if str(getattr(principal, "access_level", "")) == "section":
            return (getattr(principal, "section_code", None) or "").strip() or None
        return None

    @staticmethod
    def _effective_section(principal: Any, requested_section: str | None) -> str | None:
        if str(getattr(principal, "access_level", "")) == "section":
            sec = (getattr(principal, "section_code", None) or "").strip()
            if not sec:
                raise ValueError("principal_section_code_missing")
            return sec
        req = (requested_section or "").strip()
        return req or None

    @staticmethod
    def _risk_score_for_vuln(row: VulnerabilityFinding) -> float:
        base = _severity_weight(row.severity) * 100.0
        epss_bonus = float(row.epss or 0.0) * 20.0
        kev_bonus = 20.0 if bool(row.kev) else 0.0
        overdue_bonus = 0.0
        if row.status not in {"patched", "false_positive"} and row.due_at is not None:
            overdue_days = (_now() - row.due_at).total_seconds() / 86400.0
            if overdue_days > 0:
                overdue_bonus = min(30.0, overdue_days * 3.0)
        score = min(100.0, base + epss_bonus + kev_bonus + overdue_bonus)
        return round(score, 4)

    def upsert_vulnerability(self, *, payload: VulnerabilityUpsertRequest, principal: Any) -> Dict[str, Any]:
        section_code = self._effective_section(principal, payload.section_code)
        cve_id = payload.cve_id.strip().upper()
        source = payload.source.strip().lower()
        asset_id = payload.asset_id.strip()

        row = (
            self.db.query(VulnerabilityFinding)
            .filter(VulnerabilityFinding.section_code == section_code)
            .filter(VulnerabilityFinding.asset_id == asset_id)
            .filter(VulnerabilityFinding.cve_id == cve_id)
            .filter(VulnerabilityFinding.source == source)
            .first()
        )

        discovered_at = payload.discovered_at or _now()
        if row:
            row.severity = payload.severity
            row.epss = payload.epss
            row.kev = bool(payload.kev)
            row.status = payload.status
            row.discovered_at = discovered_at
            row.due_at = payload.due_at
            row.patched_at = payload.patched_at
            row.metadata_json = dict(payload.metadata or {})
            row.updated_at = _now()
        else:
            row = VulnerabilityFinding(
                section_code=section_code,
                asset_id=asset_id,
                cve_id=cve_id,
                source=source,
                severity=payload.severity,
                epss=payload.epss,
                kev=bool(payload.kev),
                status=payload.status,
                discovered_at=discovered_at,
                due_at=payload.due_at,
                patched_at=payload.patched_at,
                metadata_json=dict(payload.metadata or {}),
            )
            self.db.add(row)
            self.db.flush()

        row.risk_score = self._risk_score_for_vuln(row)
        self.db.commit()

        self.ledger.audit(
            actor_type="analyst",
            actor_id=str(getattr(principal, "actor_id", "api")),
            action="defense.vulnerability.upsert",
            target=f"{row.asset_id}:{row.cve_id}",
            section_code=section_code,
        )
        return self._vuln_to_dict(row)

    def list_vulnerabilities(
        self,
        *,
        principal: Any,
        status: str | None,
        section_code: str | None,
        limit: int,
        offset: int,
    ) -> Dict[str, Any]:
        sec = self._effective_section(principal, section_code)
        q = self.db.query(VulnerabilityFinding)
        if sec:
            q = q.filter(VulnerabilityFinding.section_code == sec)
        if status:
            q = q.filter(VulnerabilityFinding.status == status)
        total = q.count()
        rows = (
            q.order_by(VulnerabilityFinding.risk_score.desc(), VulnerabilityFinding.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "total": total,
            "items": [self._vuln_to_dict(x) for x in rows],
        }

    def score_patch_sla(self, *, principal: Any, section_code: str | None = None) -> Dict[str, int]:
        sec = self._effective_section(principal, section_code)
        q = self.db.query(VulnerabilityFinding)
        if sec:
            q = q.filter(VulnerabilityFinding.section_code == sec)
        q = q.filter(VulnerabilityFinding.status.notin_(["patched", "false_positive"]))
        rows = q.all()

        upserted = 0
        alerts = 0
        for row in rows:
            score = self._risk_score_for_vuln(row)
            row.risk_score = score
            status = _status_from_score(score)
            reasons = ["patch_sla_overdue"] if status in {"overdue", "critical"} else ["patch_sla_tracking"]

            existing = (
                self.db.query(PatchSlaDecision)
                .filter(PatchSlaDecision.finding_id == row.id)
                .first()
            )
            evidence = {
                "risk_score": score,
                "status": row.status,
                "due_at": row.due_at.isoformat() if row.due_at else None,
                "kev": bool(row.kev),
                "epss": row.epss,
            }
            if existing:
                existing.section_code = row.section_code
                existing.decision_status = status
                existing.score = score
                existing.reason_codes = reasons
                existing.evidence_json = evidence
                existing.updated_at = _now()
            else:
                self.db.add(
                    PatchSlaDecision(
                        finding_id=row.id,
                        section_code=row.section_code,
                        decision_status=status,
                        score=score,
                        reason_codes=reasons,
                        evidence_json=evidence,
                    )
                )
            upserted += 1

            if status in {"overdue", "critical"}:
                alerts += 1
                self._upsert_threat_alert_for_vuln(row=row, score=score, status=status)

        self.db.commit()
        return {"scored": upserted, "alerts": alerts}

    def _upsert_threat_alert_for_vuln(self, *, row: VulnerabilityFinding, score: float, status: str) -> None:
        now = _now()
        alert_row = {
            "alert_type": "vuln_overdue",
            "section_code": row.section_code,
            "entity_key": f"{row.asset_id}:{row.cve_id}",
            "window_start": now,
            "window_end": now,
            "score": round(score, 4),
            "severity": _alert_severity(score),
            "reason_codes": ["patch_sla_overdue", f"sla_status:{status}"],
            "indicators": {
                "asset_id": row.asset_id,
                "cve_id": row.cve_id,
                "due_at": row.due_at.isoformat() if row.due_at else None,
                "kev": bool(row.kev),
                "epss": row.epss,
            },
            "recommended_actions": [
                "apply emergency patch within maintenance window",
                "enable compensating controls",
                "escalate residual risk acceptance",
            ],
        }
        stmt = insert(ThreatAlert).values([alert_row])
        stmt = stmt.on_conflict_do_update(
            index_elements=["alert_type", "section_code", "entity_key", "window_end"],
            set_={
                "score": stmt.excluded.score,
                "severity": stmt.excluded.severity,
                "reason_codes": stmt.excluded.reason_codes,
                "indicators": stmt.excluded.indicators,
                "recommended_actions": stmt.excluded.recommended_actions,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        self.db.execute(stmt)

    def upsert_backup_attestation(self, *, payload: BackupAttestationRequest, principal: Any) -> Dict[str, Any]:
        section_code = self._effective_section(principal, payload.section_code)
        row = (
            self.db.query(BackupAttestation)
            .filter(BackupAttestation.section_code == section_code)
            .filter(BackupAttestation.asset_id == payload.asset_id)
            .filter(BackupAttestation.backup_id == payload.backup_id)
            .first()
        )
        if row:
            row.immutable = bool(payload.immutable)
            row.object_lock_until = payload.object_lock_until
            row.backup_hash = payload.backup_hash
            row.storage_tier = payload.storage_tier
            row.status = payload.status
            row.rpo_hours = payload.rpo_hours
            row.attested_at = payload.attested_at or _now()
            row.evidence_json = dict(payload.evidence or {})
        else:
            row = BackupAttestation(
                section_code=section_code,
                asset_id=payload.asset_id,
                backup_id=payload.backup_id,
                immutable=bool(payload.immutable),
                object_lock_until=payload.object_lock_until,
                backup_hash=payload.backup_hash,
                storage_tier=payload.storage_tier,
                status=payload.status,
                rpo_hours=payload.rpo_hours,
                attested_at=payload.attested_at or _now(),
                evidence_json=dict(payload.evidence or {}),
            )
            self.db.add(row)

        self.db.commit()
        self.ledger.audit(
            actor_type="analyst",
            actor_id=str(getattr(principal, "actor_id", "api")),
            action="defense.backup_attestation.upsert",
            target=f"{row.asset_id}:{row.backup_id}",
            section_code=section_code,
        )
        return self._backup_to_dict(row)

    def list_backup_attestations(
        self,
        *,
        principal: Any,
        section_code: str | None,
        limit: int,
        offset: int,
    ) -> Dict[str, Any]:
        sec = self._effective_section(principal, section_code)
        q = self.db.query(BackupAttestation)
        if sec:
            q = q.filter(BackupAttestation.section_code == sec)
        total = q.count()
        rows = q.order_by(BackupAttestation.attested_at.desc()).offset(offset).limit(limit).all()
        return {"total": total, "items": [self._backup_to_dict(x) for x in rows]}

    def create_restore_drill(self, *, payload: RestoreDrillRequest, principal: Any) -> Dict[str, Any]:
        section_code = self._effective_section(principal, payload.section_code)
        started_at = _now()
        completed_at = _now()

        row = RestoreDrill(
            section_code=section_code,
            asset_id=payload.asset_id,
            backup_id=payload.backup_id,
            started_at=started_at,
            completed_at=completed_at,
            success=bool(payload.success),
            rto_target_minutes=payload.rto_target_minutes,
            rto_actual_minutes=payload.rto_actual_minutes,
            operator_id=str(getattr(principal, "actor_id", "api")),
            notes=payload.notes,
            evidence_json=dict(payload.evidence or {}),
        )
        self.db.add(row)

        if not payload.success or (payload.rto_actual_minutes or 0.0) > float(payload.rto_target_minutes):
            self._upsert_restore_risk_alert(row=row)

        self.db.commit()
        self.ledger.audit(
            actor_type="analyst",
            actor_id=str(getattr(principal, "actor_id", "api")),
            action="defense.restore_drill.recorded",
            target=f"{row.asset_id}:{row.backup_id}",
            section_code=section_code,
        )
        return self._restore_to_dict(row)

    def _upsert_restore_risk_alert(self, *, row: RestoreDrill) -> None:
        score = 95.0 if not row.success else min(100.0, 60.0 + max(0.0, float((row.rto_actual_minutes or 0.0) - row.rto_target_minutes)) / 2.0)
        ts = row.completed_at or _now()
        alert_row = {
            "alert_type": "backup_risk",
            "section_code": row.section_code,
            "entity_key": f"{row.asset_id}:{row.backup_id}",
            "window_start": ts,
            "window_end": ts,
            "score": round(score, 4),
            "severity": _alert_severity(score),
            "reason_codes": ["restore_drill_failure" if not row.success else "restore_drill_rto_miss"],
            "indicators": {
                "success": bool(row.success),
                "rto_target_minutes": row.rto_target_minutes,
                "rto_actual_minutes": row.rto_actual_minutes,
            },
            "recommended_actions": [
                "validate backup integrity chain",
                "run tabletop + technical restore rehearsal",
                "verify immutable retention policy",
            ],
        }
        stmt = insert(ThreatAlert).values([alert_row])
        stmt = stmt.on_conflict_do_update(
            index_elements=["alert_type", "section_code", "entity_key", "window_end"],
            set_={
                "score": stmt.excluded.score,
                "severity": stmt.excluded.severity,
                "reason_codes": stmt.excluded.reason_codes,
                "indicators": stmt.excluded.indicators,
                "recommended_actions": stmt.excluded.recommended_actions,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        self.db.execute(stmt)

    def list_restore_drills(self, *, principal: Any, section_code: str | None, limit: int, offset: int) -> Dict[str, Any]:
        sec = self._effective_section(principal, section_code)
        q = self.db.query(RestoreDrill)
        if sec:
            q = q.filter(RestoreDrill.section_code == sec)
        total = q.count()
        rows = q.order_by(RestoreDrill.created_at.desc()).offset(offset).limit(limit).all()
        return {"total": total, "items": [self._restore_to_dict(x) for x in rows]}

    def create_incident_run(self, *, payload: IncidentRunCreateRequest, principal: Any) -> Dict[str, Any]:
        section_code = self._effective_section(principal, payload.section_code)
        row = IncidentPlaybookRun(
            incident_key=payload.incident_key,
            section_code=section_code,
            severity=payload.severity,
            status="running",
            created_by=str(getattr(principal, "actor_id", "api")),
            started_at=_now(),
            metadata_json=dict(payload.metadata or {}),
        )
        self.db.add(row)
        self.db.commit()
        self.ledger.audit(
            actor_type="analyst",
            actor_id=str(getattr(principal, "actor_id", "api")),
            action="defense.incident_run.created",
            target=row.incident_key,
            section_code=section_code,
        )
        return self._run_to_dict(row)

    def list_incident_runs(self, *, principal: Any, section_code: str | None, limit: int, offset: int) -> Dict[str, Any]:
        sec = self._effective_section(principal, section_code)
        q = self.db.query(IncidentPlaybookRun)
        if sec:
            q = q.filter(IncidentPlaybookRun.section_code == sec)
        total = q.count()
        rows = q.order_by(IncidentPlaybookRun.created_at.desc()).offset(offset).limit(limit).all()
        return {"total": total, "items": [self._run_to_dict(x) for x in rows]}

    def execute_run_actions(
        self,
        *,
        run_id: str,
        payload: IncidentRunActionBatchRequest,
        principal: Any,
    ) -> Dict[str, Any]:
        try:
            run_uuid = uuid.UUID(str(run_id))
        except ValueError:
            raise ValueError("incident_run_not_found")

        run = self.db.query(IncidentPlaybookRun).filter(IncidentPlaybookRun.id == run_uuid).first()
        if not run:
            raise ValueError("incident_run_not_found")

        sec = self._principal_section(principal)
        if sec and run.section_code != sec:
            raise ValueError("incident_run_not_found")

        out = []
        failures = 0
        for item in payload.actions:
            status, details = self._execute_single_action(
                action_type=item.action_type,
                target=item.target,
                details=item.details,
                section_code=run.section_code,
            )
            row = ContainmentAction(
                run_id=run.id,
                section_code=run.section_code,
                action_type=item.action_type,
                target=item.target,
                status=status,
                executed_by=str(getattr(principal, "actor_id", "api")),
                executed_at=_now(),
                details_json=details,
            )
            self.db.add(row)
            out.append(
                {
                    "action_type": item.action_type,
                    "target": item.target,
                    "status": status,
                    "details": details,
                }
            )
            if status != "executed":
                failures += 1

            self.ledger.audit(
                actor_type="analyst",
                actor_id=str(getattr(principal, "actor_id", "api")),
                action=f"defense.containment.{item.action_type}.{status}",
                target=item.target,
                section_code=run.section_code,
            )

        run.updated_at = _now()
        run.completed_at = _now()
        run.status = "completed" if failures == 0 else "failed"
        self.db.commit()

        return {
            "run_id": str(run.id),
            "status": run.status,
            "actions": out,
        }

    def _latest_executed_block_ip_action(
        self,
        *,
        section_code: str | None,
        target: str,
    ) -> ContainmentAction | None:
        q = (
            self.db.query(ContainmentAction)
            .filter(ContainmentAction.action_type == "block_ip")
            .filter(ContainmentAction.target == target)
            .filter(ContainmentAction.status == "executed")
        )
        if section_code is None:
            q = q.filter(ContainmentAction.section_code.is_(None))
        else:
            q = q.filter(ContainmentAction.section_code == section_code)
        return q.order_by(ContainmentAction.executed_at.desc()).first()

    def _rollback_already_executed(
        self,
        *,
        section_code: str | None,
        target: str,
        rollback_of_action_id: str,
    ) -> bool:
        q = (
            self.db.query(ContainmentAction)
            .filter(ContainmentAction.action_type == "rollback_block_ip")
            .filter(ContainmentAction.target == target)
            .filter(ContainmentAction.status == "executed")
        )
        if section_code is None:
            q = q.filter(ContainmentAction.section_code.is_(None))
        else:
            q = q.filter(ContainmentAction.section_code == section_code)

        for row in q.order_by(ContainmentAction.executed_at.desc()).limit(50).all():
            did = str((row.details_json or {}).get("rollback_of_action_id") or "")
            if did == rollback_of_action_id:
                return True
        return False

    def _execute_single_action(
        self,
        *,
        action_type: str,
        target: str,
        details: Dict[str, Any],
        section_code: str | None,
    ) -> tuple[str, Dict[str, Any]]:
        t = action_type.strip().lower()
        if t == "revoke_user":
            user = self.db.query(AuthUser).filter(AuthUser.username == target.strip().lower()).first()
            if not user:
                return "failed", {"error": "user_not_found"}
            if section_code and (
                user.access_level != "section" or (user.section_code or "").strip() != section_code
            ):
                return "failed", {"error": "unauthorized_target_section"}
            revoked = AuthService(self.db).revoke_all_user_sessions(user_id=str(user.user_id), reason="incident_response")
            return "executed", {"revoked_sessions": revoked}

        if t == "force_password_reset":
            new_password = str(details.get("new_password") or "").strip()
            if not new_password:
                return "failed", {"error": "new_password_required"}
            user = self.db.query(AuthUser).filter(AuthUser.username == target.strip().lower()).first()
            if not user:
                return "failed", {"error": "user_not_found"}
            if section_code and (
                user.access_level != "section" or (user.section_code or "").strip() != section_code
            ):
                return "failed", {"error": "unauthorized_target_section"}
            try:
                res = AuthService(self.db).admin_reset_password(
                    username=target.strip().lower(),
                    new_password=new_password,
                    revoke_existing_sessions=True,
                    actor_id="ir-playbook",
                )
                return "executed", res
            except ValueError as exc:
                return "failed", {"error": str(exc)}

        if t == "disable_source_key":
            src = self.db.query(SourceRegistry).filter(SourceRegistry.source_id == target.strip()).first()
            if not src:
                return "failed", {"error": "source_not_found"}
            if section_code and (src.section_code or "").strip() != section_code:
                return "failed", {"error": "unauthorized_target_section"}
            src.is_active = False
            self.db.flush()
            return "executed", {"source_id": src.source_id, "is_active": False}

        if t in {"isolate_host", "block_ip"}:
            status, wh_details = dispatch_containment_action(
                db           = self.db,
                action_type  = t,
                target       = target,
                section_code = section_code,
            )
            # Map webhook statuses to containment action statuses:
            # "delivered" → "executed" (partner confirmed receipt)
            # "no_webhook" → "executed" (recorded; partner must poll)
            # "failed"    → "failed"
            exec_status = "executed" if status in {"delivered", "no_webhook"} else "failed"
            return exec_status, {"webhook_status": status, **wh_details}

        if t == "rollback_block_ip":
            original = self._latest_executed_block_ip_action(section_code=section_code, target=target)
            if not original:
                return "failed", {"error": "no_block_ip_action_found"}

            default_window = max(5, int(settings.defense_rollback_window_minutes))
            requested_window = int(details.get("rollback_window_minutes") or default_window)
            rollback_window_minutes = max(5, min(default_window, requested_window))
            age_minutes = (_now() - (original.executed_at or _now())).total_seconds() / 60.0
            if age_minutes > rollback_window_minutes:
                return "failed", {
                    "error": "rollback_window_expired",
                    "rollback_window_minutes": rollback_window_minutes,
                    "age_minutes": round(age_minutes, 3),
                }

            rollback_of_action_id = str(original.id)
            if self._rollback_already_executed(
                section_code=section_code,
                target=target,
                rollback_of_action_id=rollback_of_action_id,
            ):
                return "failed", {
                    "error": "already_rolled_back",
                    "rollback_of_action_id": rollback_of_action_id,
                }

            status, wh_details = dispatch_containment_action(
                db=self.db,
                action_type="unblock_ip",
                target=target,
                section_code=section_code,
            )
            exec_status = "executed" if status in {"delivered", "no_webhook"} else "failed"
            return exec_status, {
                "webhook_status": status,
                "requested_action": "rollback_block_ip",
                "dispatched_action": "unblock_ip",
                "rollback_of_action_id": rollback_of_action_id,
                "rollback_window_minutes": rollback_window_minutes,
                **wh_details,
            }

        return "failed", {"error": "unsupported_action_type"}

    def list_threat_alerts(
        self,
        *,
        principal: Any,
        section_code: str | None,
        alert_type: str | None,
        severity: str | None,
        limit: int,
        offset: int,
    ) -> Dict[str, Any]:
        sec = self._effective_section(principal, section_code)
        q = self.db.query(ThreatAlert)
        if sec:
            q = q.filter(ThreatAlert.section_code == sec)
        if alert_type:
            q = q.filter(ThreatAlert.alert_type == alert_type)
        if severity:
            q = q.filter(ThreatAlert.severity == severity)
        total = q.count()
        rows = q.order_by(ThreatAlert.window_end.desc(), ThreatAlert.score.desc()).offset(offset).limit(limit).all()
        return {
            "total": total,
            "items": [self._alert_to_dict(x) for x in rows],
        }

    def refresh_threat_alerts(self, *, payload: ThreatAlertRefreshRequest, principal: Any) -> Dict[str, Any]:
        out = run_threat_pattern_once(
            db=self.db,
            minutes=payload.minutes,
            section_code=self._principal_section(principal),
        )
        self.ledger.audit(
            actor_type="analyst",
            actor_id=str(getattr(principal, "actor_id", "api")),
            action="defense.threat_alert.refresh",
            target=f"minutes:{payload.minutes}",
            section_code=self._principal_section(principal),
        )
        return out

    def current_crypto_posture(self) -> Dict[str, Any]:
        tls_mode = settings.crypto_tls_mode
        pqc_mode = settings.crypto_pqc_mode
        kms_provider = settings.crypto_kms_provider
        signing_alg = "HMAC-SHA3-512"
        password_kdf = "PBKDF2-HMAC-SHA3-512"
        key_rotation_days = int(settings.crypto_key_rotation_days)

        compliant = bool(
            tls_mode in {"tls1.3", "hybrid"}
            and pqc_mode in {"hybrid", "required"}
            and key_rotation_days <= 180
        )
        return {
            "tls_mode": tls_mode,
            "pqc_mode": pqc_mode,
            "kms_provider": kms_provider,
            "signing_alg": signing_alg,
            "password_kdf": password_kdf,
            "key_rotation_days": key_rotation_days,
            "compliant": compliant,
            "generated_at": _now().isoformat(),
        }

    def snapshot_crypto_posture(self, *, payload: CryptoSnapshotRequest, principal: Any) -> Dict[str, Any]:
        current = self.current_crypto_posture()
        section_code = self._effective_section(principal, payload.section_code)
        row = CryptoPostureSnapshot(
            section_code=section_code,
            taken_by=str(getattr(principal, "actor_id", "api")),
            tls_mode=current["tls_mode"],
            pqc_mode=current["pqc_mode"],
            kms_provider=current["kms_provider"],
            signing_alg=current["signing_alg"],
            password_kdf=current["password_kdf"],
            key_rotation_days=current["key_rotation_days"],
            compliant=bool(current["compliant"]),
            details_json={
                **dict(payload.details or {}),
                "snapshot_generated_at": current["generated_at"],
            },
        )
        self.db.add(row)
        self.db.commit()
        self.ledger.audit(
            actor_type="analyst",
            actor_id=str(getattr(principal, "actor_id", "api")),
            action="defense.crypto_posture.snapshot",
            target=str(row.id),
            section_code=section_code,
        )
        return {
            "snapshot_id": str(row.id),
            "compliant": bool(row.compliant),
            "created_at": row.created_at.isoformat(),
        }

    @staticmethod
    def _vuln_to_dict(row: VulnerabilityFinding) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "section_code": row.section_code,
            "asset_id": row.asset_id,
            "cve_id": row.cve_id,
            "source": row.source,
            "severity": row.severity,
            "epss": row.epss,
            "kev": bool(row.kev),
            "status": row.status,
            "discovered_at": row.discovered_at.isoformat() if row.discovered_at else None,
            "due_at": row.due_at.isoformat() if row.due_at else None,
            "patched_at": row.patched_at.isoformat() if row.patched_at else None,
            "risk_score": row.risk_score,
            "metadata": row.metadata_json or {},
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    def _backup_to_dict(row: BackupAttestation) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "section_code": row.section_code,
            "asset_id": row.asset_id,
            "backup_id": row.backup_id,
            "immutable": bool(row.immutable),
            "object_lock_until": row.object_lock_until.isoformat() if row.object_lock_until else None,
            "backup_hash": row.backup_hash,
            "storage_tier": row.storage_tier,
            "status": row.status,
            "rpo_hours": row.rpo_hours,
            "attested_at": row.attested_at.isoformat() if row.attested_at else None,
            "evidence": row.evidence_json or {},
        }

    @staticmethod
    def _restore_to_dict(row: RestoreDrill) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "section_code": row.section_code,
            "asset_id": row.asset_id,
            "backup_id": row.backup_id,
            "success": bool(row.success),
            "rto_target_minutes": row.rto_target_minutes,
            "rto_actual_minutes": row.rto_actual_minutes,
            "operator_id": row.operator_id,
            "notes": row.notes,
            "evidence": row.evidence_json or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _run_to_dict(row: IncidentPlaybookRun) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "incident_key": row.incident_key,
            "section_code": row.section_code,
            "severity": row.severity,
            "status": row.status,
            "created_by": row.created_by,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "metadata": row.metadata_json or {},
        }

    @staticmethod
    def _alert_to_dict(row: ThreatAlert) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "alert_type": row.alert_type,
            "section_code": row.section_code,
            "entity_key": row.entity_key,
            "window_start": row.window_start.isoformat() if row.window_start else None,
            "window_end": row.window_end.isoformat() if row.window_end else None,
            "score": row.score,
            "severity": row.severity,
            "reason_codes": row.reason_codes or [],
            "indicators": row.indicators or {},
            "recommended_actions": row.recommended_actions or [],
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
