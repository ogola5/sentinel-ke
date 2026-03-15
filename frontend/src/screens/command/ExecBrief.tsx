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

// ── Agency status ──────────────────────────────────────────────────────────

const ALL_AGENCY_CODES = Object.keys(KENYA_AGENCIES);

// ── Component ──────────────────────────────────────────────────────────────

export default function ExecBrief({ principal }: Props) {
  void principal;
  const [loading, setLoading]           = useState(true);
  const [threat, setThreat]             = useState<ThreatSummary | null>(null);
  const [partners, setPartners]         = useState<FederationPartner[]>([]);
  const [incidentRuns, setIncidentRuns] = useState<
    { id: string; incident_key: string; severity: string; status: string; started_at: string | null; section_code: string | null }[]
  >([]);
  const [situationLines, setSituation]  = useState<string[]>([]);
  const [lastRefresh, setLastRefresh]   = useState<Date>(new Date());
  const [error, setError]               = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [partnersData, runsData, incidentsData] = await Promise.all([
        fetchFederationPartners({ strict: true }).catch(() => [] as FederationPartner[]),
        apiFetchJson<{ items: { positive_count: number; node_count: number; prediction_type: string }[] }>(
          endpoints.aiTrainingRuns(1, 0),
          { method: "GET" },
        ).catch(() => ({ items: [] })),
        apiFetchJson<{ items: { incident_key: string; status: string; started_at: string | null; id: string; severity: string; section_code: string | null }[] }>(
          endpoints.defenseIncidents(10, 0),
          { method: "GET" },
        ).catch(() => ({ items: [] })),
      ]);

      const latestRun = runsData.items?.[0] ?? null;
      const highRiskCount = latestRun?.positive_count ?? 0;
      const partnerAlerts = (partnersData ?? []).filter((partner) => partner.status === "online").length;

      const activeRuns = (incidentsData.items ?? []).filter(
        (run) => run.status === "running" || run.status === "failed",
      );
      const topRuns = (incidentsData.items ?? []).slice(0, 3);

      setPartners(partnersData ?? []);
      setIncidentRuns(topRuns);
      setThreat(computeThreatLevel(highRiskCount, partnerAlerts, activeRuns.length));

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
      if (activeRuns.length > 0) {
        lines.push(
          `${activeRuns.length} incident response run${activeRuns.length > 1 ? "s" : ""} still need operator follow-through.`,
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
          <h2 className="exec-section-title">Incident Response Queue</h2>
          {incidentRuns.length === 0 ? (
            <p className="exec-none">No active incident runs — security teams are monitoring.</p>
          ) : (
            <ol className="exec-action-list">
              {incidentRuns.map((run) => (
                <li key={run.id} className={`exec-action-item exec-action-${run.status}`}>
                  <span className="exec-action-label">
                    {`${run.incident_key} · ${run.severity.toUpperCase()} · ${run.status.replace("_", " ")}`}
                  </span>
                  <span className="exec-action-time">
                    <Clock size={12} />
                    {run.started_at ? new Date(run.started_at).toLocaleTimeString() : "No start time"}
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
