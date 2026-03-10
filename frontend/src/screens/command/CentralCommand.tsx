import { useEffect, useMemo, useState } from "react";
import {
  Globe,
  RefreshCw,
  Loader,
  Shield,
  AlertTriangle,
  Activity,
  Users,
  Radio,
  Network,
  TrendingUp,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fetchFederationPartners, fetchFederationCorrelations } from "../../api/federation";
import { apiListUsers } from "../../api/auth";
import { KENYA_AGENCIES, agencyName, agencyColor } from "../../types/auth";
import type { FederationPartner, FederationCorrelation } from "../../types/federation";
import type { AuthUser } from "../../types/auth";
import type { OperationsSnapshot } from "../../types/operations";

interface Props {
  operationsData: OperationsSnapshot;
  activeCampaignCount: number;
  activeEventCount: number;
  healthGnnLoaded: boolean;
  healthModelVersion: string | null;
  onNavigate: (screen: string) => void;
}

const ALL_AGENCIES = Object.keys(KENYA_AGENCIES);

function threatLevel(critCount: number, highCount: number): { level: string; color: string } {
  if (critCount > 0) return { level: "CRITICAL", color: "var(--risk-critical)" };
  if (highCount > 2) return { level: "HIGH", color: "var(--risk-high)" };
  if (highCount > 0) return { level: "ELEVATED", color: "var(--risk-medium)" };
  return { level: "GUARDED", color: "var(--accent)" };
}

