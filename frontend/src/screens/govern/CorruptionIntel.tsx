import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid } from "recharts";
import { Building2, AlertTriangle, TrendingUp, Shield } from "lucide-react";
import type { OperationsSnapshot } from "../../types/operations";

const RISK_COLORS = ["#ff4d5a", "#ff8c42", "#ffd147", "#31ff90", "#88b79b"];

function severityColor(sev: string): string {
  const s = sev.toLowerCase();
  if (s === "critical") return "var(--risk-critical)";
  if (s === "high") return "var(--risk-high)";
  if (s === "medium") return "var(--risk-medium)";
  return "var(--risk-low)";
}

function riskClass(sev: string): string {
  const s = sev.toLowerCase();
  if (s === "critical") return "critical";
  if (s === "high") return "high";
  if (s === "medium") return "medium";
  return "low";
}

interface Props {
  data: OperationsSnapshot;
  onRunLeakage: () => void;
  leakageActionLabel: string;
}

export default function CorruptionIntel({ data, onRunLeakage, leakageActionLabel }: Props) {
  const ls = data.leakageSummary;

  const byDetectorData = ls
    ? Object.entries(ls.byDetector).map(([key, val]) => ({
        name: key.replace(/_/g, " "),
        value: val,
      }))
    : [];

  const bySeverityData = ls
    ? Object.entries(ls.bySeverity).map(([sev, count], i) => ({
        name: sev,
        count,
        fill: RISK_COLORS[i % RISK_COLORS.length],
      }))
    : [];

  const totalSuspectedKsh = ls?.suspectedAmountTotal ?? 0;
  const totalLeakageAlerts = ls?.totalAlerts ?? data.leakageAlerts.length;

  return (
    <div>
      <div className="screen-header">
        <h2>
          <Building2 size={20} color="var(--warning)" />
          Corruption Intelligence
          <span className="subtitle">— procurement · ghost workers · tender cartels · IFMIS leakage</span>
        </h2>
        <button className="btn-accent" onClick={onRunLeakage}>
          <TrendingUp size={13} /> &nbsp;{leakageActionLabel}
        </button>
      </div>

      {/* Leakage summary banner */}
      {ls && (
        <div className="panel" style={{ marginBottom: 16, borderColor: "rgba(255,209,71,.32)" }}>
          <div style={{ display: "flex", gap: 32, alignItems: "center", flexWrap: "wrap" }}>
            <div>
              <div className="metric-label">Window</div>
              <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{ls.windowDays} days</div>
            </div>
            <div>
              <div className="metric-label">Total alerts</div>
              <div style={{ fontWeight: 700, fontSize: "1.4rem", color: "var(--warning)" }}>{ls.totalAlerts}</div>
            </div>
            <div>
              <div className="metric-label">Suspected leakage</div>
              <div style={{ fontWeight: 700, fontSize: "1.4rem", color: "var(--danger)" }}>
                KES {totalSuspectedKsh.toLocaleString()}
              </div>
            </div>
            <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
              {Object.entries(ls.bySeverity).map(([sev, count]) =>
                count > 0 ? (
                  <span key={sev} className={`risk-badge ${riskClass(sev)}`}>
                    {count} {sev}
                  </span>
                ) : null,
              )}
            </div>
          </div>
        </div>
      )}

      {/* Metric cards */}
      <div className="metric-grid">
        <div className="metric-card warn">
          <div className="metric-label">Procurement anomalies</div>
          <div className="metric-value">{data.procurementAnomalies.length}</div>
          <div className="metric-sub">Inflated tenders / cartels</div>
        </div>
        <div className="metric-card warn">
          <div className="metric-label">Guardrail decisions</div>
          <div className="metric-value">{data.guardrailDecisions.length}</div>
          <div className="metric-sub">Auto-blocked transactions</div>
        </div>
        <div className="metric-card danger">
          <div className="metric-label">Integrity alerts</div>
          <div className="metric-value">{data.integrityAlerts.length}</div>
          <div className="metric-sub">IFMIS / payroll anomalies</div>
        </div>
        <div className="metric-card danger">
          <div className="metric-label">Leakage alerts</div>
          <div className="metric-value">{totalLeakageAlerts}</div>
          <div className="metric-sub">Cross-agency fund tracing</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Economy signals</div>
          <div className="metric-value">{data.economySignals.length}</div>
          <div className="metric-sub">Macro / sector signals</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">AI predictions</div>
          <div className="metric-value">{data.predictions.length}</div>
          <div className="metric-sub">Corruption risk scores</div>
        </div>
      </div>

      {/* Charts row */}
      {(byDetectorData.length > 0 || bySeverityData.length > 0) && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div className="panel">
            <div className="panel-header">
              <h3>Leakage by Detector</h3>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={byDetectorData} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 9, fill: "var(--ink-muted)" }} />
                <YAxis tick={{ fontSize: 10, fill: "var(--ink-muted)" }} />
                <Tooltip
                  contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                />
                <Bar dataKey="value" fill="var(--warning)" opacity={0.8} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="panel">
            <div className="panel-header">
              <h3>Alerts by Severity</h3>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={bySeverityData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  dataKey="count"
                  nameKey="name"
                >
                  {bySeverityData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                  formatter={(v: number | string | undefined, name: string | undefined) => [v ?? 0, name ?? ""]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Procurement anomalies */}
      {data.procurementAnomalies.length > 0 && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div className="panel-header">
            <h3>Procurement Anomalies</h3>
            <span className="muted">{data.procurementAnomalies.length} detected</span>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Tender ID</th>
                  <th>Vendor</th>
                  <th>Agency</th>
                  <th>Severity</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {data.procurementAnomalies.slice(0, 15).map((a) => (
                  <tr key={a.id}>
                    <td><span className="mono" style={{ fontSize: "0.78rem" }}>{a.tenderId}</span></td>
                    <td className="muted" style={{ fontSize: "0.78rem" }}>{a.vendorId}</td>
                    <td className="muted" style={{ fontSize: "0.78rem" }}>{a.agency}</td>
                    <td>
                      <span className={`risk-badge ${riskClass(a.severity)}`}>{a.severity}</span>
                    </td>
                    <td>
                      <div className="score-bar-wrap">
                        <div className="score-bar-track">
                          <div
                            className="score-bar-fill"
                            style={{ width: `${a.score * 100}%`, background: severityColor(a.severity) }}
                          />
                        </div>
                        <span style={{ fontSize: "0.76rem", minWidth: 30 }}>{a.score.toFixed(2)}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Guardrail decisions */}
      {data.guardrailDecisions.length > 0 && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div className="panel-header">
            <h3>
              <Shield size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />
              Guardrail Decisions
            </h3>
            <span className="muted">AI-flagged transaction controls</span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Tender ID</th>
                <th>Vendor</th>
                <th>Decision</th>
                <th>Severity</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {data.guardrailDecisions.slice(0, 10).map((g) => (
                <tr key={g.id}>
                  <td><span className="mono" style={{ fontSize: "0.78rem" }}>{g.tenderId}</span></td>
                  <td className="muted" style={{ fontSize: "0.78rem" }}>{g.vendorId}</td>
                  <td>
                    <span
                      className="risk-badge"
                      style={{
                        background: g.decision === "block" ? "rgba(255,77,90,.14)" : "rgba(255,209,71,.14)",
                        color: g.decision === "block" ? "var(--danger)" : "var(--warning)",
                        border: `1px solid ${g.decision === "block" ? "rgba(255,77,90,.3)" : "rgba(255,209,71,.3)"}`,
                      }}
                    >
                      {g.decision}
                    </span>
                  </td>
                  <td><span className={`risk-badge ${riskClass(g.severity)}`}>{g.severity}</span></td>
                  <td style={{ fontSize: "0.78rem" }}>{g.score.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Integrity alerts */}
      {data.integrityAlerts.length > 0 && (
        <div className="panel">
          <div className="panel-header">
            <h3>
              <AlertTriangle size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />
              Integrity Alerts
            </h3>
            <span className="muted">IFMIS · payroll · ghost workers</span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Source system</th>
                <th>Record type</th>
                <th>Alert type</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {data.integrityAlerts.slice(0, 12).map((a) => (
                <tr key={a.id}>
                  <td style={{ fontSize: "0.8rem" }}>{a.sourceSystem}</td>
                  <td className="muted" style={{ fontSize: "0.78rem" }}>{a.recordType}</td>
                  <td className="muted" style={{ fontSize: "0.78rem" }}>{a.alertType}</td>
                  <td><span className={`risk-badge ${riskClass(a.severity)}`}>{a.severity}</span></td>
                  <td>
                    <span className={`risk-badge ${a.status === "open" ? "high" : "low"}`}>{a.status}</span>
                  </td>
                  <td>
                    <div className="score-bar-wrap">
                      <div className="score-bar-track">
                        <div
                          className="score-bar-fill"
                          style={{ width: `${a.confidence * 100}%`, background: severityColor(a.severity) }}
                        />
                      </div>
                      <span style={{ fontSize: "0.75rem", minWidth: 30 }}>{a.confidence.toFixed(2)}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.procurementAnomalies.length === 0 &&
        data.guardrailDecisions.length === 0 &&
        data.integrityAlerts.length === 0 && (
          <div className="panel">
            <div className="state-box">
              <Building2 size={32} />
              <p>No corruption intelligence data yet.</p>
              <p style={{ fontSize: "0.8rem" }}>
                Ingest procurement, payroll and IFMIS events to start detecting anomalies.
              </p>
            </div>
          </div>
        )}
    </div>
  );
}
