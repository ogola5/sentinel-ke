/**
 * Executive Crisis Brief
 *
 * A single-page, plain-language situational awareness screen for
 * non-technical decision-makers (PS, CS, DG, Agency Director level).
 *
 * Design principles:
 *  - No technical jargon (no "GNN", "MC-Dropout", "entity_type", etc.)
 *  - Fits one screen — no scrolling required
 *  - Answers the only three questions that matter in a crisis:
 *      1. How bad is it right now?
 *      2. Which agencies are affected?
 *      3. What do we do next?
 */
import { useEffect, useState, useCallback } from "react";
import { RefreshCw, Loader, AlertTriangle, CheckCircle, Clock } from "lucide-react";
import { endpoints } from "../../api/endpoints";
import { apiFetchJson } from "../../api/client";
import { fetchFederationPartners } from "../../api/federation";
import { KENYA_AGENCIES, agencyName } from "../../types/auth";
import type { Principal } from "../../types/auth";
import type { FederationPartner } from "../../types/federation";

interface Props {
  principal: Principal;
}

// ── Threat level computation ───────────────────────────────────────────────

type ThreatLevel = "CRITICAL" | "HIGH" | "ELEVATED" | "NORMAL";

interface ThreatSummary {
  level: ThreatLevel;
  headline: string;
  detail: string;
  color: string;
}

function computeThreatLevel(
  highRiskCount: number,
  partnerAlerts: number,
  pendingActions: number,
): ThreatSummary {
  if (highRiskCount > 20 || partnerAlerts >= 3) {
    return {
      level: "CRITICAL",
      headline: "CRITICAL — Coordinated threat in progress",
      detail: "Multiple agencies reporting simultaneous activity. Immediate executive action required.",
      color: "#ff2d55",
    };
  }
  if (highRiskCount > 5 || partnerAlerts === 2) {
    return {
      level: "HIGH",
      headline: "HIGH — Significant threat detected",
      detail: "Elevated risk across monitored systems. Senior leadership should be briefed.",
      color: "#ff9f0a",
    };
  }
  if (highRiskCount > 0 || pendingActions > 0) {
    return {
      level: "ELEVATED",
      headline: "ELEVATED — Monitoring active threats",
      detail: "Some suspicious activity detected. Security teams are actively responding.",
      color: "#ffd60a",
    };
  }
  return {
    level: "NORMAL",
    headline: "NORMAL — Systems operating within expected parameters",
    detail: "No significant threats detected at this time. Routine monitoring continues.",
    color: "#30d158",
  };
}

// ── Plain-English action label ─────────────────────────────────────────────

function humanAction(actionType: string, status: string): string {
  const map: Record<string, string> = {
    block_ip:             "Block malicious network connection",
    isolate_host:         "Disconnect compromised computer from network",
    revoke_user:          "Suspend compromised user account",
    disable_source_key:   "Revoke data feed access",
    force_password_reset: "Force password change for affected accounts",
  };
  const label = map[actionType] ?? actionType.replace(/_/g, " ");
  const statusLabel =
    status === "queued"   ? "— awaiting approval" :
    status === "executed" ? "— completed"          :
    status === "failed"   ? "— FAILED, needs review" : "";
  return `${label} ${statusLabel}`.trim();
}

// ── Agency status ──────────────────────────────────────────────────────────

const ALL_AGENCY_CODES = Object.keys(KENYA_AGENCIES);

// ── Component ──────────────────────────────────────────────────────────────