export default function CentralCommand({
  operationsData,
  activeCampaignCount,
  activeEventCount,
  healthGnnLoaded,
  healthModelVersion,
  onNavigate,
}: Props) {
  const [partners, setPartners] = useState<FederationPartner[]>([]);
  const [correlations, setCorrelations] = useState<FederationCorrelation[]>([]);
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [activePanel, setActivePanel] = useState<"national" | "agencies" | "access">("national");

  const load = async () => {
    setLoading(true);
    const [partnerRows, correlationRows, userRows] = await Promise.all([
      fetchFederationPartners(),
      fetchFederationCorrelations(20),
      apiListUsers().then((response) => response.items).catch(() => [] as AuthUser[]),
    ]);
    setPartners(partnerRows);
    setCorrelations(correlationRows);
    setUsers(userRows);
    setLoading(false);
  };

  useEffect(() => {
    void load();
  }, []);

  const critCount = useMemo(
    () =>
      operationsData.integrityAlerts.filter((alert) => alert.severity === "critical").length +
      correlations.filter((correlation) => correlation.risk_level.toLowerCase() === "critical").length,
    [correlations, operationsData.integrityAlerts],
  );
  const highCount = useMemo(
    () =>
      operationsData.procurementAnomalies.filter((anomaly) => anomaly.severity === "high").length +
      correlations.filter((correlation) => correlation.risk_level.toLowerCase() === "high").length,
    [correlations, operationsData.procurementAnomalies],
  );
  const { level: nationalThreat, color: nationalThreatColor } = threatLevel(critCount, highCount);

  const onlineIds = new Set(partners.filter((partner) => partner.is_active).map((partner) => partner.partner_id.toUpperCase()));
  const agencyUserCounts = ALL_AGENCIES.map((code) => ({
    code,
    name: code,
    users: users.filter((user) => user.section_code === code && user.is_active).length,
  }));
  const roleBreakdown = ["admin", "analyst", "operator", "auditor"].map((role) => ({
    role,
    count: users.filter((user) => user.role === role).length,
  }));

  const centralUsers = users.filter((user) => user.access_level === "central").length;
  const sectionUsers = users.filter((user) => user.access_level === "section").length;
  const mfaEnabled = users.filter((user) => user.mfa_enabled).length;
  const lockedCount = users.filter((user) => user.locked_until).length;

  return (
    <div>
      <div className="screen-header">
        <h2>
          <Globe size={20} color="var(--accent)" />
          National Command Centre
          <span className="subtitle">— leadership brief for cross-agency coordination</span>
        </h2>
        <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader size={13} /> : <RefreshCw size={13} />}
          &nbsp;Refresh
        </button>
      </div>

      <div
        className="panel command-hero"
        style={{ borderColor: nationalThreatColor, background: `${nationalThreatColor}10` }}
      >
        <div className="command-hero-head">
          <div>
            <p className="label">National threat level</p>
            <div className="command-hero-level" style={{ color: nationalThreatColor }}>{nationalThreat}</div>
            <p className="muted">Escalation is driven by integrity alerts, federated correlation hits, and procurement risk.</p>
          </div>
          <div className="command-hero-stats">
            <Stat label="Campaigns" value={activeCampaignCount} icon={<Radio size={14} />} color="var(--warning)" />
            <Stat label="Live events" value={activeEventCount} icon={<Activity size={14} />} color="var(--info)" />
            <Stat label="Critical alerts" value={critCount} icon={<AlertTriangle size={14} />} color="var(--risk-critical)" />
            <Stat label="Cross-agency hits" value={correlations.length} icon={<Network size={14} />} color="var(--accent)" />
          </div>
        </div>
      </div>

      <div className="subsection-tabs" role="tablist" aria-label="Command centre sections">
        <button type="button" className={`subsection-tab${activePanel === "national" ? " active" : ""}`} onClick={() => setActivePanel("national")}>
          National Brief
        </button>
        <button type="button" className={`subsection-tab${activePanel === "agencies" ? " active" : ""}`} onClick={() => setActivePanel("agencies")}>
          Agency Network
        </button>
        <button type="button" className={`subsection-tab${activePanel === "access" ? " active" : ""}`} onClick={() => setActivePanel("access")}>
          Access & Posture
        </button>
      </div>

      {activePanel === "national" && (
        <>
          <div className="brief-card-grid">
            <button type="button" className="brief-card" onClick={() => onNavigate("campaigns")}>
              <p className="label">Campaign pressure</p>
              <p className="metric mono">{activeCampaignCount}</p>
              <p className="muted">Open campaign clusters requiring attribution and follow-through.</p>
            </button>
            <button type="button" className="brief-card" onClick={() => onNavigate("gnn")}>
              <p className="label">AI review queue</p>
              <p className="metric mono">{operationsData.predictions.filter((item) => item.score >= 0.7).length}</p>
              <p className="muted">High-risk model outputs waiting for analyst confirmation.</p>
            </button>
            <button type="button" className="brief-card" onClick={() => onNavigate("corruption")}>
              <p className="label">Integrity attention</p>
              <p className="metric mono">{operationsData.integrityAlerts.length + operationsData.leakageAlerts.length}</p>
              <p className="muted">Combined integrity and leakage alerts across finance and procurement.</p>
            </button>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3><TrendingUp size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />Correlated threats</h3>
              <span className="muted">{correlations.length} matched entity hashes</span>
            </div>
            {correlations.length === 0 ? (
              <div className="state-box">
                <Network size={22} />
                <p>No cross-agency correlations are active right now.</p>
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Entity hash</th>
                    <th>Partners</th>
                    <th>Agencies</th>
                    <th>Risk level</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {correlations.slice(0, 8).map((correlation) => (
                    <tr key={correlation.entity_key_hash}>
                      <td><span className="mono" style={{ fontSize: "0.78rem" }}>{correlation.entity_key_hash.slice(0, 16)}…</span></td>
                      <td><span className="mono">{correlation.partner_count}</span></td>
                      <td className="muted" style={{ fontSize: "0.75rem" }}>{correlation.partner_ids.join(", ")}</td>
                      <td><span className={`risk-badge ${correlation.risk_level.toLowerCase()}`}>{correlation.risk_level}</span></td>
                      <td className="muted" style={{ fontSize: "0.76rem" }}>{new Date(correlation.last_seen).toLocaleDateString("en-KE")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {activePanel === "agencies" && (
        <>
          <div className="panel">
            <div className="panel-header">
              <h3><Shield size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />Agency network status</h3>
              <span className="muted">{onlineIds.size} / {ALL_AGENCIES.length} online</span>
            </div>
            <div className="agency-presence-grid">
              {ALL_AGENCIES.map((code) => {
                const online = onlineIds.has(code);
                const tint = agencyColor(code);
                const partner = partners.find((item) => item.partner_id.toUpperCase() === code);
                return (
                  <div key={code} className={`agency-presence-card ${online ? "online" : "offline"}`}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: "1rem", fontWeight: 700, color: online ? tint : "var(--ink-muted)" }}>
                        {code}
                      </span>
                      <span className={`status-dot ${online ? "live" : "offline"}`} />
                    </div>
                    <div style={{ fontSize: "0.68rem", opacity: 0.72, marginTop: 4, lineHeight: 1.4 }}>
                      {agencyName(code)}
                    </div>
                    <div style={{ fontSize: "0.68rem", marginTop: 6, opacity: 0.56 }}>
                      {partner ? `Last: ${new Date(partner.last_seen_at ?? "").toLocaleDateString()}` : "Not registered"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="gnn-charts-grid">
            <div className="panel">
              <div className="panel-header">
                <h3><Users size={13} style={{ verticalAlign: "middle", marginRight: 6 }} />Users by agency</h3>
                <span className="muted">{users.length} total</span>
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={agencyUserCounts} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 9, fill: "var(--ink-muted)" }} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--ink-muted)" }} />
                  <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 11 }} />
                  <Bar dataKey="users" fill="var(--info)" opacity={0.8} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="panel command-note-panel">
              <div className="panel-header">
                <h3>Network interpretation</h3>
              </div>
              <div className="list">
                <div className="list-item">Use this view to identify agencies that are offline, under-reporting, or lagging federation registration.</div>
                <div className="list-item">When an agency is offline, move to the federation dashboard before escalating incident severity.</div>
                <div className="list-item">If user distribution is thin in a critical agency, route to user management and onboarding rather than treating it as a telemetry failure.</div>
              </div>
            </div>
          </div>
        </>
      )}

      {activePanel === "access" && (
        <>
          <div className="gnn-charts-grid">
            <div className="panel">
              <div className="panel-header">
                <h3>Role distribution</h3>
                <span className="muted">Identity posture overview</span>
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={roleBreakdown} layout="vertical" margin={{ top: 4, right: 24, left: 10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" tick={{ fontSize: 10, fill: "var(--ink-muted)" }} />
                  <YAxis dataKey="role" type="category" tick={{ fontSize: 10, fill: "var(--ink-muted)" }} />
                  <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 11 }} />
                  <Bar dataKey="count" fill="var(--accent)" opacity={0.8} radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="panel">
              <div className="panel-header"><h3>Identity & Access</h3></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <MetricRow label="Central users" value={centralUsers} color="var(--accent)" />
                <MetricRow label="Agency users" value={sectionUsers} color="var(--info)" />
                <MetricRow label="MFA enrolled" value={mfaEnabled} color="var(--accent)" />
                <MetricRow label="Locked accounts" value={lockedCount} color={lockedCount > 0 ? "var(--danger)" : undefined} />
              </div>
              <button className="btn-ghost" style={{ marginTop: 12, fontSize: "0.75rem", width: "100%" }} onClick={() => onNavigate("users")}>
                User Management →
              </button>
            </div>
          </div>

          <div className="brief-card-grid">
            <button type="button" className="brief-card" onClick={() => onNavigate("gnn")}>
              <p className="label">AI posture</p>
              <p className="metric mono">{healthGnnLoaded ? "READY" : "OFFLINE"}</p>
              <p className="muted">{healthModelVersion ? `Model ${healthModelVersion}` : "No active model artifact reported."}</p>
            </button>
            <button type="button" className="brief-card" onClick={() => onNavigate("corruption")}>
              <p className="label">Integrity controls</p>
              <p className="metric mono">{operationsData.guardrailDecisions.length}</p>
              <p className="muted">Guardrail decisions and corruption-related controls in force.</p>
            </button>
            <button type="button" className="brief-card" onClick={() => onNavigate("crypto")}>
              <p className="label">Crypto posture</p>
              <p className="metric mono">Review</p>
              <p className="muted">TLS, key rotation, and post-quantum readiness live under platform posture.</p>
            </button>
          </div>
        </>
      )}

      {loading && (
        <div className="state-box">
          <Loader size={22} />
          <p>Loading command centre data…</p>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: number | string;
  icon?: React.ReactNode;
  color?: string;
}) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4, justifyContent: "center", opacity: 0.65, fontSize: "0.7rem", textTransform: "uppercase" }}>
        {icon}
        {label}
      </div>
      <div style={{ fontSize: "1.6rem", fontWeight: 800, color: color ?? "var(--ink)", fontFamily: "JetBrains Mono, monospace" }}>
        {value}
      </div>
    </div>
  );
}

function MetricRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.82rem" }}>
      <span className="muted">{label}</span>
      <span style={{ color: color ?? "var(--ink)" }}>{value}</span>
    </div>
  );
}
