/**
 * Timeline / Indicators — S2
 *
 * Threat forecast dashboard powered by:
 *   • event_log   — multi-source event volume (fraud, DDoS, network, vuln, phishing)
 *   • ai_prediction (risk_gnn) — GNN risk trajectory over time
 *   • ai_campaign_risk_indicator — campaign severity breakdown
 *
 * Falls back to legacy DDoS-only indicators when threatSummary has no data.
 */
import type { ServiceIndicator, ThreatSummary } from "../types/domain";
import { Sparkline, Meter } from "../components/Charts";
import { formatPercent, formatScore } from "../utils/formatters";

// ── helpers ──────────────────────────────────────────────────────────────────

const stageClass = (stage: string) => {
  if (stage === "active")    return "stage stage-active";
  if (stage === "emerging")  return "stage stage-emerging";
  if (stage === "rehearsal") return "stage stage-rehearsal";
  return "stage";
};

const stageLabel = (stage: string) => {
  if (stage === "rehearsal") return "probing";
  return stage;
};

const KILL_CHAIN_ORDER = [
  "reconnaissance", "weaponization", "delivery",
  "exploitation", "installation", "command_and_control", "actions_on_objectives",
];

const KILL_CHAIN_LABEL: Record<string, string> = {
  reconnaissance:          "Recon",
  weaponization:           "Weaponize",
  delivery:                "Delivery",
  exploitation:            "Exploit",
  installation:            "Install",
  command_and_control:     "C2",
  actions_on_objectives:   "Impact",
};

const SEVERITY_COLOR: Record<string, string> = {
  critical: "var(--danger)",
  high:     "var(--warning)",
  medium:   "var(--accent)",
  low:      "var(--ink-muted)",
};

const CATEGORY_COLOR: Record<string, string> = {
  fraud:         "#f0bf4c",
  ddos:          "#e85a67",
  network:       "#2fd67d",
  vulnerability: "#bbf7d2",
  phishing:      "#8b5cf6",
  other:         "#6b7280",
};

const CATEGORY_LABEL: Record<string, string> = {
  fraud:         "Fraud / Mobile Money",
  ddos:          "DDoS Signals",
  network:       "Network Intrusion",
  vulnerability: "Vulnerabilities (KEV)",
  phishing:      "Phishing",
  other:         "Other",
};

function trendIcon(trend: string) {
  if (trend === "rising")  return "↑";
  if (trend === "falling") return "↓";
  return "→";
}

function trendColor(trend: string) {
  if (trend === "rising")  return "var(--danger)";
  if (trend === "falling") return "var(--accent)";
  return "var(--ink-muted)";
}

function fmtDate(iso: string): string {
  try { return new Date(iso).toLocaleDateString("en-KE", { month: "short", day: "numeric" }); }
  catch { return iso; }
}

// ── types ────────────────────────────────────────────────────────────────────

type TimelineProps = {
  indicators:        ServiceIndicator[];
  threatSummary:     ThreatSummary;
  selectedService:   string;
  evidenceRefs:      string[];
  onSelectService:   (serviceId: string) => void;
  onOpenCampaign:    () => void;
  onShowInfra:       () => void;
};

// ── component ────────────────────────────────────────────────────────────────

