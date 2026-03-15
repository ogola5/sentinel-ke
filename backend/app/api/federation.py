"""
Sentinel-KE Federation API
===========================

Endpoints for the federated intelligence network.

Edge agents (running at banks / telcos / hospitals) POST their GNN
pattern batches here.  Analysts at the National Command Centre query
these endpoints to monitor all connected partners and detect
cross-organizational threats.

Endpoints
---------
POST /v1/federation/patterns
    Edge agent submits a batch of high-risk entity patterns.
    Auth: X-API-Key header (same mechanism as the main ingest pipeline).

GET  /v1/federation/partners
    List all registered partners with liveness status.
    Auth: section access required.

GET  /v1/federation/patterns
    Query pattern stream — filter by partner, time window, risk threshold.
    Auth: section access required.

GET  /v1/federation/correlations
    Cross-partner threat correlations: entities flagged by 2+ independent
    organisations in the same time window.
    Auth: section access required.

POST /v1/federation/register
    Register a new edge agent partner (admin: central access + write scope).
    Returns the API key to configure in the edge agent's .env.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_central_access, require_scope, require_section_access
from app.core.config import settings as hub_settings
from app.federation.models import FederationPartner, FederationPattern
from app.db.base import utcnow

router = APIRouter(prefix="/v1/federation", tags=["federation"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class EntityPattern(BaseModel):
    entity_key_hash: str = Field(..., description="HMAC-SHA256 of the entity key — never the raw key")
    entity_type: str = Field(..., description="ip / phone_h / account_h / domain / etc.")
    risk_score: float = Field(..., ge=0.0, le=1.0)
    uncertainty: float = Field(0.0, ge=0.0, le=1.0)
    fraud_family: Optional[str] = None
    chain_score: float = Field(0.0, ge=0.0, le=1.0)
    risk_flags: List[str] = Field(default_factory=list)


class PatternBatchSummary(BaseModel):
    total_entities_scored: int = 0
    high_risk_count: int = 0
    mean_risk_score: float = 0.0
    top_fraud_family: Optional[str] = None
    gnn_auc: Optional[float] = None


class PatternBatch(BaseModel):
    """Payload sent by an edge agent after each GNN run."""
    partner_id: str = Field(..., description="Edge agent partner ID, e.g. equity-bank-ke")
    schema_version: str = Field("1.0")
    window_start: datetime
    window_end: datetime
    gnn_model_version: Optional[str] = None
    high_risk_entities: List[EntityPattern] = Field(default_factory=list)
    summary: PatternBatchSummary = Field(default_factory=PatternBatchSummary)


class PartnerHeartbeat(BaseModel):
    partner_id: str = Field(..., description="Edge agent partner ID, e.g. equity-bank-ke")
    agent_version: Optional[str] = Field(None, description="Edge agent software version")
    model_version: Optional[str] = Field(None, description="Currently loaded model version on edge node")
    artifact: Dict[str, Any] = Field(default_factory=dict, description="Artifact metadata exposed by the edge agent")
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_publish_status: Optional[str] = None
    run_count: int = 0
    data_source: Optional[str] = None
    hub_reachable: Optional[bool] = None
    capabilities: List[str] = Field(default_factory=list)


class PartnerRegistration(BaseModel):
    partner_id: str = Field(..., min_length=3, max_length=64,
                            description="Short stable ID e.g. equity-bank-ke")
    partner_name: str = Field(..., description="Display name e.g. Equity Bank Kenya")
    partner_type: str = Field(..., description="bank | telco | hospital | government | other")
    # Optional last-mile webhook — partner's firewall/EDR endpoint that receives
    # signed block_ip / isolate_host actions from the national hub.
    webhook_url: Optional[str] = Field(None, description="Partner-side containment webhook URL")
    webhook_secret: Optional[str] = Field(None, description="Shared secret for HMAC-SHA256 webhook signature")
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Auth helper — verifies edge agent API key
# ---------------------------------------------------------------------------

async def _require_partner_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    x_signature: Optional[str] = Header(default=None, alias="X-Sentinel-Signature"),
    db: Session = Depends(get_db),
) -> FederationPartner:
    request_body = await request.body()
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    partner = (
        db.query(FederationPartner)
        .filter(FederationPartner.api_key_hash == key_hash,
                FederationPartner.is_active.is_(True))
        .first()
    )
    if not partner:
        raise HTTPException(status_code=403, detail="Unknown or inactive partner API key")

    # Verify HMAC-SHA256 body signature to prevent payload tampering
    if hub_settings.federation_require_signed_requests and not x_signature:
        raise HTTPException(status_code=401, detail="Missing X-Sentinel-Signature")

    if x_signature:
        expected = "sha256=" + hmac.new(
            x_api_key.encode(), request_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_signature):
            raise HTTPException(status_code=403, detail="Invalid request signature")

    return partner


# ---------------------------------------------------------------------------
# POST /v1/federation/patterns  — edge agent submits GNN patterns
# ---------------------------------------------------------------------------

_PARTNER_SUBMIT_WINDOW: Dict[str, list] = {}   # partner_id → [timestamp, ...]
_PARTNER_MAX_BATCHES_PER_HOUR = 60             # one batch per minute max per partner


def _check_partner_rate_limit(partner_id: str) -> None:
    """Sliding-window rate limiter: max 60 batches per partner per hour."""
    now = datetime.now(timezone.utc).timestamp()
    window = _PARTNER_SUBMIT_WINDOW.setdefault(partner_id, [])
    # evict entries older than 1 hour
    _PARTNER_SUBMIT_WINDOW[partner_id] = [t for t in window if now - t < 3600]
    if len(_PARTNER_SUBMIT_WINDOW[partner_id]) >= _PARTNER_MAX_BATCHES_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {_PARTNER_MAX_BATCHES_PER_HOUR} batches/hour per partner",
        )
    _PARTNER_SUBMIT_WINDOW[partner_id].append(now)


@router.post(
    "/patterns",
    summary="Submit GNN pattern batch from edge agent",
    description=(
        "Called automatically by the Sentinel-KE Edge Agent after each local GNN run. "
        "Accepts a batch of high-risk entity patterns (hashed keys only — no raw data). "
        "Auth: partner API key + HMAC-SHA256 request signature."
    ),
    status_code=202,
)
async def submit_patterns(
    batch: PatternBatch,
    partner: FederationPartner = Depends(_require_partner_api_key),
    db: Session = Depends(get_db),
) -> dict:
    _check_partner_rate_limit(partner.partner_id)
    if partner.partner_id != batch.partner_id:
        raise HTTPException(status_code=403,
                            detail="partner_id in payload does not match API key owner")

    now = utcnow()
    rows = []
    for ent in batch.high_risk_entities:
        rows.append(FederationPattern(
            partner_id        = partner.partner_id,
            received_at       = now,
            window_start      = batch.window_start,
            window_end        = batch.window_end,
            gnn_model_version = batch.gnn_model_version,
            entity_key_hash   = ent.entity_key_hash,
            entity_type       = ent.entity_type,
            risk_score        = ent.risk_score,
            uncertainty       = ent.uncertainty,
            fraud_family      = ent.fraud_family,
            chain_score       = ent.chain_score,
            risk_flags        = list(ent.risk_flags),
            summary_json      = batch.summary.model_dump(),
            schema_version    = batch.schema_version,
        ))

    if rows:
        db.bulk_save_objects(rows)

    # Update partner liveness
    partner.last_seen       = now
    partner.last_pattern_at = now
    partner.total_patterns  = (partner.total_patterns or 0) + len(rows)
    db.commit()

    return {
        "accepted": len(rows),
        "partner_id": partner.partner_id,
        "received_at": now.isoformat(),
    }


@router.post(
    "/heartbeat",
    summary="Receive edge-agent liveness + version heartbeat",
    description=(
        "Edge agents send this lightweight heartbeat on startup and after runs so the hub can display "
        "freshness, agent version, model version, and artifact status even when no new patterns were published."
    ),
    status_code=202,
)
async def receive_heartbeat(
    heartbeat: PartnerHeartbeat,
    partner: FederationPartner = Depends(_require_partner_api_key),
    db: Session = Depends(get_db),
) -> dict:
    if partner.partner_id != heartbeat.partner_id:
        raise HTTPException(status_code=403, detail="partner_id in heartbeat does not match API key owner")

    now = utcnow()
    metadata = dict(partner.metadata_json or {})
    edge_status = dict(metadata.get("edge_status") or {})
    edge_status.update(
        {
            "last_heartbeat_at": now.isoformat(),
            "agent_version": heartbeat.agent_version,
            "model_version": heartbeat.model_version,
            "artifact": dict(heartbeat.artifact or {}),
            "last_run_at": heartbeat.last_run_at.isoformat() if heartbeat.last_run_at else None,
            "last_run_status": heartbeat.last_run_status,
            "last_publish_status": heartbeat.last_publish_status,
            "run_count": int(heartbeat.run_count or 0),
            "data_source": heartbeat.data_source,
            "hub_reachable": heartbeat.hub_reachable,
            "capabilities": list(heartbeat.capabilities or []),
        }
    )
    metadata["edge_status"] = edge_status
    partner.metadata_json = metadata
    partner.last_seen = now
    db.commit()

    return {
        "accepted": True,
        "partner_id": partner.partner_id,
        "received_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /v1/federation/partners  — list all partners
# ---------------------------------------------------------------------------

@router.get(
    "/partners",
    summary="List registered edge-agent partners",
    dependencies=[Depends(require_section_access)],
)
def list_partners(db: Session = Depends(get_db)) -> List[dict]:
    partners = db.query(FederationPartner).order_by(
        FederationPartner.last_seen.desc().nulls_last()
    ).all()

    now = utcnow()
    result = []
    for p in partners:
        age_sec = None
        status = "never_connected"
        if p.last_seen:
            age_sec = round((now - p.last_seen.replace(tzinfo=timezone.utc)
                             if p.last_seen.tzinfo is None
                             else now - p.last_seen).total_seconds())
            status = "online" if age_sec < 300 else ("stale" if age_sec < 3600 else "offline")

        metadata = dict(p.metadata_json or {})
        edge_status = dict(metadata.get("edge_status") or {})
        result.append({
            "partner_id":       p.partner_id,
            "partner_name":     p.partner_name,
            "partner_type":     p.partner_type,
            "status":           status,
            "last_seen_sec_ago": age_sec,
            "last_pattern_at":  p.last_pattern_at.isoformat() if p.last_pattern_at else None,
            "total_patterns":   p.total_patterns,
            "is_active":        p.is_active,
            "registered_at":    p.registered_at.isoformat() if p.registered_at else None,
            "metadata":         metadata,
            "last_heartbeat_at": edge_status.get("last_heartbeat_at"),
            "agent_version":   edge_status.get("agent_version"),
            "model_version":   edge_status.get("model_version"),
            "data_source":     edge_status.get("data_source"),
            "hub_reachable":   edge_status.get("hub_reachable"),
            "capabilities":    list(edge_status.get("capabilities") or []),
            "last_run_status": edge_status.get("last_run_status"),
            "last_publish_status": edge_status.get("last_publish_status"),
            "run_count":       edge_status.get("run_count"),
        })
    return result


# ---------------------------------------------------------------------------
# GET /v1/federation/patterns  — query pattern stream
# ---------------------------------------------------------------------------

@router.get(
    "/stream",
    summary="Query federation pattern stream",
    dependencies=[Depends(require_section_access)],
)
def query_patterns(
    partner_id:    Optional[str]   = Query(None,  description="Filter by partner"),
    min_risk:      float           = Query(0.7,   description="Minimum risk score"),
    hours:         int             = Query(1,     description="Look-back window in hours"),
    fraud_family:  Optional[str]   = Query(None,  description="Filter by fraud family"),
    limit:         int             = Query(100,   le=500),
    db: Session = Depends(get_db),
) -> List[dict]:
    since = utcnow() - timedelta(hours=max(1, min(hours, 168)))
    q = (
        db.query(FederationPattern)
        .filter(FederationPattern.received_at >= since)
        .filter(FederationPattern.risk_score >= min_risk)
    )
    if partner_id:
        q = q.filter(FederationPattern.partner_id == partner_id)
    if fraud_family:
        q = q.filter(FederationPattern.fraud_family == fraud_family)

    rows = q.order_by(FederationPattern.risk_score.desc()).limit(limit).all()

    return [
        {
            "id":               str(r.id),
            "partner_id":       r.partner_id,
            "received_at":      r.received_at.isoformat(),
            "window_start":     r.window_start.isoformat() if r.window_start else None,
            "window_end":       r.window_end.isoformat()   if r.window_end   else None,
            "entity_key_hash":  r.entity_key_hash,
            "entity_type":      r.entity_type,
            "risk_score":       round(r.risk_score, 4),
            "uncertainty":      round(r.uncertainty, 4),
            "fraud_family":     r.fraud_family,
            "chain_score":      round(r.chain_score, 4),
            "risk_flags":       list(r.risk_flags or []),
            "gnn_model_version": r.gnn_model_version,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# GET /v1/federation/correlations  — cross-partner threat correlations
# ---------------------------------------------------------------------------

@router.get(
    "/correlations",
    summary="Cross-partner threat correlations",
    description=(
        "Returns entities flagged as high-risk by 2 or more independent partner organisations "
        "within the same time window. A signal confirmed by multiple independent GNN runs "
        "is near-certain evidence of a real cross-organizational attack.\n\n"
        "Example: Equity Bank's GNN flags phone_h:abc123 at 14:30, "
        "Safaricom's GNN flags the same hash at 14:32 → coordinated SIM-swap + mule attack."
    ),
    dependencies=[Depends(require_section_access)],
)
def cross_partner_correlations(
    hours:     int   = Query(1,   description="Look-back window in hours"),
    min_risk:  float = Query(0.7, description="Minimum risk score per signal"),
    min_partners: int = Query(2,  description="Minimum number of partners that must confirm"),
    limit:     int   = Query(50,  le=200),
    db: Session = Depends(get_db),
) -> dict:
    since = utcnow() - timedelta(hours=max(1, min(hours, 168)))

    rows = db.execute(
        text("""
            SELECT
                entity_key_hash,
                entity_type,
                array_agg(DISTINCT partner_id ORDER BY partner_id) AS seen_in_partners,
                count(DISTINCT partner_id)                          AS partner_count,
                max(risk_score)                                     AS max_risk,
                avg(risk_score)                                     AS avg_risk,
                array_agg(DISTINCT fraud_family)
                    FILTER (WHERE fraud_family IS NOT NULL)         AS fraud_families,
                array_agg(DISTINCT unnested_flag)
                    FILTER (WHERE unnested_flag IS NOT NULL)        AS all_risk_flags,
                max(chain_score)                                    AS max_chain_score,
                max(received_at)                                    AS last_seen,
                count(*)                                            AS total_signals
            FROM federation_pattern
            CROSS JOIN LATERAL unnest(risk_flags) AS t(unnested_flag)
            WHERE received_at >= :since
              AND risk_score   >= :min_risk
            GROUP BY entity_key_hash, entity_type
            HAVING count(DISTINCT partner_id) >= :min_partners
            ORDER BY partner_count DESC, max_risk DESC
            LIMIT :lim
        """),
        {
            "since":        since,
            "min_risk":     min_risk,
            "min_partners": max(1, int(min_partners)),
            "lim":          limit,
        },
    ).fetchall()

    correlations = [
        {
            "entity_key_hash":  r[0],
            "entity_type":      r[1],
            "seen_in_partners": list(r[2] or []),
            "partner_count":    int(r[3] or 0),
            "max_risk":         round(float(r[4] or 0), 4),
            "avg_risk":         round(float(r[5] or 0), 4),
            "fraud_families":   list(r[6] or []),
            "all_risk_flags":   list(r[7] or []),
            "max_chain_score":  round(float(r[8] or 0), 4),
            "last_seen":        r[9].isoformat() if r[9] else None,
            "total_signals":    int(r[10] or 0),
            "threat_level": (
                "CRITICAL" if int(r[3] or 0) >= 4 else
                "HIGH"     if int(r[3] or 0) >= 3 else
                "MEDIUM"
            ),
        }
        for r in rows
    ]

    return {
        "window_hours":   hours,
        "min_risk":       min_risk,
        "min_partners":   min_partners,
        "correlations":   correlations,
        "total_found":    len(correlations),
        "queried_at":     utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /v1/federation/register  — register a new edge agent partner (admin)
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    summary="Register a new edge-agent partner (admin)",
    dependencies=[
        Depends(require_central_access),
        Depends(require_scope("integrations.write")),
    ],
    status_code=201,
)
def register_partner(
    reg: PartnerRegistration,
    db: Session = Depends(get_db),
) -> dict:
    existing = db.query(FederationPartner).filter(
        FederationPartner.partner_id == reg.partner_id
    ).first()
    if existing:
        raise HTTPException(status_code=409,
                            detail=f"Partner '{reg.partner_id}' already registered")

    raw_key  = secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    # The national correlation salt is the SAME for every partner so that
    # HMAC(entity_key, correlation_salt) matches across organisations.
    correlation_salt = hub_settings.federation_correlation_salt

    webhook_secret_hash = None
    if reg.webhook_secret:
        webhook_secret_hash = hashlib.sha256(reg.webhook_secret.encode()).hexdigest()

    partner = FederationPartner(
        partner_id          = reg.partner_id,
        partner_name        = reg.partner_name,
        partner_type        = reg.partner_type,
        api_key_hash        = key_hash,
        correlation_salt    = correlation_salt,
        webhook_url         = reg.webhook_url,
        webhook_secret_hash = webhook_secret_hash,
        metadata_json       = reg.metadata,
    )
    db.add(partner)
    db.commit()

    return {
        "partner_id":         reg.partner_id,
        "partner_name":       reg.partner_name,
        "partner_type":       reg.partner_type,
        "api_key":            raw_key,   # returned ONCE — store securely
        "correlation_salt":   correlation_salt,  # use as NATIONAL_SALT in edge agent .env
        "warning":            "Store api_key and correlation_salt securely. Neither can be retrieved again.",
        "webhook_registered": reg.webhook_url is not None,
        "edge_agent_env": {
            "PARTNER_ID":           reg.partner_id,
            "PARTNER_NAME":         reg.partner_name,
            "HUB_URL":              hub_settings.edge_hub_url or "https://<set-HUB_URL-in-env>",
            "HUB_API_KEY":          raw_key,
            "NATIONAL_SALT":        correlation_salt,
            "HMAC_SALT":            "CHANGE_ME_PER_PARTNER",
            "DATA_SOURCE":          "demo",
            "RUN_INTERVAL_S":       "300",
            "RETRAIN_EVERY":        "12",
        },
    }


# ---------------------------------------------------------------------------
# GET /v1/federation/edge-status  — edge sync agent health (edge nodes only)
# ---------------------------------------------------------------------------

@router.get(
    "/edge-status",
    summary="Edge sync agent health — reads local sync state file",
    dependencies=[Depends(require_section_access)],
)
def edge_sync_status() -> dict:
    """
    Returns the local edge sync agent's last push time, total pushed,
    and last error (if any).  Only meaningful when running on an edge node.
    Returns is_edge_node=false on the central hub.
    """
    import json as _json
    from pathlib import Path as _Path

    if not hub_settings.is_edge_node:
        return {
            "is_edge_node": False,
            "message": "This instance is the central hub, not an edge station.",
        }

    state_file = _Path(hub_settings.gnn_artifact_dir).parent / "edge_sync_state.json"
    if not state_file.exists():
        return {
            "is_edge_node": True,
            "partner_id": hub_settings.edge_partner_id,
            "status": "never_synced",
            "last_synced_at": None,
            "total_pushed": 0,
            "last_error": None,
        }

    try:
        state = _json.loads(state_file.read_text())
    except Exception as exc:
        return {"is_edge_node": True, "status": "state_file_corrupt", "error": str(exc)}

    last_synced = state.get("last_synced_at")
    age_sec = None
    status = "unknown"
    if last_synced:
        try:
            last_dt = datetime.fromisoformat(last_synced)
            age_sec = round((datetime.now(timezone.utc) - last_dt).total_seconds())
            status = "healthy" if age_sec < 300 else ("stale" if age_sec < 900 else "lagging")
        except Exception:
            status = "parse_error"

    return {
        "is_edge_node": True,
        "partner_id": hub_settings.edge_partner_id,
        "hub_url": hub_settings.edge_hub_url,
        "status": status,
        "last_synced_at": last_synced,
        "age_seconds": age_sec,
        "total_pushed": state.get("total_pushed", 0),
        "last_error": state.get("last_error"),
    }
