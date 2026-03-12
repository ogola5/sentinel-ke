import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  Globe,
  Loader,
  Network,
  Radio,
  RefreshCw,
  Shield,
  TrendingUp,
  Users,
} from "lucide-react";

import { fetchFederationCorrelations, fetchFederationPartners } from "../../api/federation";
import { apiListUsers } from "../../api/auth";
import { agencyColor, agencyName, type AuthUser, KENYA_AGENCIES } from "../../types/auth";
import type { FederationCorrelation, FederationPartner } from "../../types/federation";
import type { ThreatSummary } from "../../types/domain";
import type { OperationsSnapshot } from "../../types/operations";
import { formatRiskScore, isHighRisk } from "../../utils/risk";

interface Props {
  operationsData: OperationsSnapshot;
  activeCampaignCount: number;
  activeEventCount: number;
  healthGnnLoaded: boolean;
  healthModelVersion: string | null;
  threatSummaryData: ThreatSummary;
  onNavigate: (screen: string) => void;
}

type CommandView = "brief" | "network" | "readiness";

const ALL_AGENCIES = Object.keys(KENYA_AGENCIES);

function threatLevel(critCount: number, highCount: number): { level: string; color: string; note: string } {
  if (critCount > 0) {
    return { level: "CRITICAL", color: "var(--risk-critical)", note: "Immediate coordination required." };
  }
  if (highCount > 5) {
    return { level: "HIGH", color: "var(--risk-high)", note: "Elevated cross-agency pressure." };
  }
  if (highCount > 0) {
    return { level: "ELEVATED", color: "var(--risk-medium)", note: "Multiple queues need review." };
  }
  return { level: "GUARDED", color: "var(--accent)", note: "No critical queue is active right now." };
}

function CommandStat({
  label,
  value,
  icon,
  tone,
}: {
  label: string;
  value: number | string;
  icon: ReactNode;
  tone?: string;
}) {
  return (
    <div className="metric-card">
      <div className="metric-label" style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {icon}
        {label}
      </div>
      <div className="metric-value" style={{ color: tone }}>{value}</div>
    </div>
  );
}