export default function Timeline({
  indicators,
  threatSummary,
  selectedService,
  evidenceRefs,
  onSelectService,
  onOpenCampaign,
  onShowInfra,
}: TimelineProps) {

  const hasSummary = threatSummary.event_volume_series.length > 0
    || threatSummary.gnn_risk_series.length > 0
    || threatSummary.event_totals.total > 0;

  // ── no data at all ──────────────────────────────────────────────────────
  if (!hasSummary && indicators.length === 0) {
    return (
      <section className="screen">
        <div className="screen-header">
          <div>
            <p className="eyebrow">S2</p>
            <h2>Threat Forecast &amp; Indicators</h2>
            <p className="subtle">GNN risk trajectory, AI early warning, and multi-source threat telemetry.</p>
          </div>
        </div>
        <div className="panel" style={{ textAlign: "center", padding: "56px 24px" }}>
          <p style={{ fontSize: "2rem", marginBottom: 8 }}>📡</p>
          <p style={{ fontWeight: 700, marginBottom: 6 }}>Waiting for threat telemetry</p>
          <p className="muted" style={{ maxWidth: 440, margin: "0 auto", lineHeight: 1.6 }}>
            Once events are ingested and the GNN model runs, this screen will show live risk
            trajectories, AI forecasts, and multi-source threat breakdowns.
          </p>
        </div>
      </section>
    );
  }

  // ── derived values ──────────────────────────────────────────────────────
  const { event_totals, campaign_risk, gnn_risk_series, event_volume_series,
          top_threats, kill_chain_distribution, forecast } = threatSummary;

  const gnnScores     = gnn_risk_series.map(d => d.avg_score);
  const gnnMax        = gnn_risk_series.map(d => d.max_score);
  const gnnDates      = gnn_risk_series.map(d => fmtDate(d.date));
  const latestGnn     = gnn_risk_series[gnn_risk_series.length - 1];

  const CATS = ["fraud", "ddos", "network", "vulnerability", "phishing"] as const;
  const volTotal = event_volume_series.reduce((s, d) => s + d.total, 0);

  // Sparkline per category over days
  const catSeries = (cat: "fraud" | "ddos" | "network" | "vulnerability" | "phishing") =>
    event_volume_series.map(d => d[cat] ?? 0);

  // Kill-chain bar
  const kcTotal = Object.values(kill_chain_distribution).reduce((a, b) => a + b, 0) || 1;
  const orderedKC = KILL_CHAIN_ORDER
    .filter(k => kill_chain_distribution[k] > 0)
    .map(k => ({ key: k, count: kill_chain_distribution[k], pct: kill_chain_distribution[k] / kcTotal }));

  return (
    <section className="screen">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="screen-header">
        <div>
          <p className="eyebrow">S2</p>
          <h2>Threat Forecast &amp; Indicators</h2>
          <p className="subtle">
            GNN risk trajectory · AI early warning · multi-source threat telemetry.
            Data from {gnn_risk_series.length} GNN training windows over the last {threatSummary.window_days} days.
          </p>
        </div>
        <div className="chip-row">
          {forecast.trend !== "stable" && (
            <span className="chip" style={{ color: trendColor(forecast.trend), fontWeight: 700 }}>
              {trendIcon(forecast.trend)} Risk {forecast.trend}
            </span>
          )}
          {campaign_risk.critical > 0 && (
            <span className="chip" style={{ color: "var(--danger)", borderColor: "rgba(232,90,103,0.4)" }}>
              🔴 {campaign_risk.critical} critical campaigns
            </span>
          )}
        </div>
      </div>

      {/* ── AI Forecast banner ─────────────────────────────────────────────── */}
      {forecast.forecast_score !== null && (
        <div className="panel" style={{
          background: `rgba(${forecast.trend === "rising" ? "232,90,103" : forecast.trend === "falling" ? "47,214,125" : "240,191,76"},0.07)`,
          border: `1px solid rgba(${forecast.trend === "rising" ? "232,90,103" : forecast.trend === "falling" ? "47,214,125" : "240,191,76"},0.25)`,
          padding: "14px 18px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <div>
              <p className="label" style={{ marginBottom: 2 }}>GNN AI Forecast — 3-day outlook</p>
              <p style={{ fontWeight: 700, fontSize: "1.1rem" }}>
                <span style={{ color: trendColor(forecast.trend), marginRight: 8 }}>
                  {trendIcon(forecast.trend)} Risk is {forecast.trend}
                </span>
                Predicted score: <span style={{ color: trendColor(forecast.trend) }}>
                  {forecast.forecast_score.toFixed(1)}/100
                </span>
              </p>
            </div>
            <div style={{ marginLeft: "auto", textAlign: "right" }}>
              <p className="label">Model confidence</p>
              <p style={{ fontWeight: 600 }}>{Math.round(forecast.confidence * 100)}%</p>
            </div>
            <p className="muted" style={{ fontSize: "0.76rem", width: "100%", marginTop: 4 }}>
              AI risk score for investigative prioritisation. Legal enforcement requires forensic corroboration.
            </p>
          </div>
        </div>
      )}

      {/* ── Summary stats ──────────────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0,1fr))", gap: "0.5rem" }}>
        {CATS.map(cat => (
          <div key={cat} className="panel" style={{ padding: "10px 12px" }}>
            <p className="label" style={{ fontSize: "0.72rem", marginBottom: 2 }}>{CATEGORY_LABEL[cat]}</p>
            <p style={{ fontWeight: 700, fontSize: "1.3rem",
              color: CATEGORY_COLOR[cat], margin: "2px 0" }}>
              {((event_totals as Record<string, number>)[cat] ?? 0).toLocaleString()}
            </p>
            <p className="muted" style={{ fontSize: "0.68rem" }}>total events</p>
          </div>
        ))}
      </div>

      {/* ── GNN Risk Trajectory ────────────────────────────────────────────── */}
      {gnn_risk_series.length > 0 && (
        <div className="grid-two">
          <div className="panel">
            <div className="panel-header">
              <h3>GNN Risk Trajectory</h3>
              <span className="muted">Average entity risk score per day</span>
            </div>
            <Sparkline data={gnnScores.length > 1 ? gnnScores : [0, ...gnnScores]} height={80} />
            <div className="chart-meta">
              {gnnDates.map(d => <span key={d}>{d}</span>)}
            </div>
            {latestGnn && (
              <div className="detail-grid" style={{ marginTop: 12 }}>
                <div>
                  <p className="label">Latest avg score</p>
                  <p className="stat" style={{ color: "var(--accent)" }}>{latestGnn.avg_score.toFixed(1)}</p>
                </div>
                <div>
                  <p className="label">Latest max score</p>
                  <p className="stat" style={{ color: "var(--warning)" }}>{latestGnn.max_score.toFixed(1)}</p>
                </div>
                <div>
                  <p className="label">P90 score</p>
                  <p className="stat">{latestGnn.p90_score.toFixed(1)}</p>
                </div>
                <div>
                  <p className="label">Entities scored</p>
                  <p className="stat">{latestGnn.prediction_count.toLocaleString()}</p>
                </div>
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Max Threat Score</h3>
              <span className="muted">Highest-risk entity per day</span>
            </div>
            <Sparkline data={gnnMax.length > 1 ? gnnMax : [0, ...gnnMax]}
              height={80} stroke="var(--danger)" />
            <div className="chart-meta">
              {gnnDates.map(d => <span key={d}>{d}</span>)}
            </div>
            <div style={{ marginTop: 12 }}>
              <Meter
                value={(latestGnn?.avg_score ?? 0) / 100}
                label="Current avg GNN risk"
                tone="var(--accent)"
              />
              <div style={{ marginTop: 8 }}>
                <Meter
                  value={(latestGnn?.max_score ?? 0) / 100}
                  label="Current max GNN risk"
                  tone="var(--danger)"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Event Volume Timeline ──────────────────────────────────────────── */}
      {event_volume_series.length > 0 && (
        <div className="panel">
          <div className="panel-header">
            <h3>Multi-Source Event Volume</h3>
            <span className="muted">
              {volTotal.toLocaleString()} total events across {event_volume_series.length} days
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px,1fr))", gap: 16 }}>
            {CATS.map(cat => {
              const series = catSeries(cat);
              const total = series.reduce((a, b) => a + b, 0);
              if (total === 0) return null;
              return (
                <div key={cat}>
                  <p style={{ fontSize: "0.76rem", fontWeight: 600, color: CATEGORY_COLOR[cat], marginBottom: 4 }}>
                    {CATEGORY_LABEL[cat]}
                  </p>
                  <Sparkline data={series} height={48} stroke={CATEGORY_COLOR[cat]} />
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 2 }}>
                    <span className="muted" style={{ fontSize: "0.68rem" }}>
                      {fmtDate(event_volume_series[0]?.date ?? "")}
                    </span>
                    <span style={{ fontSize: "0.72rem", fontWeight: 600, color: CATEGORY_COLOR[cat] }}>
                      {total.toLocaleString()} total
                    </span>
                    <span className="muted" style={{ fontSize: "0.68rem" }}>
                      {fmtDate(event_volume_series[event_volume_series.length - 1]?.date ?? "")}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Campaign Risk + Kill Chain ─────────────────────────────────────── */}
      <div className="grid-two">

        {/* Campaign severity */}
        <div className="panel">
          <div className="panel-header">
            <h3>Campaign Risk Severity</h3>
            <span className="muted">{campaign_risk.total} GNN-detected campaigns</span>
          </div>
          {campaign_risk.total === 0 ? (
            <p className="muted">No campaign risk data yet.</p>
          ) : (
            <>
              {(["critical", "high", "medium", "low"] as const).map(sev => {
                const count = campaign_risk[sev];
                if (count === 0) return null;
                const pct = count / campaign_risk.total;
                return (
                  <div key={sev} style={{ marginBottom: 10 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                      <span style={{ fontSize: "0.8rem", fontWeight: 600, color: SEVERITY_COLOR[sev],
                        textTransform: "uppercase", letterSpacing: "0.5px" }}>{sev}</span>
                      <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>{count}</span>
                    </div>
                    <div style={{ height: 6, borderRadius: 4, background: "var(--line)", overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${pct * 100}%`,
                        background: SEVERITY_COLOR[sev], borderRadius: 4 }} />
                    </div>
                  </div>
                );
              })}
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <button className="ghost" type="button" onClick={onOpenCampaign}>
                  View campaigns →
                </button>
              </div>
            </>
          )}
        </div>

        {/* Kill-chain stage distribution */}
        <div className="panel">
          <div className="panel-header">
            <h3>Kill-Chain Stage Distribution</h3>
            <span className="muted">GNN-classified entity stages</span>
          </div>
          {orderedKC.length === 0 ? (
            <p className="muted">No kill-chain data yet.</p>
          ) : (
            <>
              {orderedKC.map(({ key, count, pct }) => (
                <div key={key} style={{ marginBottom: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                    <span style={{ fontSize: "0.78rem" }}>{KILL_CHAIN_LABEL[key] ?? key}</span>
                    <span className="muted" style={{ fontSize: "0.72rem" }}>
                      {count} · {Math.round(pct * 100)}%
                    </span>
                  </div>
                  <div style={{ height: 5, borderRadius: 3, background: "var(--line)", overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${pct * 100}%`,
                      background: "var(--accent-2)", borderRadius: 3 }} />
                  </div>
                </div>
              ))}
              <div style={{ marginTop: 12 }}>
                <button className="ghost" type="button" onClick={onShowInfra}>
                  View infra clusters →
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Top at-risk entities ───────────────────────────────────────────── */}
      {top_threats.length > 0 && (
        <div className="panel">
          <div className="panel-header">
            <h3>Top At-Risk Entities</h3>
            <span className="muted">Highest GNN scores — requires forensic corroboration before action</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px,1fr))", gap: 10 }}>
            {top_threats.map(entity => (
              <div key={entity.entity_key} style={{
                border: "1px solid var(--line)", borderRadius: 10, padding: "10px 12px",
                borderLeftWidth: 3,
                borderLeftColor: SEVERITY_COLOR[entity.severity] ?? "var(--line)",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 5 }}>
                  <p style={{ fontWeight: 700, fontSize: "0.82rem", wordBreak: "break-all", flex: 1 }}>
                    {entity.entity_key}
                  </p>
                  <span style={{
                    fontSize: "0.72rem", fontWeight: 700, padding: "1px 7px", borderRadius: 6,
                    background: (SEVERITY_COLOR[entity.severity] ?? "var(--ink-muted)") + "22",
                    color: SEVERITY_COLOR[entity.severity] ?? "var(--ink-muted)",
                    marginLeft: 8, flexShrink: 0,
                  }}>
                    {entity.score.toFixed(0)}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <span className="chip" style={{ fontSize: "0.68rem", padding: "1px 5px" }}>
                    {entity.entity_type}
                  </span>
                  {entity.kill_chain_stage && (
                    <span className="chip" style={{ fontSize: "0.68rem", padding: "1px 5px" }}>
                      {KILL_CHAIN_LABEL[entity.kill_chain_stage] ?? entity.kill_chain_stage}
                    </span>
                  )}
                  <span className="chip" style={{
                    fontSize: "0.68rem", padding: "1px 5px",
                    color: SEVERITY_COLOR[entity.severity],
                  }}>
                    {entity.severity}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Legacy DDoS indicators (fallback / supplemental) ──────────────── */}
      {indicators.length > 0 && (() => {
        const current = indicators.find(i => i.serviceId === selectedService) ?? indicators[0];
        const idx     = current.reqRate.length - 1;
        return (
          <div className="panel">
            <div className="panel-header">
              <h3>DDoS Service Indicators</h3>
              <div className="chip-row">
                {indicators.map(item => (
                  <button key={item.serviceId} type="button"
                    className={item.serviceId === selectedService ? "chip active" : "chip ghost"}
                    onClick={() => onSelectService(item.serviceId)}>
                    {item.serviceId}
                  </button>
                ))}
                <div className={stageClass(current.stage)}>Stage: {stageLabel(current.stage)}</div>
              </div>
            </div>
            <div className="grid-three">
              <div>
                <p className="label">Request rate (now)</p>
                <p className="stat">{current.reqRate[idx]}/min</p>
                <Sparkline data={current.reqRate} height={48} />
              </div>
              <div>
                <p className="label">Unique IPs</p>
                <p className="stat">{current.uniqueIps[idx]}</p>
                <Sparkline data={current.uniqueIps} height={48} stroke="var(--accent-2)" />
              </div>
              <div>
                <p className="label">AI scores</p>
                <p className="stat mono">{formatScore(current.anomalyScore[idx])} anom · {formatPercent(current.ddosRisk[idx], 2)} DDoS</p>
                <Meter value={current.ddosRisk[idx]} label="DDoS risk" />
              </div>
            </div>
            <div className="factors" style={{ marginTop: 12 }}>
              {current.factors.map(f => <span key={f} className="factor">{f}</span>)}
            </div>
            {evidenceRefs.length > 0 && (
              <div className="panel-subsection" style={{ marginTop: 12 }}>
                <h4>Evidence refs</h4>
                <div className="list">
                  {evidenceRefs.slice(0, 5).map(ref => (
                    <div key={ref} className="list-item mono" style={{ fontSize: "0.72rem" }}>{ref}</div>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })()}

    </section>
  );
}