export default function ExecBrief({ principal }: Props) {
  void principal;
  const [loading, setLoading]           = useState(true);
  const [threat, setThreat]             = useState<ThreatSummary | null>(null);
  const [partners, setPartners]         = useState<FederationPartner[]>([]);
  const [actions, setActions]           = useState<
    { id: string; action_type: string; status: string; created_at: string }[]
  >([]);
  const [situationLines, setSituation]  = useState<string[]>([]);
  const [lastRefresh, setLastRefresh]   = useState<Date>(new Date());
  const [error, setError]               = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [partnersData, runsData, incidentsData] = await Promise.all([
        fetchFederationPartners().catch(() => [] as FederationPartner[]),
        apiFetchJson<{ items: { positive_count: number; node_count: number; prediction_type: string }[] }>(
          endpoints.aiTrainingRuns(1, 0),
          { method: "GET" },
        ).catch(() => ({ items: [] })),
        apiFetchJson<{ items: { action_type: string; status: string; created_at: string; id: string }[] }>(
          endpoints.defenseIncidents(10, 0),
          { method: "GET" },
        ).catch(() => ({ items: [] })),
      ]);

      const latestRun = runsData.items?.[0] ?? null;
      const highRiskCount = latestRun?.positive_count ?? 0;
      const partnerAlerts = (partnersData ?? []).length;

      const pending = (incidentsData.items ?? []).filter(
        (a) => a.status === "queued" || a.status === "failed",
      );
      const topActions = (incidentsData.items ?? []).slice(0, 3);

      setPartners(partnersData ?? []);
      setActions(topActions);
      setThreat(computeThreatLevel(highRiskCount, partnerAlerts, pending.length));

      // Build situation lines in plain English
      const lines: string[] = [];
      if (latestRun) {
        const domain = latestRun.prediction_type === "corruption_risk"
          ? "government procurement fraud"
          : "cyber and financial fraud";
        lines.push(
          `AI analysis flagged ${highRiskCount} high-risk entities across ${domain} patterns.`,
        );
      }
      if (partnerAlerts >= 2) {
        lines.push(
          `${partnerAlerts} partner organisations (banks, telcos) are reporting correlated threats.`,
        );
      }
      if (pending.length > 0) {
        lines.push(
          `${pending.length} containment action${pending.length > 1 ? "s" : ""} pending authorisation or review.`,
        );
      }
      if (lines.length === 0) {
        lines.push("No significant threats require immediate executive attention.");
      }
      setSituation(lines);
      setLastRefresh(new Date());
    } catch (err) {
      setError("Could not load situation report. Check network connectivity.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 60 seconds
  useEffect(() => {
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, [load]);

  if (loading && !threat) {
    return (
      <div className="exec-brief-loading">
        <Loader size={28} className="spin" />
        <p>Loading situation report…</p>
      </div>
    );
  }

  const connectedCodes = new Set(partners.map((p) => p.partner_id?.split("_")[0]?.toUpperCase()));

  return (
    <div className="exec-brief">

      {/* ── Threat Level Banner ─────────────────────────────────────── */}
      <div
        className="exec-threat-banner"
        style={{ background: threat?.color ?? "#30d158" }}
      >
        <div className="exec-threat-icon">
          {threat?.level === "NORMAL"
            ? <CheckCircle size={36} color="#fff" />
            : <AlertTriangle size={36} color="#fff" />}
        </div>
        <div className="exec-threat-text">
          <div className="exec-threat-headline">{threat?.headline}</div>
          <div className="exec-threat-detail">{threat?.detail}</div>
        </div>
        <button
          className="exec-refresh-btn"
          onClick={load}
          disabled={loading}
          title="Refresh now"
          type="button"
        >
          <RefreshCw size={18} className={loading ? "spin" : ""} />
        </button>
      </div>

      {error && <div className="exec-error">{error}</div>}

      <div className="exec-body">

        {/* ── Immediate Actions ───────────────────────────────────────── */}
        <section className="exec-section">
          <h2 className="exec-section-title">Immediate Actions Required</h2>
          {actions.length === 0 ? (
            <p className="exec-none">No pending actions — security teams are monitoring.</p>
          ) : (
            <ol className="exec-action-list">
              {actions.map((a) => (
                <li key={a.id} className={`exec-action-item exec-action-${a.status}`}>
                  <span className="exec-action-label">
                    {humanAction(a.action_type, a.status)}
                  </span>
                  <span className="exec-action-time">
                    <Clock size={12} />
                    {new Date(a.created_at).toLocaleTimeString()}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </section>

        {/* ── Agency Status ────────────────────────────────────────────── */}
        <section className="exec-section">
          <h2 className="exec-section-title">Connected Agencies</h2>
          <div className="exec-agency-grid">
            {ALL_AGENCY_CODES.map((code) => {
              const online = connectedCodes.has(code);
              return (
                <div key={code} className={`exec-agency-chip ${online ? "online" : "offline"}`}>
                  <span
                    className="exec-agency-dot"
                    style={{ background: online ? "#30d158" : "#636366" }}
                  />
                  <span className="exec-agency-name">{agencyName(code)}</span>
                </div>
              );
            })}
          </div>
        </section>

        {/* ── Situation Summary ─────────────────────────────────────────── */}
        <section className="exec-section">
          <h2 className="exec-section-title">Situation Summary</h2>
          <ul className="exec-situation-list">
            {situationLines.map((line, i) => (
              <li key={i} className="exec-situation-item">{line}</li>
            ))}
          </ul>
        </section>

      </div>

      <div className="exec-footer">
        Sentinel-KE National Intelligence Platform &nbsp;·&nbsp;
        Last updated: {lastRefresh.toLocaleTimeString()} &nbsp;·&nbsp;
        <span className="exec-classification">RESTRICTED — Authorised personnel only</span>
      </div>
    </div>
  );
}
