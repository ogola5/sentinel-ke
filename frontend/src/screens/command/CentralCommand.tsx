import { useEffect, useState } from "react";
import {
  Globe, RefreshCw, Loader, Shield, AlertTriangle,
  Activity, Users, Radio, Network, TrendingUp,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
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
  const [partners, setPartners]         = useState<FederationPartner[]>([]);
  const [correlations, setCorrelations] = useState<FederationCorrelation[]>([]);
  const [users, setUsers]               = useState<AuthUser[]>([]);
  const [loading, setLoading]           = useState(true);

  const load = async () => {
    setLoading(true);
    const [p, c, u] = await Promise.all([
      fetchFederationPartners(),
      fetchFederationCorrelations(20),
      apiListUsers().then((r) => r.items).catch(() => [] as AuthUser[]),
    ]);
    setPartners(p);
    setCorrelations(c);
    setUsers(u);
    setLoading(false);
  };

  useEffect(() => { void load(); }, []);

  // Compute threat level from all data
  const critCount =
    operationsData.integrityAlerts.filter((a) => a.severity === "critical").length +
    correlations.filter((c) => c.risk_level.toLowerCase() === "critical").length;
  const highCount =
    operationsData.procurementAnomalies.filter((a) => a.severity === "high").length +
    correlations.filter((c) => c.risk_level.toLowerCase() === "high").length;
  const { level: ntl, color: ntlColor } = threatLevel(critCount, highCount);

  // Which agencies are online (appear in federation partners)
  const onlineIds = new Set(partners.filter((p) => p.is_active).map((p) => p.partner_id.toUpperCase()));

  // Per-agency user counts
  const agencyUserCounts = ALL_AGENCIES.map((code) => ({
    code,
    name: code,
    users: users.filter((u) => u.section_code === code && u.is_active).length,
  }));

  // User role breakdown
  const roleBreakdown = ["admin", "analyst", "operator", "auditor"].map((role) => ({
    role,
    count: users.filter((u) => u.role === role).length,
  }));

  const centralUsers  = users.filter((u) => u.access_level === "central").length;
  const sectionUsers  = users.filter((u) => u.access_level === "section").length;
  const mfaEnabled    = users.filter((u) => u.mfa_enabled).length;
  const lockedCount   = users.filter((u) => u.locked_until).length;

  return (
    <div>
      {/* Header */}
      <div className="screen-header">
        <h2>
          <Globe size={20} color="var(--accent)" />
          National Command Centre
          <span className="subtitle">— cross-agency view · central access only</span>
        </h2>
        <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader size={13} /> : <RefreshCw size={13} />}
          &nbsp;Refresh
        </button>
      </div>

      {/* National Threat Level banner */}
      <div
        className="panel"
        style={{
          marginBottom: 16,
          borderColor: ntlColor,
          background: `${ntlColor}0d`,
          padding: "20px 24px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20, flexWrap: "wrap" }}>
          <div>
            <p style={{ fontSize: "0.65rem", letterSpacing: "0.14em", opacity: 0.55, textTransform: "uppercase" }}>
              National Threat Level
            </p>
            <div style={{ fontSize: "2.4rem", fontWeight: 900, color: ntlColor, letterSpacing: "0.04em", fontFamily: "JetBrains Mono, monospace" }}>
              {ntl}
            </div>
          </div>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginLeft: "auto" }}>
            <Stat label="Active campaigns" value={activeCampaignCount} icon={<Radio size={14} />} color="var(--warning)" />
            <Stat label="Live events" value={activeEventCount} icon={<Activity size={14} />} color="var(--info)" />
            <Stat label="Critical alerts" value={critCount} icon={<AlertTriangle size={14} />} color="var(--risk-critical)" />
            <Stat label="Cross-agency hits" value={correlations.length} icon={<Network size={14} />} color="var(--accent)" />
          </div>
        </div>
      </div>

      {/* Agency presence grid */}
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-header">
          <h3><Shield size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />Agency Network Status</h3>
          <span className="muted">{onlineIds.size} / {ALL_AGENCIES.length} online</span>
        </div>
        <div className="agency-presence-grid">
          {ALL_AGENCIES.map((code) => {
            const online = onlineIds.has(code);
            const color = agencyColor(code);
            const partner = partners.find((p) => p.partner_id.toUpperCase() === code);
            return (
              <div key={code} className={`agency-presence-card ${online ? "online" : "offline"}`}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span
                    style={{
                      fontFamily: "JetBrains Mono, monospace",
                      fontSize: "1rem",
                      fontWeight: 700,
                      color: online ? color : "var(--ink-muted)",
                    }}
                  >
                    {code}
                  </span>
                  <span className={`status-dot ${online ? "live" : "offline"}`} />
                </div>
                <div style={{ fontSize: "0.68rem", opacity: 0.6, marginTop: 4, lineHeight: 1.4 }}>
                  {agencyName(code)}
                </div>
                <div style={{ fontSize: "0.68rem", marginTop: 6, opacity: 0.5 }}>
                  {partner ? (
                    `Last: ${new Date(partner.last_seen_at ?? "").toLocaleDateString()}`
                  ) : (
                    "Not registered"
                  )}
                </div>
              </div>
            );
          })}
          {/* CENTRAL */}
          <div className="agency-presence-card online" style={{ borderColor: "var(--accent)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: "1rem", fontWeight: 700, color: "var(--accent)" }}>
                CENTRAL
              </span>
              <span className="status-dot live" />
            </div>
            <div style={{ fontSize: "0.68rem", opacity: 0.6, marginTop: 4, lineHeight: 1.4 }}>
              National Command Centre
            </div>
            <div style={{ fontSize: "0.68rem", marginTop: 6, opacity: 0.5 }}>Hub instance</div>
          </div>
        </div>
      </div>

      {/* Charts row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
        {/* Users by agency */}
        <div className="panel">
          <div className="panel-header">
            <h3><Users size={13} style={{ verticalAlign: "middle", marginRight: 6 }} />Users by Agency</h3>
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

        {/* Role breakdown */}
        <div className="panel">
          <div className="panel-header">
            <h3>Role Distribution</h3>
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
      </div>

      {/* IAM + GNN status row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
        {/* IAM summary */}
        <div className="panel">
          <div className="panel-header"><h3>Identity & Access</h3></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <MetricRow label="Central users"  value={centralUsers}  color="var(--accent)" />
            <MetricRow label="Agency users"   value={sectionUsers}  color="var(--info)" />
            <MetricRow label="MFA enrolled"   value={mfaEnabled}    color="var(--accent)" />
            <MetricRow label="Locked accounts" value={lockedCount}  color={lockedCount > 0 ? "var(--danger)" : undefined} />
          </div>
          <button
            className="btn-ghost"
            style={{ marginTop: 12, fontSize: "0.75rem", width: "100%" }}
            onClick={() => onNavigate("users")}
          >
            User Management →
          </button>
        </div>

        {/* GNN status */}
        <div className="panel">
          <div className="panel-header"><h3>GNN Model Status</h3></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <MetricRow label="Model loaded" value={healthGnnLoaded ? "✓ Active" : "✗ Offline"} color={healthGnnLoaded ? "var(--accent)" : "var(--danger)"} />
            {healthModelVersion && <MetricRow label="Version" value={healthModelVersion} mono />}
            <MetricRow label="Predictions" value={operationsData.predictions.length} />
            <MetricRow label="High-risk" value={operationsData.predictions.filter((p) => p.score >= 0.7).length} color="var(--risk-high)" />
          </div>
          <button
            className="btn-ghost"
            style={{ marginTop: 12, fontSize: "0.75rem", width: "100%" }}
            onClick={() => onNavigate("gnn")}
          >
            GNN Intelligence →
          </button>
        </div>

        {/* Corruption posture */}
        <div className="panel">
          <div className="panel-header"><h3>Economic Integrity</h3></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <MetricRow label="Procurement anomalies" value={operationsData.procurementAnomalies.length} color="var(--warning)" />
            <MetricRow label="Integrity alerts" value={operationsData.integrityAlerts.length} color="var(--risk-critical)" />
            <MetricRow label="Leakage alerts" value={operationsData.leakageAlerts.length} color="var(--risk-high)" />
            <MetricRow label="Guardrail blocks" value={operationsData.guardrailDecisions.filter((g) => g.decision === "block").length} color="var(--danger)" />
          </div>
          <button
            className="btn-ghost"
            style={{ marginTop: 12, fontSize: "0.75rem", width: "100%" }}
            onClick={() => onNavigate("corruption")}
          >
            Corruption Intel →
          </button>
        </div>
      </div>

      {/* Cross-agency correlations */}
      {correlations.length > 0 && (
        <div className="panel">
          <div className="panel-header">
            <h3><TrendingUp size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />Cross-Agency Threat Correlations</h3>
            <span className="muted">{correlations.length} matched entity hashes</span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Entity hash</th>
                <th>Partners</th>
                <th>Agency IDs</th>
                <th>Max confidence</th>
                <th>Risk level</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {correlations.slice(0, 8).map((c) => (
                <tr key={c.entity_key_hash}>
                  <td><span className="mono" style={{ fontSize: "0.78rem" }}>{c.entity_key_hash.slice(0, 16)}…</span></td>
                  <td>
                    <span style={{ fontWeight: 700, color: c.partner_count >= 3 ? "var(--danger)" : "var(--warning)" }}>
                      {c.partner_count}
                    </span>
                  </td>
                  <td className="muted" style={{ fontSize: "0.75rem" }}>{c.partner_ids.join(", ")}</td>
                  <td style={{ fontSize: "0.8rem" }}>{c.max_confidence.toFixed(2)}</td>
                  <td>
                    <span className={`risk-badge ${c.risk_level.toLowerCase()}`}>{c.risk_level}</span>
                  </td>
                  <td className="muted" style={{ fontSize: "0.76rem" }}>
                    {new Date(c.last_seen).toLocaleDateString("en-KE")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            className="btn-ghost"
            style={{ marginTop: 10, fontSize: "0.75rem" }}
            onClick={() => onNavigate("federation")}
          >
            Full Federation Dashboard →
          </button>
        </div>
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

function Stat({ label, value, icon, color }: { label: string; value: number | string; icon?: React.ReactNode; color?: string }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4, justifyContent: "center", opacity: 0.6, fontSize: "0.7rem", textTransform: "uppercase" }}>
        {icon}{label}
      </div>
      <div style={{ fontSize: "1.6rem", fontWeight: 800, color: color ?? "var(--ink)", fontFamily: "JetBrains Mono, monospace" }}>
        {value}
      </div>
    </div>
  );
}

function MetricRow({ label, value, color, mono }: { label: string; value: string | number; color?: string; mono?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.82rem" }}>
      <span className="muted">{label}</span>
      <span style={{ color: color ?? "var(--ink)", fontFamily: mono ? "JetBrains Mono, monospace" : undefined }}>
        {value}
      </span>
    </div>
  );
}
