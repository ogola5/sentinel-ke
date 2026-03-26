import { useMemo, useState } from "react";
import { Activity, AlertTriangle, FileWarning, Shield, Wallet } from "lucide-react";

import type { OperationsSnapshot } from "../types/operations";
import { formatRiskScore, isHighRisk, riskSeverityLabel } from "../utils/risk";
import { displayEntityLabel, isCanonicalEntityKey } from "../utils/entityKeys";

type OperationsView = "overview" | "review" | "integrity";
type ReviewQueue = "predictions" | "anomalies";

type OperationsCenterProps = {
  data: OperationsSnapshot;
  onRunLeakage: () => void;
  leakageActionLabel: string;
  onOpenCorruptionIntel?: () => void;
};

const anomalyLabel = (score: number): "high" | "medium" | "low" => {
  if (score >= 0.8) return "high";
  if (score >= 0.5) return "medium";
  return "low";
};

const compactAmount = (value: number): string =>
  new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);

const humanEntity = (value: string): string =>
  isCanonicalEntityKey(value) ? displayEntityLabel(value) : value;

const humanReason = (value: string | undefined): string => {
  if (!value) return "Model signaled risk from linked evidence.";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
};

export default function OperationsCenter({ data, onRunLeakage, leakageActionLabel, onOpenCorruptionIntel }: OperationsCenterProps) {
  const [view, setView] = useState<OperationsView>("overview");
  const [reviewQueue, setReviewQueue] = useState<ReviewQueue>("predictions");

  const highRiskPredictions = useMemo(
    () => data.predictions.filter((item) => isHighRisk(item.score)),
    [data.predictions],
  );
  const highAnomalies = useMemo(
    () => data.anomalies.filter((item) => item.score >= 0.8),
    [data.anomalies],
  );
  const blockedGuardrails = useMemo(
    () => data.guardrailDecisions.filter((item) => item.decision === "block"),
    [data.guardrailDecisions],
  );
  const primaryQueue = highRiskPredictions.length >= highAnomalies.length ? "AI risk queue" : "Anomaly queue";
  const reviewCount = reviewQueue === "predictions" ? data.predictions.length : data.anomalies.length;
  const integrityPressure = data.procurementAnomalies.length + blockedGuardrails.length + data.integrityAlerts.length;
  const prioritySummary =
    highRiskPredictions.length > 0
      ? `${highRiskPredictions.length} AI-scored entities are already above the response threshold.`
      : highAnomalies.length > 0
        ? `${highAnomalies.length} sensor anomalies need corroboration before escalation.`
        : "No urgent cyber queue is active right now.";
  const leakageSummary =
    data.leakageSummary.totalAlerts > 0
      ? `Leakage monitoring is tracking ${data.leakageSummary.totalAlerts} alerts and KES ${data.leakageSummary.suspectedAmountTotal.toLocaleString()} of suspected exposure.`
      : "Leakage monitoring is currently quiet.";

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S7</p>
          <h2>Operational Dashboard</h2>
          <p className="subtle">
            What is happening now, what needs review first, and what can be handed to deeper investigation.
          </p>
        </div>
        <div className="screen-header-actions">
          <div className="chip-row">
            {[
              { id: "overview", label: "Overview" },
              { id: "review", label: "Review Queue" },
              { id: "integrity", label: "Integrity & Leakage" },
            ].map((item) => (
              <button
                key={item.id}
                type="button"
                className={view === item.id ? "chip active" : "chip ghost"}
                onClick={() => setView(item.id as OperationsView)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button className="ghost" type="button" onClick={onRunLeakage}>
            {leakageActionLabel}
          </button>
        </div>
      </div>

      {view === "overview" && (
        <div className="workflow-stack">
          {!data.availability.cyberFeedsOk && (
            <div className="info-note">
              <AlertTriangle size={13} style={{ flexShrink: 0 }} />
              <span>Cyber queue feeds are currently unavailable or restricted for this session.</span>
            </div>
          )}
          {!data.availability.integrityFeedsOk && (
            <div className="info-note">
              <FileWarning size={13} style={{ flexShrink: 0 }} />
              <span>Integrity and leakage feeds are limited for this user or not currently available from the backend.</span>
            </div>
          )}
          <div className="metric-grid">
            <div className="metric-card">
              <div className="metric-label">Signals ingested</div>
              <div className="metric-value">{data.metrics.events}</div>
              <div className="metric-sub">{data.metrics.graphDeltas} graph updates</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Cyber queue</div>
              <div className="metric-value">{highRiskPredictions.length}</div>
              <div className="metric-sub">{highAnomalies.length} anomalies need corroboration</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Integrity pressure</div>
              <div className="metric-value">{integrityPressure}</div>
              <div className="metric-sub">{blockedGuardrails.length} blocked guardrails</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Leakage monitor</div>
              <div className="metric-value">KES {compactAmount(data.leakageSummary.suspectedAmountTotal)}</div>
              <div className="metric-sub">{data.leakageSummary.totalAlerts} alerts</div>
            </div>
          </div>

          <div className="workflow-summary-banner">
            <div>
              <strong>What is happening now</strong>
              <span className="muted">{prioritySummary}</span>
            </div>
            <div>
              <strong>Why this matters</strong>
              <span className="muted">{leakageSummary}</span>
            </div>
            <div>
              <strong>Operator intent</strong>
              <span className="muted">Use this screen to choose the next queue, not to finish the whole investigation here.</span>
            </div>
          </div>

          <div className="grid-two">
            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Current posture</h3>
                <span className="muted">{primaryQueue} next</span>
              </div>
              <div className="list">
                <div className="list-item">
                  <p style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600 }}>
                    <AlertTriangle size={14} color="var(--risk-high)" />
                    Anomaly queue
                  </p>
                  <p className="muted">{data.anomalies.length} active anomalies, {highAnomalies.length} in the highest bucket.</p>
                </div>
                <div className="list-item">
                  <p style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600 }}>
                    <Shield size={14} color="var(--accent)" />
                    AI risk review
                  </p>
                  <p className="muted">{highRiskPredictions.length} AI predictions are above the operational threshold.</p>
                </div>
                <div className="list-item">
                  <p style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600 }}>
                    <Wallet size={14} color="var(--warning)" />
                    Economic exposure
                  </p>
                  <p className="muted">
                    {data.integrityAlerts.length} integrity alerts and KES {data.leakageSummary.suspectedAmountTotal.toLocaleString()} suspected leakage.
                  </p>
                </div>
              </div>
            </div>

            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Next actionable items</h3>
                <span className="muted">Short list, not a flood</span>
              </div>
              <div className="list">
                {[
                  ...highRiskPredictions.slice(0, 2).map((item) => ({
                    title: humanEntity(item.entityKey),
                    subtitle: `${humanReason(item.reasonCodes[0])} · ${item.evidenceCount} evidence references`,
                    score: `${formatRiskScore(item.score)} / 100`,
                  })),
                  ...data.mitigations.slice(0, 2).map((item) => ({
                    title: item.kind,
                    subtitle: item.stakeholders.join(", ") || item.refId,
                    score: item.createdAt,
                  })),
                ].slice(0, 4).map((item, index) => (
                  <div key={`${item.title}-${index}`} className="list-item" style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
                    <div>
                      <p style={{ fontWeight: 600, marginBottom: 3 }}>{item.title}</p>
                      <p className="muted">{item.subtitle}</p>
                    </div>
                    <span className="mono">{item.score}</span>
                  </div>
                ))}
                {highRiskPredictions.length === 0 && data.mitigations.length === 0 && (
                  <div className="state-box">
                    <Activity size={20} />
                    <p>No action queue is populated yet.</p>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="grid-two">
            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Shareable cyber indicators</h3>
                <span className="muted">What can be exported or forwarded</span>
              </div>
              <div className="ops-ioc-grid">
                <div className="ops-ioc-item">
                  <p className="label">IPs</p>
                  <p className="stat">{data.iocExport.ips}</p>
                </div>
                <div className="ops-ioc-item">
                  <p className="label">Domains</p>
                  <p className="stat">{data.iocExport.domains}</p>
                </div>
                <div className="ops-ioc-item">
                  <p className="label">Endpoints</p>
                  <p className="stat">{data.iocExport.endpoints}</p>
                </div>
              </div>
              <p className="muted" style={{ marginTop: 10 }}>
                This section is the operational share surface: indicators and mitigation exports that can move into partner workflows or structured formats.
              </p>
            </div>

            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>How to read this dashboard</h3>
                <span className="muted">Plain language first</span>
              </div>
              <div className="list">
                <div className="list-item">
                  High <strong>Cyber queue</strong> means AI-scored entities or sensor anomalies need analyst review.
                </div>
                <div className="list-item">
                  High <strong>Integrity pressure</strong> means procurement or records risk is rising and should move to Corruption Intelligence.
                </div>
                <div className="list-item">
                  High <strong>Leakage monitor</strong> means money or procurement exposure is accumulating, even if cyber risk is quiet.
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {view === "review" && (
        <div className="workflow-stack">
          <div className="info-note">
            <Shield size={13} style={{ flexShrink: 0 }} />
            <span>
              Use <strong>AI Predictions</strong> when the model already sees connected risk. Use <strong>Anomalies</strong> when sensor pressure exists but the case still needs corroboration.
            </span>
          </div>
          <div className="chip-row">
            <button
              type="button"
              className={reviewQueue === "predictions" ? "chip active" : "chip ghost"}
              onClick={() => setReviewQueue("predictions")}
            >
              AI Predictions
            </button>
            <button
              type="button"
              className={reviewQueue === "anomalies" ? "chip active" : "chip ghost"}
              onClick={() => setReviewQueue("anomalies")}
            >
              Anomalies
            </button>
          </div>

          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>{reviewQueue === "predictions" ? "AI predictions" : "Anomalies"}</h3>
              <span className="muted">
                {reviewCount} rows · {reviewQueue === "predictions" ? highRiskPredictions.length : highAnomalies.length} priority
              </span>
            </div>
            {reviewQueue === "anomalies" ? (
              data.anomalies.length === 0 ? (
                <div className="state-box">
                  <AlertTriangle size={20} />
                  <p>No anomalies available.</p>
                </div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Service</th>
                      <th>Endpoint</th>
                      <th>Score</th>
                      <th>Window</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.anomalies.slice(0, 10).map((item) => (
                      <tr key={item.id}>
                        <td className="mono" style={{ fontSize: "0.78rem" }}>{item.serviceId}</td>
                        <td className="muted">{item.endpoint}</td>
                        <td><span className={`risk-badge ${anomalyLabel(item.score)}`}>{item.score.toFixed(2)}</span></td>
                        <td className="muted">{item.windowEnd}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            ) : data.predictions.length === 0 ? (
              <div className="state-box">
                <Shield size={20} />
                <p>No AI predictions available.</p>
              </div>
            ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Entity</th>
                      <th>Meaning</th>
                      <th>Risk</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.predictions.slice(0, 10).map((item) => (
                      <tr key={item.id}>
                        <td className="mono" style={{ fontSize: "0.78rem" }}>{humanEntity(item.entityKey)}</td>
                        <td className="muted">{humanReason(item.reasonCodes[0])}</td>
                        <td>
                          <span className={`risk-badge ${riskSeverityLabel(item.score).toLowerCase()}`}>
                            {formatRiskScore(item.score)}
                          </span>
                        </td>
                      <td className="muted">{item.evidenceCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <details className="collapsible-panel">
              <summary>
                Mitigations and exports
                <span className="muted">{data.mitigations.length} recent rows</span>
              </summary>
              {data.mitigations.length === 0 ? (
                <div className="state-box">
                  <FileWarning size={20} />
                  <p>No mitigations available.</p>
                </div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Kind</th>
                      <th>Reference</th>
                      <th>Stakeholders</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.mitigations.slice(0, 8).map((item) => (
                      <tr key={item.id}>
                        <td>{item.kind}</td>
                        <td className="mono">{item.refId}</td>
                        <td className="muted">{item.stakeholders.join(", ") || "—"}</td>
                        <td>{item.createdAt}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </details>
          </div>
        </div>
      )}

      {view === "integrity" && (
        <div className="workflow-stack">
          {!data.availability.integrityFeedsOk && (
            <div className="info-note">
              <AlertTriangle size={13} style={{ flexShrink: 0 }} />
              <span>
                Some integrity feeds are scope-restricted. A quiet table here may mean limited access, not necessarily a clean national picture.
              </span>
            </div>
          )}
          <div className="info-note">
            <Wallet size={13} style={{ flexShrink: 0 }} />
            <span>
              This tab is for procurement and financial integrity pressure. It is not a cyber-attack trace view; use it to decide whether to open the deeper corruption workflow.
            </span>
          </div>
          <div className="grid-two">
            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Leakage summary</h3>
                <span className="muted">{data.leakageSummary.windowDays}-day window</span>
              </div>
              <div className="detail-grid">
                <div>
                  <p className="label">Alerts</p>
                  <p className="stat">{data.leakageSummary.totalAlerts}</p>
                </div>
                <div>
                  <p className="label">Suspected amount</p>
                  <p className="stat">KES {data.leakageSummary.suspectedAmountTotal.toLocaleString()}</p>
                </div>
                <div>
                  <p className="label">Detectors</p>
                  <p className="stat">{Object.keys(data.leakageSummary.byDetector).length}</p>
                </div>
                <div>
                  <p className="label">Severity buckets</p>
                  <p className="stat">{Object.keys(data.leakageSummary.bySeverity).length}</p>
                </div>
              </div>
              <div className="panel-subsection">
                <h4>Leakage by severity</h4>
                <div className="chip-row">
                  {Object.entries(data.leakageSummary.bySeverity).map(([severity, count]) => (
                    <span key={severity} className={`risk-badge ${severity.toLowerCase()}`}>
                      {severity}: {count}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Integrity pressure</h3>
                <span className="muted">Most important queues</span>
              </div>
              <div className="list">
                <div className="list-item">
                  <strong>{data.procurementAnomalies.length}</strong> procurement anomalies
                </div>
                <div className="list-item">
                  <strong>{blockedGuardrails.length}</strong> guardrail blocks
                </div>
                <div className="list-item">
                  <strong>{data.integrityAlerts.length}</strong> integrity alerts
                </div>
                <div className="list-item">
                  <strong>{data.economySignals.length}</strong> economy signals
                </div>
              </div>
            </div>
          </div>

          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>Priority integrity snapshot</h3>
              <span className="muted">{data.procurementAnomalies.length + data.integrityAlerts.length} priority rows</span>
            </div>
            <div className="info-note" style={{ marginBottom: 12 }}>
              <FileWarning size={13} style={{ flexShrink: 0 }} />
              <span>
                This workspace keeps integrity pressure short. Use <strong>Corruption Intelligence</strong> for the full procurement, guardrail, and integrity investigation surfaces.
              </span>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Queue</th>
                  <th>Reference</th>
                  <th>Agency / source</th>
                  <th>Severity</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ...data.procurementAnomalies.slice(0, 3).map((item) => ({
                    queue: "Procurement",
                    reference: item.tenderId,
                    source: `${item.vendorId} / ${item.agency}`,
                    severity: item.severity,
                    score: item.score.toFixed(2),
                  })),
                  ...data.integrityAlerts.slice(0, 3).map((item) => ({
                    queue: "Integrity",
                    reference: item.recordType,
                    source: `${item.sourceSystem} / ${item.alertType}`,
                    severity: item.severity,
                    score: `${Math.round(item.confidence * 100)}%`,
                  })),
                ].map((item, index) => (
                  <tr key={`${item.queue}-${item.reference}-${index}`}>
                    <td>{item.queue}</td>
                    <td className="mono">{item.reference}</td>
                    <td className="muted">{item.source}</td>
                    <td><span className={`risk-badge ${item.severity.toLowerCase()}`}>{item.severity}</span></td>
                    <td>{item.score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {onOpenCorruptionIntel && (
              <div className="chip-row" style={{ marginTop: 12 }}>
                <button className="ghost" type="button" onClick={onOpenCorruptionIntel}>
                  Open Corruption Intelligence
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
