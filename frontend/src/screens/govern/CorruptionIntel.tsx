import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid } from "recharts";
import { Building2, AlertTriangle, TrendingUp, Shield, Loader2 } from "lucide-react";
import ArchitectureFlow from "../../app/ArchitectureFlow";
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
  const topProcurement = data.procurementAnomalies[0] ?? null;
  const topGuardrail = data.guardrailDecisions[0] ?? null;
  const topIntegrity = data.integrityAlerts[0] ?? null;
  const waitingForFeeds =
    data.procurementAnomalies.length === 0 &&
    data.guardrailDecisions.length === 0 &&
    data.integrityAlerts.length === 0 &&
    data.leakageAlerts.length === 0 &&
    !data.availability.integrityFeedsOk &&
    !data.availability.leakageFeedsOk;
  const uniqueVendors = new Set([
    ...data.procurementAnomalies.map((item) => item.vendorId),
    ...data.guardrailDecisions.map((item) => item.vendorId),
    ...data.leakageAlerts.map((item) => item.vendorId),
  ]).size;
  const openIntegrity = data.integrityAlerts.filter((item) => item.status.toLowerCase() === "open").length;

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
  const flaggedProcurementAmount = data.procurementAnomalies.reduce(
    (sum, item) => sum + item.amount,
    0,
  );
  const hasLeakageHeadline =
    Boolean(ls) &&
    (
      (ls?.totalAlerts ?? 0) > 0 ||
      totalSuspectedKsh > 0 ||
      Object.keys(ls?.byDetector ?? {}).length > 0
    );
  const heroLabel = hasLeakageHeadline ? "Integrity pressure" : "Procurement review queue";
  const heroValue = hasLeakageHeadline ? totalSuspectedKsh : flaggedProcurementAmount;
  const heroCopy = hasLeakageHeadline
    ? `${ls?.windowDays ?? 30}-day suspected leakage exposure across procurement, payment control, and integrity review.`
    : "Leakage detectors are quiet in this window, but procurement, supplier, and integrity review queues are active and ready for investigator follow-up.";

  return (
    <div>
      <div className="screen-header">
        <h2>
          <Building2 size={20} color="var(--warning)" />
          Corruption Intelligence
          <span className="subtitle">— procurement, supplier networks, payments, and outcomes</span>
        </h2>
        <button className="btn-accent" onClick={onRunLeakage}>
          <TrendingUp size={13} /> &nbsp;{leakageActionLabel}
        </button>
      </div>

      <ArchitectureFlow
        label="Integrity flow"
        title="How the corruption view should be read"
        summary="Start from procurement and payment pressure, then read linked supplier risk, then move into integrity evidence."
        steps={[
          { stage: "Procurement", title: "Tender and award signals", detail: "Watch anomalies in awards, single-source patterns, and emergency procurement.", tone: "warning" },
          { stage: "Network", title: "Supplier linkage", detail: "Track shared directors, accounts, addresses, and family networks.", tone: "accent" },
          { stage: "Payments", title: "Disbursement and delivery", detail: "Compare payments, milestones, complaints, and execution rate.", tone: "info" },
          { stage: "Outcome", title: "Escalate for review", detail: "Push audit, legal, or anti-corruption follow-up with evidence attached.", tone: "danger" },
        ]}
      />

      {waitingForFeeds ? (
        <div className="panel state-box" style={{ marginTop: 16 }}>
          <Loader2 size={18} className="spin" />
          <div>
            <strong>Integrity feeds are syncing.</strong>
            <p className="muted" style={{ marginTop: 6 }}>
              Sentinel-KE is still loading procurement, guardrail, and integrity review records for this workspace. If you open this screen immediately after sign-in, give it a moment or tap <span className="mono-inline">Resync</span> before presenting it.
            </p>
          </div>
        </div>
      ) : null}

      <div className="focus-layout">
        <div className="panel focus-hero focus-hero-warning">
          <p className="focus-kicker">{heroLabel}</p>
          <p className="focus-value">KES {heroValue.toLocaleString()}</p>
          <p className="focus-copy">
            {heroCopy} Use this screen to show how tenders, supplier networks, controls, and review outcomes form one chain instead of disconnected alerts.
          </p>
          <div className="focus-stat-grid">
            <div className="focus-stat-card">
              <div className="focus-stat-label">Tender anomalies</div>
              <div className="focus-stat-value">{data.procurementAnomalies.length}</div>
            </div>
            <div className="focus-stat-card">
              <div className="focus-stat-label">Supplier entities</div>
              <div className="focus-stat-value">{uniqueVendors}</div>
            </div>
            <div className="focus-stat-card">
              <div className="focus-stat-label">Payment controls</div>
              <div className="focus-stat-value">{data.guardrailDecisions.length}</div>
            </div>
            <div className="focus-stat-card">
              <div className="focus-stat-label">Open reviews</div>
              <div className="focus-stat-value">{openIntegrity}</div>
            </div>
          </div>
          {ls && (
            <div className="chip-row" style={{ marginTop: 16 }}>
              {Object.entries(ls.bySeverity).map(([sev, count]) =>
                count > 0 ? (
                  <span key={sev} className={`risk-badge ${riskClass(sev)}`}>
                    {count} {sev}
                  </span>
                ) : null,
              )}
            </div>
          )}
        </div>

        <div className="panel priority-stack">
          <div className="panel-header">
            <h3>How this case is read</h3>
            <span className="muted">Follow the chain, not isolated alerts</span>
          </div>
          <div className="story-rail story-rail-four">
            <div className="story-card">
              <p className="story-card-label">Procurement</p>
              <h4>{data.procurementAnomalies.length} anomalies</h4>
              <p>{topProcurement ? `${topProcurement.tenderId} at ${topProcurement.agency} is the current lead case.` : "No tender anomaly is leading right now."}</p>
            </div>
            <div className="story-card">
              <p className="story-card-label">Supplier network</p>
              <h4>{uniqueVendors} vendors</h4>
              <p>Use repeated suppliers and shared vendor identities to surface collusion and subdivision risk.</p>
            </div>
            <div className="story-card">
              <p className="story-card-label">Payment control</p>
              <h4>{data.guardrailDecisions.length} holds</h4>
              <p>{topGuardrail ? `${topGuardrail.decision} on ${topGuardrail.tenderId} is the strongest current control signal.` : "No guardrail decision is leading yet."}</p>
            </div>
            <div className="story-card">
              <p className="story-card-label">Outcome queue</p>
              <h4>{openIntegrity} open reviews</h4>
              <p>{topIntegrity ? `${topIntegrity.alertType} in ${topIntegrity.sourceSystem} is currently open for review.` : "No integrity review is currently open."}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="grid-two">
        <div className="panel priority-stack">
          <div className="panel-header">
            <h3>Priority case</h3>
            <span className="muted">What to point at first</span>
          </div>
          {topProcurement ? (
            <div className="priority-card">
              <div className="priority-card-head">
                <div>
                  <h4 className="priority-card-title">{topProcurement.tenderId}</h4>
                  <p className="priority-card-copy">
                    {topProcurement.vendorId} at {topProcurement.agency} is flagged as {topProcurement.severity.toLowerCase()} severity at {topProcurement.score.toFixed(2)} score.
                  </p>
                </div>
                <span className={`risk-badge ${riskClass(topProcurement.severity)}`}>{topProcurement.severity}</span>
              </div>
            </div>
          ) : (
            <div className="priority-card">
              <h4 className="priority-card-title">No lead tender anomaly</h4>
              <p className="priority-card-copy">Use the lifecycle panels below once procurement data is ingested into the corruption pipeline.</p>
            </div>
          )}
          {topGuardrail && (
            <div className="priority-card">
              <div className="priority-card-head">
                <div>
                  <h4 className="priority-card-title">Control signal</h4>
                  <p className="priority-card-copy">
                    {topGuardrail.decision} applied to {topGuardrail.tenderId} for {topGuardrail.vendorId} at {topGuardrail.score.toFixed(2)} score.
                  </p>
                </div>
                <Shield size={16} color="var(--warning)" />
              </div>
            </div>
          )}
        </div>

        <div className="panel priority-stack">
          <div className="panel-header">
            <h3>Recommended next moves</h3>
            <span className="muted">Keep corruption actions human-gated</span>
          </div>
          <div className="priority-card">
            <h4 className="priority-card-title">1. Freeze the review, not the whole system</h4>
            <p className="priority-card-copy">Escalate the tender, vendor, or payment path for controlled audit review instead of claiming AI has proven wrongdoing.</p>
          </div>
          <div className="priority-card">
            <h4 className="priority-card-title">2. Link supplier and payment evidence</h4>
            <p className="priority-card-copy">Move from tender anomaly to supplier network to payment control and then to integrity outcome. That chain is the actual evidence story.</p>
          </div>
          <div className="priority-card-actions">
            <button className="btn-accent" onClick={onRunLeakage}>
              <TrendingUp size={13} /> &nbsp;{leakageActionLabel}
            </button>
          </div>
        </div>
      </div>

      {(byDetectorData.length > 0 || bySeverityData.length > 0) && (
        <details className="panel panel-details" open>
          <summary>
            <span>Detector mix and severity spread</span>
            <span className="muted">Open analytics breakdown</span>
          </summary>
          <div className="grid-two">
            <div className="panel">
              <div className="panel-header">
                <h3>Leakage by detector</h3>
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
                <h3>Alerts by severity</h3>
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
        </details>
      )}

      {/* Procurement anomalies */}
      {data.procurementAnomalies.length > 0 && (
        <details className="panel panel-details" open>
          <summary>
            <span>Procurement anomalies</span>
            <span className="muted">{data.procurementAnomalies.length} detected</span>
          </summary>
          <div className="panel-header">
            <h3>Procurement anomalies</h3>
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
        </details>
      )}

      {data.guardrailDecisions.length > 0 && (
        <details className="panel panel-details">
          <summary>
            <span>Payment controls and guardrails</span>
            <span className="muted">{data.guardrailDecisions.length} decisions</span>
          </summary>
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
        </details>
      )}

      {data.integrityAlerts.length > 0 && (
        <details className="panel panel-details">
          <summary>
            <span>Integrity alerts</span>
            <span className="muted">{data.integrityAlerts.length} alerts</span>
          </summary>
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
        </details>
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
