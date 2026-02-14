from __future__ import annotations

import fnmatch
import ipaddress
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Sequence, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.cases.builders import build_case_packet
from app.core.security import compute_event_hash, hmac_verify, sha256_hex, stable_json_dumps
from app.ledger.models import AuditLog
from app.ledger.repository import LedgerRepository
from app.legal.anchoring import LegalEvidenceAnchoringService
from app.legal.models import LegalAuthorizationGrant, LegalEvidenceBundle, LegalOrder
from app.legal.schemas import (
    ApprovalPayloadRequest,
    LegalAuthorizationRequest,
    LegalEvidenceExportRequest,
    LegalOrderCreate,
    LegalOrderRevoke,
    LegalScanPlanRequest,
    ScanCandidate,
)
from app.stix.exporter import build_stix_bundle_from_case


@dataclass(frozen=True)
class AuthorizationDecision:
    status: str
    reason_codes: List[str]
    valid_from: datetime
    valid_until: datetime
    approval_digest: str


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _norm_str_list(values: Sequence[str] | None) -> List[str]:
    if not values:
        return []
    out = []
    seen = set()
    for item in values:
        s = str(item).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _match_action(action: str, allowed_actions: Sequence[str]) -> bool:
    if not allowed_actions:
        return False
    action = action.strip().lower()
    for rule in allowed_actions:
        r = str(rule).strip().lower()
        if not r:
            continue
        if r == "*" or fnmatch.fnmatch(action, r):
            return True
    return False


