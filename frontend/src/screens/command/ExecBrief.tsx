/**
 * Executive Readiness Brief
 *
 * A judge-facing presentation layer that shows what the platform can prove
 * operationally right now, where the live system is aligned to benchmarked
 * model runs, and where caveats still apply.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  Clock,
  Database,
  Loader,
  RefreshCw,
  Shield,
} from "lucide-react";

import {
  fetchGNNDomainHealth,
  fetchGNNLatestRuns,
  fetchOperationalHealthSnapshot,
  fetchPlatformTrustSummary,
} from "../../api/ai";
import { apiFetchJson } from "../../api/client";
import { endpoints } from "../../api/endpoints";
import { fetchFederationPartners } from "../../api/federation";
import type { Principal } from "../../types/auth";
import type {
  GNNDomainHealth,
  GNNDomainSummary,
  OperationalHealthSnapshot,
  PlatformTrustSummary,
  TrustCheck,
} from "../../types/ai";
import type { FederationPartner } from "../../types/federation";

interface Props {
  principal: Principal;
}

type ReadinessLevel = "READY" | "CAUTION" | "REMEDIATE";

interface ReadinessSummary {
  level: ReadinessLevel;
  headline: string;
  detail: string;
  color: string;
}

interface IncidentRunRow {
  id: string;
  incident_key: string;
  severity: string;
  status: string;
  started_at: string | null;
  section_code: string | null;
}

const DOMAIN_ORDER = ["risk_gnn", "corruption_risk"];

function labelForPredictionType(predictionType: string): string {
  if (predictionType === "corruption_risk") return "Corruption risk";
  if (predictionType === "risk_gnn") return "Cyber and fraud";
  return predictionType.replace(/_/g, " ");
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatHours(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value < 1) return `${Math.max(1, Math.round(value * 60))}m`;
  if (value < 24) return `${value.toFixed(1)}h`;
  return `${Math.round(value)}h`;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-KE", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toneColor(status: "pass" | "warn" | "fail" | "ok" | "missing"): string {
  if (status === "pass" || status === "ok") return "var(--accent)";
  if (status === "warn") return "var(--warning)";
  return "var(--risk-critical)";
}

function metricToneClass(status: "pass" | "warn" | "fail" | "ok" | "missing"): string {
  if (status === "pass" || status === "ok") return "accent";
  if (status === "warn") return "warn";
  return "danger";
}

function computeReadinessSummary(
  trustSummary: PlatformTrustSummary | null,
  domainHealthRows: GNNDomainHealth[],
  platformHealth: OperationalHealthSnapshot | null,
): ReadinessSummary {
  if (!trustSummary && domainHealthRows.length === 0 && !platformHealth) {
    return {
      level: "REMEDIATE",
      headline: "REMEDIATE — Readiness evidence is unavailable",
      detail: "Core readiness feeds did not load. Do not present the platform as judge-ready until trust and domain-health evidence is visible.",
      color: "#ff2d55",
    };
  }

  const hardFailure =
    trustSummary?.overall_status === "fail" ||
    domainHealthRows.some(
      (row) =>
        row.status === "missing" ||
        row.fairness_blocked === true ||
        row.real_data_gate_passed === false,
    ) ||
    (platformHealth != null && !platformHealth.schema_contract_ok);

  if (hardFailure) {
    return {
      level: "REMEDIATE",
      headline: "REMEDIATE — Do not overclaim readiness",
      detail: "One or more model-governance, schema, or evidence checks are failing. Present the system as in remediation and state the gaps explicitly.",
      color: "#ff2d55",
    };
  }

  const caution =
    trustSummary?.overall_status === "warn" ||
    domainHealthRows.some(
      (row) =>
        row.status === "warn" ||
        !row.run_prediction_alignment.window_matches ||
        !row.run_prediction_alignment.model_version_matches,
    ) ||
    (platformHealth != null && !platformHealth.federation_signed_requests_required);

  if (caution) {
    return {
      level: "CAUTION",
      headline: "CAUTION — Present with explicit caveats",
      detail: "Live operating evidence exists, but some freshness, alignment, or governance checks are degraded. Pair the KPIs with the caveats shown below.",
      color: "#ff9f0a",
    };
  }

  return {
    level: "READY",
    headline: "READY — Operational proof surface is available",
    detail: "Live queues, benchmark references, and trust controls are visible. Present these as readiness indicators, not as proof that every flagged entity is correct.",
    color: "#30d158",
  };
}

function summarizeChecks(checks: TrustCheck[]): { pass: number; warn: number; fail: number } {
  return checks.reduce(
    (acc, check) => {
      acc[check.status] += 1;
      return acc;
    },
    { pass: 0, warn: 0, fail: 0 },
  );
}

export default function ExecBrief({ principal }: Props) {
  void principal;

  const [loading, setLoading] = useState(true);
  const [partners, setPartners] = useState<FederationPartner[]>([]);
  const [domainSummaries, setDomainSummaries] = useState<GNNDomainSummary[]>([]);
  const [domainHealthRows, setDomainHealthRows] = useState<GNNDomainHealth[]>([]);
  const [trustSummary, setTrustSummary] = useState<PlatformTrustSummary | null>(null);
  const [platformHealth, setPlatformHealth] = useState<OperationalHealthSnapshot | null>(null);
  const [incidentRuns, setIncidentRuns] = useState<IncidentRunRow[]>([]);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [partnersData, latestRuns, domainHealth, trust, health, incidentsData] = await Promise.all([
        fetchFederationPartners({ strict: true }).catch(() => [] as FederationPartner[]),
        fetchGNNLatestRuns(undefined, { strict: true }).catch(() => [] as GNNDomainSummary[]),
        fetchGNNDomainHealth(undefined, { strict: true }).catch(() => [] as GNNDomainHealth[]),
        fetchPlatformTrustSummary(),
        fetchOperationalHealthSnapshot(),
        apiFetchJson<{ items: IncidentRunRow[] }>(endpoints.defenseIncidents(10, 0), { method: "GET" }).catch(
          () => ({ items: [] }),
        ),
      ]);

      setPartners(partnersData ?? []);
      setDomainSummaries(latestRuns ?? []);
      setDomainHealthRows(domainHealth ?? []);
      setTrustSummary(trust);
      setPlatformHealth(health);
      setIncidentRuns((incidentsData.items ?? []).slice(0, 4));
      setLastRefresh(new Date());

      const missingFeeds = [
        latestRuns.length === 0 ? "benchmark metrics" : null,
        domainHealth.length === 0 ? "domain health" : null,
        trust == null ? "trust summary" : null,
        health == null ? "operational health" : null,
      ].filter(Boolean);

      if (missingFeeds.length > 0) {
        setError(`Some readiness feeds are unavailable: ${missingFeeds.join(", ")}.`);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void load();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const readiness = useMemo(
    () => computeReadinessSummary(trustSummary, domainHealthRows, platformHealth),
    [trustSummary, domainHealthRows, platformHealth],
  );

  const activeIncidentRuns = incidentRuns.filter((run) => run.status === "running" || run.status === "failed");
  const onlinePartners = partners.filter((partner) => partner.status === "online");
  const stalePartners = partners.filter((partner) => partner.status === "stale").length;
  const connectedAgencies = new Set(
    onlinePartners
      .map((partner) => partner.partner_id?.split("_")[0]?.toUpperCase())
      .filter(Boolean),
  ).size;
  const totalPredictions = domainHealthRows.reduce(
    (sum, row) => sum + Number(row.latest_prediction_count ?? 0),
    0,
  );
  const totalFlagged = domainHealthRows.reduce((sum, row) => sum + Number(row.flagged_count ?? 0), 0);
  const totalHighRisk = domainHealthRows.reduce((sum, row) => sum + Number(row.high_risk_count ?? 0), 0);
  const checkSummary = summarizeChecks(trustSummary?.checks ?? []);
  const domainHealthByType = new Map(domainHealthRows.map((row) => [row.prediction_type, row]));
  const domainSummaryByType = new Map(domainSummaries.map((row) => [row.prediction_type, row]));
  const domainTypes = Array.from(
    new Set([...domainSummaries.map((row) => row.prediction_type), ...domainHealthRows.map((row) => row.prediction_type)]),
  ).sort((left, right) => DOMAIN_ORDER.indexOf(left) - DOMAIN_ORDER.indexOf(right));

  const presenterLines = useMemo(() => {
    const lines: string[] = [];

    if (partners.length > 0) {
      lines.push(
        `${onlinePartners.length} of ${partners.length} partner feeds are online${stalePartners > 0 ? `, with ${stalePartners} stale` : ""}. ${connectedAgencies} agency footprints are visible in the live federation view.`,
      );
    }

    if (domainHealthRows.length > 0) {
      const alignedCount = domainHealthRows.filter(
        (row) =>
          row.run_prediction_alignment.window_matches &&
          row.run_prediction_alignment.model_version_matches,
      ).length;
      lines.push(
        `${alignedCount} of ${domainHealthRows.length} model lane${domainHealthRows.length === 1 ? "" : "s"} remain aligned to the latest recorded benchmark window and model version.`,
      );
    }

    if (trustSummary) {
      const unresolved = checkSummary.warn + checkSummary.fail;
      lines.push(
        `${checkSummary.pass} trust checks pass${unresolved > 0 ? `; ${unresolved} still require caveats or remediation` : ""}. ${trustSummary.headline}`,
      );
    }

    lines.push(
      "Use benchmark metrics as operating baselines and queue evidence, not as proof of liability, intent, or certainty on their own.",
    );

    return lines;
  }, [partners, onlinePartners.length, stalePartners, connectedAgencies, domainHealthRows, trustSummary, checkSummary.pass, checkSummary.warn, checkSummary.fail]);

  if (loading && domainSummaries.length === 0 && domainHealthRows.length === 0 && !trustSummary) {
    return (
      <div className="exec-brief-loading">
        <Loader size={28} className="spin" />
        <p>Loading readiness evidence…</p>
      </div>
    );
  }

  return (
    <div className="exec-brief">
      <div className="exec-threat-banner" style={{ background: readiness.color }}>
        <div className="exec-threat-icon">
          {readiness.level === "READY" ? <CheckCircle size={36} color="#fff" /> : <AlertTriangle size={36} color="#fff" />}
        </div>
        <div className="exec-threat-text">
          <div className="exec-threat-headline">{readiness.headline}</div>
          <div className="exec-threat-detail">{readiness.detail}</div>
        </div>
        <button
          className="exec-refresh-btn"
          onClick={() => void load()}
          disabled={loading}
          title="Refresh now"
          type="button"
        >
          <RefreshCw size={18} className={loading ? "spin" : ""} />
        </button>
      </div>

      {error && <div className="exec-error">{error}</div>}

      <div className="exec-body">
        <section className="exec-section">
          <h2 className="exec-section-title">KPI and Coverage</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div className="metric-card accent">
              <div className="metric-label">Partner coverage</div>
              <div className="metric-value">{onlinePartners.length}/{partners.length || 0}</div>
              <div className="metric-sub">{connectedAgencies} agencies visible in live federation</div>
            </div>
            <div className={`metric-card ${totalHighRisk > 0 ? "warn" : "accent"}`}>
              <div className="metric-label">Flagged queue now</div>
              <div className="metric-value">{totalFlagged}</div>
              <div className="metric-sub">{totalHighRisk} high-risk entities across live lanes</div>
            </div>
            <div className={`metric-card ${((trustSummary?.action_readiness.active_webhooks ?? 0) > 0) ? "accent" : "warn"}`}>
              <div className="metric-label">Containment routes</div>
              <div className="metric-value">{trustSummary?.action_readiness.active_webhooks ?? 0}</div>
              <div className="metric-sub">{trustSummary?.action_readiness.executed_actions_24h ?? 0} actions executed in 24h</div>
            </div>
            <div className={`metric-card ${activeIncidentRuns.length > 0 ? "warn" : "accent"}`}>
              <div className="metric-label">Open response runs</div>
              <div className="metric-value">{activeIncidentRuns.length}</div>
              <div className="metric-sub">{trustSummary?.action_readiness.pending_actions ?? 0} queued actions remain</div>
            </div>
          </div>

          <div className="exec-situation-item" style={{ marginTop: 12, borderLeftColor: "var(--accent)" }}>
            Current operating KPI: {totalPredictions} live predictions are on-screen right now. Queue volume shows activity and review demand, not model correctness by itself.
          </div>

          <div style={{ marginTop: 14 }}>
            <div className="exec-section-title" style={{ marginBottom: 10 }}>Active response queue</div>
            {incidentRuns.length === 0 ? (
              <p className="exec-none">No active incident runs are blocking the presentation surface right now.</p>
            ) : (
              <ol className="exec-action-list">
                {incidentRuns.map((run) => (
                  <li key={run.id} className={`exec-action-item exec-action-${run.status}`}>
                    <span className="exec-action-label">
                      {`${run.incident_key} · ${run.severity.toUpperCase()} · ${run.status.replace(/_/g, " ")}`}
                    </span>
                    <span className="exec-action-time">
                      <Clock size={12} />
                      {run.started_at ? formatTimestamp(run.started_at) : "No start time"}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>

        <section className="exec-section">
          <h2 className="exec-section-title">Benchmarked Baseline</h2>
          <p className="exec-none" style={{ marginBottom: 12 }}>
            These are the latest recorded benchmark metrics for each lane. They are reference baselines for the model, not proof about a specific case.
          </p>

          {domainTypes.length === 0 ? (
            <p className="exec-none">No model-lane baseline is available yet.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {domainTypes.map((predictionType) => {
                const summary = domainSummaryByType.get(predictionType);
                const health = domainHealthByType.get(predictionType);
                const latestRun = summary?.latest_run ?? null;
                const cardTone = health?.status ?? "missing";
                const reasonLine =
                  health?.status_reasons?.find(Boolean) ??
                  summary?.status_reasons?.find(Boolean) ??
                  "No benchmark explanation has been recorded yet.";

                return (
                  <div key={predictionType} className="priority-card" style={{ marginTop: 0 }}>
                    <div className="priority-card-head">
                      <div>
                        <h4 className="priority-card-title">{summary?.domain_label ?? health?.domain_label ?? labelForPredictionType(predictionType)}</h4>
                        <p className="priority-card-copy">{reasonLine}</p>
                      </div>
                      <span
                        className="chip"
                        style={{
                          color: toneColor(cardTone),
                          borderColor: `${toneColor(cardTone)}55`,
                        }}
                      >
                        {(health?.status ?? summary?.status ?? "missing").toUpperCase()}
                      </span>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10 }}>
                      <div className={`metric-card ${metricToneClass(cardTone)}`} style={{ padding: "10px 12px" }}>
                        <div className="metric-label">AUC</div>
                        <div className="metric-value">{formatPercent(latestRun?.auc)}</div>
                        <div className="metric-sub">Latest benchmark run</div>
                      </div>
                      <div className={`metric-card ${metricToneClass(cardTone)}`} style={{ padding: "10px 12px" }}>
                        <div className="metric-label">Precision</div>
                        <div className="metric-value">{formatPercent(latestRun?.precision)}</div>
                        <div className="metric-sub">Latest benchmark run</div>
                      </div>
                      <div className="metric-card" style={{ padding: "10px 12px" }}>
                        <div className="metric-label">Recall</div>
                        <div className="metric-value">{formatPercent(latestRun?.recall)}</div>
                        <div className="metric-sub">Latest benchmark run</div>
                      </div>
                      <div className="metric-card" style={{ padding: "10px 12px" }}>
                        <div className="metric-label">F1</div>
                        <div className="metric-value">{formatPercent(latestRun?.f1)}</div>
                        <div className="metric-sub">Latest benchmark run</div>
                      </div>
                    </div>

                    <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                      <div className="exec-situation-item" style={{ borderLeftColor: toneColor(cardTone), padding: "10px 12px" }}>
                        Live queue: {health?.latest_prediction_count ?? 0} predictions, {health?.flagged_count ?? 0} flagged, {health?.high_risk_count ?? 0} high risk.
                      </div>
                      <div className="exec-situation-item" style={{ borderLeftColor: toneColor(cardTone), padding: "10px 12px" }}>
                        Alignment: {health?.run_prediction_alignment.window_matches ? "live window matches latest benchmark" : "live window moved ahead of latest benchmark"}; {health?.run_prediction_alignment.model_version_matches ? "model version matches" : "model version differs"}.
                      </div>
                      <div className="exec-situation-item" style={{ borderLeftColor: toneColor(cardTone), padding: "10px 12px" }}>
                        Robustness guardrails: {health?.real_data_gate_passed === false ? "real-data gate not yet passed" : "real-data gate passed or not flagged"}; {health?.fairness_blocked ? "fairness policy blocks deployment" : "no fairness block recorded"}.
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="exec-section">
          <h2 className="exec-section-title">Trust Evidence and Caveats</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div className={`metric-card ${checkSummary.fail > 0 ? "danger" : checkSummary.warn > 0 ? "warn" : "accent"}`}>
              <div className="metric-label">Trust checks</div>
              <div className="metric-value">{checkSummary.pass}</div>
              <div className="metric-sub">{checkSummary.warn} warn · {checkSummary.fail} fail</div>
            </div>
            <div className={`metric-card ${(platformHealth?.schema_contract_ok ?? false) ? "accent" : "warn"}`}>
              <div className="metric-label">Schema contract</div>
              <div className="metric-value">{platformHealth?.schema_contract_ok ? "Clean" : "Attention"}</div>
              <div className="metric-sub">{platformHealth?.schema_missing_count ?? 0} required fields missing</div>
            </div>
            <div className="metric-card info">
              <div className="metric-label">Prediction freshness</div>
              <div className="metric-value">{formatHours(trustSummary?.freshness.prediction_age_hours)}</div>
              <div className="metric-sub">Graph {formatHours(trustSummary?.freshness.graph_age_hours)} · Intel {formatHours(trustSummary?.freshness.intel_age_hours)}</div>
            </div>
            <div className={`metric-card ${trustSummary?.resilience.latest_restore_success ? "accent" : "warn"}`}>
              <div className="metric-label">Resilience proof</div>
              <div className="metric-value">{trustSummary?.resilience.backup_attestations_30d ?? 0}</div>
              <div className="metric-sub">
                Latest restore {trustSummary?.resilience.latest_restore_success ? "succeeded" : "needs evidence"}
              </div>
            </div>
          </div>

          <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
            {presenterLines.map((line, index) => (
              <div key={`${index}-${line.slice(0, 24)}`} className="exec-situation-item" style={{ padding: "10px 12px" }}>
                {line}
              </div>
            ))}
          </div>

          <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
            {(trustSummary?.checks ?? []).slice(0, 4).map((check) => (
              <div key={check.label} className="exec-situation-item" style={{ borderLeftColor: toneColor(check.status), padding: "10px 12px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <strong>{check.label}</strong>
                  <span style={{ color: toneColor(check.status), fontSize: "0.75rem", fontWeight: 700 }}>
                    {check.status.toUpperCase()}
                  </span>
                </div>
                <div className="muted" style={{ marginTop: 4 }}>
                  {check.detail}
                </div>
                {check.action && check.status !== "pass" && (
                  <div className="muted" style={{ marginTop: 4 }}>
                    Action: {check.action}
                  </div>
                )}
              </div>
            ))}

            <div className="exec-situation-item" style={{ borderLeftColor: "var(--warning)", padding: "10px 12px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Shield size={14} color="var(--warning)" />
                <strong>Presentation guardrail</strong>
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                This brief shows current readiness, live queue pressure, benchmark references, and trust controls. It does not establish wrongdoing, intent, or certainty without analyst review and case evidence.
              </div>
            </div>

            <div className="exec-situation-item" style={{ borderLeftColor: "var(--accent)", padding: "10px 12px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Activity size={14} color="var(--accent)" />
                <strong>Operational anchors</strong>
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                Signed federation is {platformHealth?.federation_signed_requests_required ? "enforced" : "not yet enforced"}; legal anchor integrity is {platformHealth?.legal_anchor_integrity ?? "unknown"}; latest prediction was recorded at {formatTimestamp(trustSummary?.freshness.latest_prediction_at)}.
              </div>
            </div>

            <div className="exec-situation-item" style={{ borderLeftColor: "var(--info)", padding: "10px 12px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Database size={14} color="var(--info)" />
                <strong>Model provenance anchor</strong>
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                The latest operational model version is {platformHealth?.gnn_model_version ?? "unknown"}{platformHealth?.gnn_prediction_type ? ` for ${labelForPredictionType(platformHealth.gnn_prediction_type)}` : ""}. Present that identifier whenever you cite current model state.
              </div>
            </div>
          </div>
        </section>
      </div>

      <div className="exec-footer">
        Sentinel-KE Readiness Brief &nbsp;·&nbsp;
        Last updated: {lastRefresh.toLocaleTimeString()} &nbsp;·&nbsp;
        <span className="exec-classification">RESTRICTED — Authorised personnel only</span>
      </div>
    </div>
  );
}