export default function CentralCommand({
  operationsData,
  activeCampaignCount,
  activeEventCount,
  healthGnnLoaded,
  healthModelVersion,
  threatSummaryData,
  onNavigate,
}: Props) {
  const [view, setView] = useState<CommandView>("brief");
  const [partners, setPartners] = useState<FederationPartner[]>([]);
  const [correlations, setCorrelations] = useState<FederationCorrelation[]>([]);
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const [partnerRows, correlationRows, userRows] = await Promise.all([
      fetchFederationPartners(),
      fetchFederationCorrelations(20),
      apiListUsers().then((r) => r.items).catch(() => [] as AuthUser[]),
    ]);
    setPartners(partnerRows);
    setCorrelations(correlationRows);
    setUsers(userRows);
    setLoading(false);
  };

  useEffect(() => {
    void load();
  }, []);

  const criticalQueueCount =
    threatSummaryData.campaign_risk.critical +
    operationsData.integrityAlerts.filter((item) => item.severity.toLowerCase() === "critical").length;
  const highQueueCount =
    threatSummaryData.campaign_risk.high +
    operationsData.procurementAnomalies.filter((item) => item.severity.toLowerCase() === "high").length +
    operationsData.predictions.filter((item) => isHighRisk(item.score)).length;
  const nationalThreat = threatLevel(criticalQueueCount, highQueueCount);

  const onlinePartnerIds = new Set(partners.filter((item) => item.is_active).map((item) => item.partner_id.toUpperCase()));
  const agencyUserCounts = ALL_AGENCIES.map((code) => ({
    code,
    label: code,
    count: users.filter((user) => user.section_code === code && user.is_active).length,
  })).filter((item) => item.count > 0);

  const topThreats = useMemo(
    () => threatSummaryData.top_threats.slice(0, 6),
    [threatSummaryData.top_threats],
  );
  const forecast = threatSummaryData.forecast;
  const highRiskPredictions = operationsData.predictions.filter((item) => isHighRisk(item.score));
  const blockedGuardrails = operationsData.guardrailDecisions.filter((item) => item.decision === "block");
  const mfaEnabled = users.filter((item) => item.mfa_enabled).length;
  const lockedCount = users.filter((item) => item.locked_until).length;
  const centralUsers = users.filter((item) => item.access_level === "central").length;
  const sectionUsers = users.filter((item) => item.access_level === "section").length;

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">C1</p>
          <h2>National Command Centre</h2>
          <p className="subtle">
            A lean national view: first understand the threat level, then the network, then readiness.
          </p>
        </div>
        <div className="screen-header-actions">
          <div className="chip-row">
            {[
              { id: "brief", label: "National Brief" },
              { id: "network", label: "Agency Network" },
              { id: "readiness", label: "Readiness" },
            ].map((item) => (
              <button
                key={item.id}
                type="button"
                className={view === item.id ? "chip active" : "chip ghost"}
                onClick={() => setView(item.id as CommandView)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button className="ghost" type="button" onClick={() => void load()} disabled={loading}>
            {loading ? <Loader size={14} className="spin" /> : <RefreshCw size={14} />}
            &nbsp;Refresh
          </button>
        </div>
      </div>

      <div
        className="panel"
        style={{
          borderColor: nationalThreat.color,
          background: `${nationalThreat.color}10`,
        }}
      >
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div>
            <p className="label">National threat level</p>
            <p style={{ fontSize: "2.2rem", fontWeight: 800, color: nationalThreat.color, margin: "2px 0" }}>
              {nationalThreat.level}
            </p>
            <p className="muted">{nationalThreat.note}</p>
          </div>

          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginLeft: "auto" }}>
            <CommandStat label="Campaigns" value={activeCampaignCount} icon={<Radio size={13} />} tone="var(--warning)" />
            <CommandStat label="Live events" value={activeEventCount} icon={<Activity size={13} />} tone="var(--info)" />
            <CommandStat label="High-risk AI queue" value={highRiskPredictions.length} icon={<AlertTriangle size={13} />} tone="var(--risk-high)" />
            <CommandStat label="Cross-agency hits" value={correlations.length} icon={<Network size={13} />} tone="var(--accent)" />
          </div>
        </div>
      </div>

      {view === "brief" && (
        <>
          <div className="metric-grid">
            <CommandStat
              label="Forecast"
              value={forecast.forecast_score != null ? `${formatRiskScore(forecast.forecast_score)} / 100` : "No forecast"}
              icon={<TrendingUp size={13} />}
              tone={forecast.trend === "rising" ? "var(--risk-high)" : "var(--accent)"}
            />
            <CommandStat
              label="Critical campaign queue"
              value={threatSummaryData.campaign_risk.critical}
              icon={<AlertTriangle size={13} />}
              tone="var(--risk-critical)"
            />
            <CommandStat
              label="Leakage alerts"
              value={operationsData.leakageSummary.totalAlerts}
              icon={<Shield size={13} />}
              tone="var(--warning)"
            />
            <CommandStat
              label="Guardrail blocks"
              value={blockedGuardrails.length}
              icon={<Shield size={13} />}
              tone="var(--risk-critical)"
            />
          </div>

          <div className="grid-two">
            <div className="panel">
              <div className="panel-header">
                <h3>What needs attention first</h3>
                <span className="muted">One queue at a time</span>
              </div>
              <div className="list">
                <div className="list-item">
                  <p style={{ fontWeight: 600, marginBottom: 4 }}>AI high-risk review queue</p>
                  <p className="muted">
                    {highRiskPredictions.length} entities are above the operational review threshold.
                  </p>
                  <button className="ghost" type="button" onClick={() => onNavigate("gnn")}>
                    Open GNN Intelligence
                  </button>
                </div>
                <div className="list-item">
                  <p style={{ fontWeight: 600, marginBottom: 4 }}>Campaign escalation</p>
                  <p className="muted">
                    {threatSummaryData.campaign_risk.critical} critical and {threatSummaryData.campaign_risk.high} high campaign indicators are active.
                  </p>
                  <button className="ghost" type="button" onClick={() => onNavigate("campaigns")}>
                    Open Campaigns
                  </button>
                </div>
                <div className="list-item">
                  <p style={{ fontWeight: 600, marginBottom: 4 }}>Operational integrity</p>
                  <p className="muted">
                    {operationsData.integrityAlerts.length} integrity alerts and KES{" "}
                    {operationsData.leakageSummary.suspectedAmountTotal.toLocaleString()} suspected leakage in the current window.
                  </p>
                  <button className="ghost" type="button" onClick={() => onNavigate("ops")}>
                    Open Operations
                  </button>
                </div>
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3>Top threat entities</h3>
                <span className="muted">{topThreats.length} shown</span>
              </div>
              {topThreats.length === 0 ? (
                <div className="state-box">
                  <Globe size={22} />
                  <p>No threat entities available yet.</p>
                </div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Entity</th>
                      <th>Type</th>
                      <th>Score</th>
                      <th>Stage</th>
                      <th>Severity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topThreats.map((item) => (
                      <tr key={item.entity_key}>
                        <td className="mono" style={{ fontSize: "0.78rem" }}>{item.entity_key}</td>
                        <td className="muted">{item.entity_type}</td>
                        <td>{formatRiskScore(item.score)}</td>
                        <td>{item.kill_chain_stage ?? "—"}</td>
                        <td><span className={`risk-badge ${item.severity.toLowerCase()}`}>{item.severity}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}

      {view === "network" && (
        <>
          <div className="panel">
            <div className="panel-header">
              <h3>Agency network status</h3>
              <span className="muted">{onlinePartnerIds.size} / {ALL_AGENCIES.length} active partners</span>
            </div>
            <div className="agency-presence-grid">
              {ALL_AGENCIES.map((code) => {
                const online = onlinePartnerIds.has(code);
                const color = agencyColor(code);
                const partner = partners.find((item) => item.partner_id.toUpperCase() === code);
                return (
                  <div key={code} className={`agency-presence-card ${online ? "online" : "offline"}`}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontFamily: "JetBrains Mono, monospace", fontWeight: 700, color: online ? color : "var(--ink-muted)" }}>
                        {code}
                      </span>
                      <span className={`status-dot ${online ? "live" : "offline"}`} />
                    </div>
                    <div style={{ fontSize: "0.72rem", opacity: 0.7, marginTop: 4 }}>{agencyName(code)}</div>
                    <div className="muted" style={{ marginTop: 6 }}>
                      {partner?.last_seen_at ? `Last seen ${new Date(partner.last_seen_at).toLocaleDateString("en-KE")}` : "Not registered"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="grid-two">
            <div className="panel">
              <div className="panel-header">
                <h3>Cross-agency correlations</h3>
                <span className="muted">{correlations.length} active matches</span>
              </div>
              {correlations.length === 0 ? (
                <div className="state-box">
                  <Network size={22} />
                  <p>No active cross-agency correlations yet.</p>
                </div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Entity hash</th>
                      <th>Partners</th>
                      <th>Risk</th>
                      <th>Last seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {correlations.slice(0, 8).map((item) => (
                      <tr key={item.entity_key_hash}>
                        <td className="mono" style={{ fontSize: "0.78rem" }}>{item.entity_key_hash.slice(0, 16)}…</td>
                        <td>{item.partner_count} · <span className="muted">{item.partner_ids.join(", ")}</span></td>
                        <td><span className={`risk-badge ${item.risk_level.toLowerCase()}`}>{item.risk_level}</span></td>
                        <td className="muted">{new Date(item.last_seen).toLocaleDateString("en-KE")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3>Partner coverage</h3>
                <span className="muted">Active user footprint</span>
              </div>
              <div className="list">
                {agencyUserCounts.length === 0 ? (
                  <div className="state-box">
                    <Users size={22} />
                    <p>No active agency users found.</p>
                  </div>
                ) : (
                  agencyUserCounts.slice(0, 8).map((item) => (
                    <div key={item.code} className="list-item" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div>
                        <p style={{ fontWeight: 600, marginBottom: 2 }}>{item.label}</p>
                        <p className="muted">{agencyName(item.code)}</p>
                      </div>
                      <span className="stat mono">{item.count}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {view === "readiness" && (
        <div className="grid-three">
          <div className="panel">
            <div className="panel-header">
              <h3>Identity readiness</h3>
              <span className="muted">People and access</span>
            </div>
            <div className="list">
              <div className="list-item"><strong>{centralUsers}</strong> central users</div>
              <div className="list-item"><strong>{sectionUsers}</strong> agency users</div>
              <div className="list-item"><strong>{mfaEnabled}</strong> MFA-enrolled users</div>
              <div className="list-item"><strong>{lockedCount}</strong> locked accounts</div>
            </div>
            <button className="ghost" type="button" onClick={() => onNavigate("users")}>
              Open User Management
            </button>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Model readiness</h3>
              <span className="muted">AI and explainability</span>
            </div>
            <div className="list">
              <div className="list-item"><strong>{healthGnnLoaded ? "Loaded" : "Offline"}</strong> primary GNN artifact</div>
              <div className="list-item"><strong>{healthModelVersion ?? "—"}</strong> active model version</div>
              <div className="list-item"><strong>{operationsData.predictions.length}</strong> predictions in current operational snapshot</div>
              <div className="list-item"><strong>{highRiskPredictions.length}</strong> predictions above operational threshold</div>
            </div>
            <button className="ghost" type="button" onClick={() => onNavigate("gnn")}>
              Open GNN Intelligence
            </button>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Economic integrity</h3>
              <span className="muted">Public-sector risk</span>
            </div>
            <div className="list">
              <div className="list-item"><strong>{operationsData.procurementAnomalies.length}</strong> procurement anomalies</div>
              <div className="list-item"><strong>{operationsData.integrityAlerts.length}</strong> integrity alerts</div>
              <div className="list-item"><strong>{operationsData.leakageSummary.totalAlerts}</strong> leakage alerts</div>
              <div className="list-item">
                <strong>KES {operationsData.leakageSummary.suspectedAmountTotal.toLocaleString()}</strong> suspected amount
              </div>
            </div>
            <button className="ghost" type="button" onClick={() => onNavigate("reports")}>
              Open Reports
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