def _target_to_ip(target: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    t = target.strip()
    try:
        return ipaddress.ip_address(t)
    except ValueError:
        return None


def _match_target(target: str, allowed_targets: Sequence[str]) -> bool:
    if not allowed_targets:
        return False
    t = target.strip()
    t_ip = _target_to_ip(t)
    for rule in allowed_targets:
        r = str(rule).strip()
        if not r:
            continue
        if r == "*" or fnmatch.fnmatch(t, r):
            return True

        # CIDR scope support for direct IP targets.
        try:
            net = ipaddress.ip_network(r, strict=False)
            if t_ip and t_ip in net:
                return True
        except ValueError:
            pass
    return False


def _compute_token_material(material: Dict[str, Any]) -> str:
    # Reuse deterministic SHA256 helper to mint opaque execution tokens.
    return compute_event_hash(material)


def _load_approver_secrets() -> Dict[str, str]:
    """
    LEGAL_APPROVER_SECRETS format:
    - "approverA=secretA,approverB=secretB" OR "approverA:secretA,approverB:secretB"
    """
    raw = os.getenv("LEGAL_APPROVER_SECRETS", "").strip()
    if not raw:
        return {}
    out: Dict[str, str] = {}
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue
        if "=" in item:
            k, v = item.split("=", 1)
        elif ":" in item:
            k, v = item.split(":", 1)
        else:
            continue
        k = k.strip()
        v = v.strip()
        if k and v:
            out[k] = v
    return out


def build_approval_message(req: ApprovalPayloadRequest | LegalAuthorizationRequest) -> Tuple[str, str]:
    material = {
        "order_id": req.order_id,
        "action_type": req.action_type,
        "target": req.target,
        "requested_by": req.requested_by,
        "requested_minutes": req.requested_minutes,
    }
    msg = stable_json_dumps(material)
    digest = sha256_hex(msg.encode("utf-8"))
    return msg, digest


class LegalAuthorizationService:
    def __init__(self, db: Session):
        self.db = db
        self.ledger = LedgerRepository(db)
        self.anchor = LegalEvidenceAnchoringService(db)

    def create_order(self, payload: LegalOrderCreate) -> Dict[str, Any]:
        issued_at = payload.issued_at or _now_utc()
        order_id = str(uuid.uuid4())

        row = LegalOrder(
            order_id=order_id,
            order_number=payload.order_number.strip(),
            court_name=payload.court_name.strip(),
            case_reference=payload.case_reference,
            purpose=payload.purpose.strip(),
            authorized_by=payload.authorized_by.strip(),
            issued_at=issued_at,
            valid_from=payload.valid_from,
            valid_until=payload.valid_until,
            status="active",
            allowed_actions_json=_norm_str_list(payload.allowed_actions),
            allowed_targets_json=_norm_str_list(payload.allowed_targets),
            constraints_json=payload.constraints or {},
            metadata_json=payload.metadata or {},
            created_by=payload.created_by.strip(),
        )
        self.db.add(row)
        self.db.commit()

        self.ledger.audit(
            actor_type="analyst",
            actor_id=payload.created_by,
            action="legal_order.created",
            target=order_id,
        )
        return self._order_to_dict(row)

    def revoke_order(self, order_id: str, payload: LegalOrderRevoke) -> Dict[str, Any]:
        row = self.db.get(LegalOrder, order_id)
        if not row:
            raise ValueError("legal_order_not_found")

        row.status = "revoked"
        row.revoked_by = payload.revoked_by
        row.revoked_reason = payload.reason
        row.revoked_at = _now_utc()
        self.db.commit()

        self.ledger.audit(
            actor_type="analyst",
            actor_id=payload.revoked_by,
            action="legal_order.revoked",
            target=order_id,
        )
        return self._order_to_dict(row)

    def authorize(self, payload: LegalAuthorizationRequest) -> Dict[str, Any]:
        order = self.db.get(LegalOrder, payload.order_id)
        if not order:
            raise ValueError("legal_order_not_found")

        decision = self._evaluate(order=order, req=payload)
        grant_id = str(uuid.uuid4())
        token = _compute_token_material(
            {
                "grant_id": grant_id,
                "order_id": payload.order_id,
                "action_type": payload.action_type,
                "target": payload.target,
                "valid_until": decision.valid_until.isoformat(),
            }
        )

        row = LegalAuthorizationGrant(
            grant_id=grant_id,
            order_id=payload.order_id,
            action_type=payload.action_type,
            target=payload.target,
            requested_by=payload.requested_by,
            approved_by_json=_norm_str_list(payload.approved_by),
            justification=payload.justification,
            status=decision.status,
            reason_codes_json=decision.reason_codes,
            evidence_json={
                **(payload.evidence or {}),
                "approval_digest": decision.approval_digest,
                "approved_by": _norm_str_list(payload.approved_by),
            },
            valid_from=decision.valid_from,
            valid_until=decision.valid_until,
            execution_token=token,
        )
        self.db.add(row)
        self.db.commit()

        self.ledger.audit(
            actor_type="analyst",
            actor_id=payload.requested_by,
            action=f"legal_authorization.{decision.status}",
            target=grant_id,
        )

        return self._grant_to_dict(row)

    def verify_grant_token(
        self,
        *,
        execution_token: str,
        action_type: str,
        target: str,
        mark_used: bool = False,
        actor_id: str = "system",
    ) -> Dict[str, Any]:
        grant = (
            self.db.query(LegalAuthorizationGrant)
            .filter(LegalAuthorizationGrant.execution_token == execution_token)
            .first()
        )
        if not grant:
            raise ValueError("grant_token_not_found")

        order = self.db.get(LegalOrder, grant.order_id)
        if not order:
            raise ValueError("legal_order_not_found")

        now = _now_utc()
        if order.status != "active":
            raise ValueError("order_not_active")
        if now < order.valid_from or now > order.valid_until:
            if grant.status == "allow":
                grant.status = "expired"
                self.db.commit()
            raise ValueError("outside_order_window")
        if grant.status not in {"allow", "used"}:
            raise ValueError("grant_not_allowed")
        if now < grant.valid_from or now > grant.valid_until:
            if grant.status == "allow":
                grant.status = "expired"
                self.db.commit()
            raise ValueError("grant_expired")
        if not _match_action(action_type, [grant.action_type]):
            raise ValueError("grant_action_mismatch")
        if not _match_target(target, [grant.target]):
            raise ValueError("grant_target_mismatch")

        single_use = bool((order.constraints_json or {}).get("single_use_token", False))
        if mark_used or single_use:
            if grant.used_at is not None:
                raise ValueError("grant_token_already_used")
            grant.used_at = now
            grant.status = "used"
            self.db.commit()

        self.ledger.audit(
            actor_type="service",
            actor_id=actor_id,
            action="legal_grant.verified",
            target=grant.grant_id,
        )
        return {
            "grant_id": grant.grant_id,
            "order_id": grant.order_id,
            "status": grant.status,
            "action_type": grant.action_type,
            "target": grant.target,
            "valid_until": grant.valid_until.isoformat(),
        }

    def build_greedy_scan_plan(self, payload: LegalScanPlanRequest) -> Dict[str, Any]:
        order = self.db.get(LegalOrder, payload.order_id)
        if not order:
            raise ValueError("legal_order_not_found")
        now = _now_utc()
        if order.status != "active":
            raise ValueError("order_not_active")
        if now < order.valid_from or now > order.valid_until:
            raise ValueError("outside_order_window")

        if not _match_action(payload.action_type, order.allowed_actions_json or []):
            raise ValueError("action_not_permitted_by_order")

        selected, skipped, used_budget, total_utility = greedy_select_candidates(
            candidates=payload.candidates,
            max_budget=payload.max_budget,
            allowed_targets=order.allowed_targets_json or [],
        )

        self.ledger.audit(
            actor_type="analyst",
            actor_id=payload.requested_by,
            action="legal_scan_plan.generated",
            target=payload.order_id,
        )

        return {
            "order_id": payload.order_id,
            "action_type": payload.action_type,
            "max_budget": payload.max_budget,
            "used_budget": round(used_budget, 4),
            "total_expected_risk_reduction": round(total_utility, 6),
            "selected_targets": selected,
            "skipped_targets": skipped,
        }

    def export_evidence_bundle(self, payload: LegalEvidenceExportRequest) -> Dict[str, Any]:
        order = self.db.get(LegalOrder, payload.order_id)
        if not order:
            raise ValueError("legal_order_not_found")

        campaign_uuid = UUID(payload.campaign_id)
        case_packet = build_case_packet(campaign_id=campaign_uuid, db=self.db)
        stix_bundle = (
            build_stix_bundle_from_case(db=self.db, campaign_id=campaign_uuid)
            if payload.include_stix
            else None
        )

        grants_q = self.db.query(LegalAuthorizationGrant).filter(
            LegalAuthorizationGrant.order_id == payload.order_id
        )
        selected_grant_ids = _norm_str_list(payload.grant_ids)
        if selected_grant_ids:
            grants_q = grants_q.filter(LegalAuthorizationGrant.grant_id.in_(selected_grant_ids))
        grants = grants_q.order_by(LegalAuthorizationGrant.created_at.asc()).all()

        audit_targets = [payload.order_id] + [g.grant_id for g in grants]
        audits = (
            self.db.query(AuditLog)
            .filter(AuditLog.target.in_(audit_targets))
            .order_by(AuditLog.at.asc())
            .limit(1000)
            .all()
        )
        audit_chain = [
            {
                "id": x.id,
                "actor_type": x.actor_type,
                "actor_id": x.actor_id,
                "action": x.action,
                "target": x.target,
                "at": x.at.isoformat(),
            }
            for x in audits
        ]

        generated_at = _now_utc()
        bundle_payload = {
            "bundle_type": "court_case_legal_chain_v1",
            "generated_at": generated_at.isoformat(),
            "notes": payload.notes,
            "campaign_id": payload.campaign_id,
            "case_packet": case_packet,
            "stix_bundle": stix_bundle,
            "legal_order": self._order_to_dict(order),
            "authorization_chain": [self._grant_to_dict(g) for g in grants],
            "audit_chain": audit_chain,
        }
        root_hash = compute_event_hash(bundle_payload)

        prev = (
            self.db.query(LegalEvidenceBundle)
            .order_by(LegalEvidenceBundle.created_at.desc())
            .first()
        )
        prev_chain_hash = prev.chain_hash if prev else None
        chain_hash = compute_event_hash(
            {
                "prev_chain_hash": prev_chain_hash or "",
                "root_hash": root_hash,
                "created_at": generated_at.isoformat(),
            }
        )

        row = LegalEvidenceBundle(
            bundle_id=str(uuid.uuid4()),
            export_type="court_case_legal_chain_v1",
            campaign_id=payload.campaign_id,
            order_id=payload.order_id,
            root_hash=root_hash,
            prev_chain_hash=prev_chain_hash,
            chain_hash=chain_hash,
            payload_json=bundle_payload,
            created_by=payload.exported_by,
            created_at=generated_at,
        )
        self.db.add(row)
        self.db.commit()

        self.ledger.audit(
            actor_type="analyst",
            actor_id=payload.exported_by,
            action="legal_evidence_bundle.exported",
            target=row.bundle_id,
        )

        anchor = self.anchor.anchor_bundle(bundle=row)
        self.ledger.audit(
            actor_type="analyst",
            actor_id=payload.exported_by,
            action=f"legal_evidence_anchor.{anchor.get('anchor_status', 'unknown')}",
            target=row.bundle_id,
        )
        return self._evidence_bundle_to_dict(row, include_payload=True, anchor=anchor)

    def list_orders(self, *, status: str | None, limit: int, offset: int) -> Dict[str, Any]:
        q = self.db.query(LegalOrder)
        if status:
            q = q.filter(LegalOrder.status == status)
        rows = q.order_by(LegalOrder.created_at.desc()).offset(offset).limit(limit).all()
        return {"limit": limit, "offset": offset, "items": [self._order_to_dict(x) for x in rows]}

    def list_grants(self, *, status: str | None, limit: int, offset: int) -> Dict[str, Any]:
        q = self.db.query(LegalAuthorizationGrant)
        if status:
            q = q.filter(LegalAuthorizationGrant.status == status)
        rows = q.order_by(LegalAuthorizationGrant.created_at.desc()).offset(offset).limit(limit).all()
        return {"limit": limit, "offset": offset, "items": [self._grant_to_dict(x) for x in rows]}

    def list_evidence_bundles(self, *, limit: int, offset: int) -> Dict[str, Any]:
        rows = (
            self.db.query(LegalEvidenceBundle)
            .order_by(LegalEvidenceBundle.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        items: List[Dict[str, Any]] = []
        for x in rows:
            anchor = None
            try:
                anchor = self.anchor.get_anchor(bundle_id=x.bundle_id)
            except ValueError:
                anchor = None
            items.append(self._evidence_bundle_to_dict(x, anchor=anchor))
        return {"limit": limit, "offset": offset, "items": items}

    def get_evidence_bundle(self, bundle_id: str) -> Dict[str, Any]:
        row = self.db.get(LegalEvidenceBundle, bundle_id)
        if not row:
            raise ValueError("legal_evidence_bundle_not_found")
        anchor = None
        try:
            anchor = self.anchor.get_anchor(bundle_id=bundle_id)
        except ValueError:
            anchor = None
        return self._evidence_bundle_to_dict(row, include_payload=True, anchor=anchor)

    def get_evidence_anchor(self, bundle_id: str) -> Dict[str, Any]:
        row = self.db.get(LegalEvidenceBundle, bundle_id)
        if not row:
            raise ValueError("legal_evidence_bundle_not_found")
        return self.anchor.get_anchor(bundle_id=bundle_id)

    def refresh_evidence_anchor(self, *, bundle_id: str, actor_id: str = "api") -> Dict[str, Any]:
        row = self.db.get(LegalEvidenceBundle, bundle_id)
        if not row:
            raise ValueError("legal_evidence_bundle_not_found")
        anchor = self.anchor.anchor_bundle(bundle=row, force=True)
        self.ledger.audit(
            actor_type="service",
            actor_id=actor_id,
            action=f"legal_evidence_anchor.refresh.{anchor.get('anchor_status', 'unknown')}",
            target=bundle_id,
        )
        return anchor

    def _evaluate(self, *, order: LegalOrder, req: LegalAuthorizationRequest) -> AuthorizationDecision:
        now = _now_utc()
        reasons: List[str] = []

        # Update stale active orders automatically if out of window.
        if order.status == "active" and order.valid_until < now:
            order.status = "expired"
            self.db.commit()

        if order.status != "active":
            reasons.append("order_not_active")
        if now < order.valid_from or now > order.valid_until:
            reasons.append("outside_order_window")
        if not _match_action(req.action_type, order.allowed_actions_json or []):
            reasons.append("action_not_allowed")
        if not _match_target(req.target, order.allowed_targets_json or []):
            reasons.append("target_not_in_scope")

        constraints = order.constraints_json or {}
        requires_dual = bool(constraints.get("requires_dual_approval", True))
        min_approvers = int(constraints.get("min_approvers", 2 if requires_dual else 1))
        min_approvers = max(1, min_approvers)
        approvers = _norm_str_list(req.approved_by)
        if len(approvers) < min_approvers:
            reasons.append("insufficient_approvers")

        approval_message, approval_digest = build_approval_message(req)
        requires_crypto = bool(constraints.get("requires_crypto_approval", True))
        if requires_crypto:
            sig_map = {s.approver_id.strip(): s.signature_hex.strip() for s in (req.approval_signatures or [])}
            secrets = _load_approver_secrets()
            signed_material = approval_message.encode("utf-8")
            for approver_id in approvers:
                signature = sig_map.get(approver_id)
                if not signature:
                    reasons.append(f"missing_signature:{approver_id}")
                    continue
                secret = secrets.get(approver_id)
                if not secret:
                    reasons.append(f"secret_not_configured:{approver_id}")
                    continue
                if not hmac_verify(secret=secret, message=signed_material, signature_hex=signature):
                    reasons.append(f"invalid_signature:{approver_id}")

        max_grant_minutes = int(constraints.get("max_grant_minutes", 60))
        ttl_minutes = min(max_grant_minutes, req.requested_minutes)
        valid_until = min(order.valid_until, now + timedelta(minutes=ttl_minutes))

        status = "allow" if not reasons else "deny"
        return AuthorizationDecision(
            status=status,
            reason_codes=reasons or ["authorized"],
            valid_from=now,
            valid_until=valid_until,
            approval_digest=approval_digest,
        )

    @staticmethod
    def _order_to_dict(row: LegalOrder) -> Dict[str, Any]:
        return {
            "order_id": row.order_id,
            "order_number": row.order_number,
            "court_name": row.court_name,
            "case_reference": row.case_reference,
            "purpose": row.purpose,
            "authorized_by": row.authorized_by,
            "issued_at": row.issued_at.isoformat(),
            "valid_from": row.valid_from.isoformat(),
            "valid_until": row.valid_until.isoformat(),
            "status": row.status,
            "allowed_actions": row.allowed_actions_json or [],
            "allowed_targets": row.allowed_targets_json or [],
            "constraints": row.constraints_json or {},
            "metadata": row.metadata_json or {},
            "created_by": row.created_by,
            "revoked_by": row.revoked_by,
            "revoked_reason": row.revoked_reason,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    @staticmethod
    def _grant_to_dict(row: LegalAuthorizationGrant) -> Dict[str, Any]:
        return {
            "grant_id": row.grant_id,
            "order_id": row.order_id,
            "action_type": row.action_type,
            "target": row.target,
            "requested_by": row.requested_by,
            "approved_by": row.approved_by_json or [],
            "status": row.status,
            "reason_codes": row.reason_codes_json or [],
            "valid_from": row.valid_from.isoformat(),
            "valid_until": row.valid_until.isoformat(),
            "execution_token": row.execution_token,
            "evidence": row.evidence_json or {},
            "created_at": row.created_at.isoformat(),
        }

    @staticmethod
    def _evidence_bundle_to_dict(
        row: LegalEvidenceBundle,
        *,
        include_payload: bool = False,
        anchor: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        out = {
            "bundle_id": row.bundle_id,
            "export_type": row.export_type,
            "campaign_id": row.campaign_id,
            "order_id": row.order_id,
            "root_hash": row.root_hash,
            "prev_chain_hash": row.prev_chain_hash,
            "chain_hash": row.chain_hash,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat(),
        }
        if anchor is not None:
            out["anchor"] = anchor
        if include_payload:
            out["payload"] = row.payload_json or {}
        return out


def greedy_select_candidates(
    *,
    candidates: Sequence[ScanCandidate],
    max_budget: float,
    allowed_targets: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float, float]:
    """
    Defensive greedy planner:
    - filters out targets outside legal scope
    - ranks by utility/cost ratio
    - picks highest value items until budget is exhausted
    """
    scored: List[Tuple[float, ScanCandidate]] = []
    skipped: List[Dict[str, Any]] = []
    for c in candidates:
        if not _match_target(c.target, allowed_targets):
            skipped.append(
                {
                    "target": c.target,
                    "reason": "target_not_in_scope",
                    "estimated_cost": c.estimated_cost,
                }
            )
            continue
        utility = c.risk_score * c.criticality * c.intel_confidence
        ratio = utility / c.estimated_cost
        scored.append((ratio, c))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected: List[Dict[str, Any]] = []
    used_budget = 0.0
    total_utility = 0.0
    for ratio, c in scored:
        if used_budget + c.estimated_cost > max_budget:
            skipped.append(
                {
                    "target": c.target,
                    "reason": "budget_exceeded",
                    "estimated_cost": c.estimated_cost,
                    "ratio": round(ratio, 6),
                }
            )
            continue
        utility = c.risk_score * c.criticality * c.intel_confidence
        used_budget += c.estimated_cost
        total_utility += utility
        selected.append(
            {
                "target": c.target,
                "estimated_cost": c.estimated_cost,
                "risk_score": c.risk_score,
                "criticality": c.criticality,
                "intel_confidence": c.intel_confidence,
                "utility": round(utility, 6),
                "ratio": round(ratio, 6),
                "metadata": c.metadata,
            }
        )

    return selected, skipped, used_budget, total_utility
