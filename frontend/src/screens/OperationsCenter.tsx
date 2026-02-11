import type { OperationsSnapshot } from "../types/operations";

type OperationsCenterProps = {
  data: OperationsSnapshot;
  onRunLeakage: () => void;
  leakageActionLabel: string;
};

const severityClass = (severity: string) => {
  const normalized = severity.toLowerCase();
  if (normalized === "high" || normalized === "critical" || normalized === "block") {
    return "severity-pill severity-high";
  }
  if (normalized === "medium" || normalized === "review") {
    return "severity-pill severity-medium";
  }
  return "severity-pill severity-low";
};

const compactAmount = (value: number): string =>
  new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);

export default function OperationsCenter({
  data,
  onRunLeakage,
  leakageActionLabel,
}: OperationsCenterProps) {
  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S7</p>
          <h2>Operations & Economy</h2>
          <p className="subtle">Backend-integrated analytics, guardrails, integrity, and leakage monitoring.</p>
        </div>
        <button className="ghost" type="button" onClick={onRunLeakage}>
          {leakageActionLabel}
        </button>
      </div>

      <div className="ops-metric-grid">
        <div className="panel metric-card">
          <p className="label">Events</p>
          <p className="metric-value mono">{data.metrics.events}</p>
        </div>
        <div className="panel metric-card">
          <p className="label">Graph deltas</p>
          <p className="metric-value mono">{data.metrics.graphDeltas}</p>
        </div>
        <div className="panel metric-card">
          <p className="label">Anomalies</p>
          <p className="metric-value mono">{data.metrics.anomalies}</p>
        </div>
        <div className="panel metric-card">
          <p className="label">Mitigations</p>
          <p className="metric-value mono">{data.metrics.mitigations}</p>
        </div>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>Anomalies</h3>
            <span className="muted">/v1/anomalies + /v1/ai/predictions</span>
          </div>
          <div className="ops-list">
            {data.anomalies.slice(0, 5).map((item) => (
              <div key={item.id} className="ops-row">
                <div>
                  <p className="mono">{item.serviceId}</p>
                  <p className="muted">{item.endpoint}</p>
                </div>
                <span className={severityClass(item.score >= 0.8 ? "high" : item.score >= 0.5 ? "medium" : "low")}>
                  {item.score.toFixed(2)}
                </span>
                <span className="muted">{item.windowEnd}</span>
              </div>
            ))}
            {data.anomalies.length === 0 && <p className="muted">No anomaly rows available.</p>}
          </div>

          <div className="panel-subsection">
            <h4>AI predictions</h4>
            <div className="ops-list">
              {data.predictions.slice(0, 5).map((item) => (
                <div key={item.id} className="ops-row">
                  <div>
                    <p className="mono">{item.entityKey}</p>
                    <p className="muted">{item.predictionType}</p>
                  </div>
                  <span className={severityClass(item.score >= 0.8 ? "high" : item.score >= 0.5 ? "medium" : "low")}>
                    {item.score.toFixed(2)}
                  </span>
                  <span className="muted">{item.evidenceCount} ev</span>
                </div>
              ))}
              {data.predictions.length === 0 && <p className="muted">No prediction rows available.</p>}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Mitigations & IOC Export</h3>
            <span className="muted">/v1/mitigations + /v1/mitigations/export</span>
          </div>
          <div className="ops-ioc-grid">
            <div className="ops-ioc-item">
              <p className="label">Records</p>
              <p className="stat mono">{data.iocExport.records}</p>
            </div>
            <div className="ops-ioc-item">
              <p className="label">Actions</p>
              <p className="stat mono">{data.iocExport.actions}</p>
            </div>
            <div className="ops-ioc-item">
              <p className="label">IPs</p>
              <p className="stat mono">{data.iocExport.ips}</p>
            </div>
            <div className="ops-ioc-item">
              <p className="label">Domains</p>
              <p className="stat mono">{data.iocExport.domains}</p>
            </div>
            <div className="ops-ioc-item">
              <p className="label">Providers</p>
              <p className="stat mono">{data.iocExport.providers}</p>
            </div>
            <div className="ops-ioc-item">
              <p className="label">Endpoints</p>
              <p className="stat mono">{data.iocExport.endpoints}</p>
            </div>
          </div>

          <div className="panel-subsection">
            <h4>Latest mitigation rows</h4>
            <div className="ops-list">
              {data.mitigations.slice(0, 5).map((item) => (
                <div key={item.id} className="ops-row">
                  <div>
                    <p className="mono">{item.kind}</p>
                    <p className="muted">{item.refId}</p>
                  </div>
                  <span className="chip">{item.stakeholders.slice(0, 2).join(", ") || "n/a"}</span>
                  <span className="muted">{item.createdAt}</span>
                </div>
              ))}
              {data.mitigations.length === 0 && <p className="muted">No mitigation rows available.</p>}
            </div>
          </div>
        </div>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>Economic Signals</h3>
            <span className="muted">/v1/economy/signals + procurement anomalies</span>
          </div>
          <div className="ops-list">
            {data.economySignals.slice(0, 5).map((item) => (
              <div key={item.id} className="ops-row">
                <div>
                  <p>{item.signalType}</p>
                  <p className="muted">{item.agency} / {item.sector}</p>
                </div>
                <span className={severityClass(item.severity)}>{item.severity}</span>
                <span className="mono">{item.score.toFixed(2)}</span>
              </div>
            ))}
            {data.economySignals.length === 0 && <p className="muted">No economic signals available.</p>}
          </div>
          <div className="panel-subsection">
            <h4>Procurement anomalies</h4>
            <div className="ops-list">
              {data.procurementAnomalies.slice(0, 5).map((item) => (
                <div key={item.id} className="ops-row">
                  <div>
                    <p className="mono">{item.tenderId}</p>
                    <p className="muted">{item.vendorId} / {item.agency}</p>
                  </div>
                  <span className={severityClass(item.severity)}>{item.severity}</span>
                  <span className="mono">{item.score.toFixed(2)}</span>
                </div>
              ))}
              {data.procurementAnomalies.length === 0 && <p className="muted">No procurement anomalies available.</p>}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Guardrail + Integrity</h3>
            <span className="muted">Decisions and tamper alerts</span>
          </div>
          <div className="ops-list">
            {data.guardrailDecisions.slice(0, 5).map((item) => (
              <div key={item.id} className="ops-row">
                <div>
                  <p className="mono">{item.tenderId}</p>
                  <p className="muted">{item.vendorId}</p>
                </div>
                <span className={severityClass(item.decision)}>{item.decision}</span>
                <span className="mono">{item.score.toFixed(2)}</span>
              </div>
            ))}
            {data.guardrailDecisions.length === 0 && <p className="muted">No guardrail decisions available.</p>}
          </div>
          <div className="panel-subsection">
            <h4>External integrity alerts</h4>
            <div className="ops-list">
              {data.integrityAlerts.slice(0, 5).map((item) => (
                <div key={item.id} className="ops-row">
                  <div>
                    <p>{item.sourceSystem}</p>
                    <p className="muted">{item.recordType} / {item.alertType}</p>
                  </div>
                  <span className={severityClass(item.severity)}>{item.severity}</span>
                  <span className="mono">{Math.round(item.confidence * 100)}%</span>
                </div>
              ))}
              {data.integrityAlerts.length === 0 && <p className="muted">No integrity alerts available.</p>}
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Leakage Monitor</h3>
          <span className="muted">/v1/economy/leakage/summary + alerts</span>
        </div>
        <div className="ops-leakage-summary">
          <div>
            <p className="label">Window</p>
            <p className="stat mono">{data.leakageSummary.windowDays} days</p>
          </div>
          <div>
            <p className="label">Total alerts</p>
            <p className="stat mono">{data.leakageSummary.totalAlerts}</p>
          </div>
          <div>
            <p className="label">Suspected amount</p>
            <p className="stat mono">KES {compactAmount(data.leakageSummary.suspectedAmountTotal)}</p>
          </div>
        </div>
        <div className="panel-subsection">
          <h4>Recent leakage alerts</h4>
          <div className="ops-list">
            {data.leakageAlerts.slice(0, 6).map((item) => (
              <div key={item.id} className="ops-row">
                <div>
                  <p>{item.detectorType}</p>
                  <p className="muted">{item.vendorId} / {item.agency}</p>
                </div>
                <span className={severityClass(item.severity)}>{item.severity}</span>
                <span className="mono">{item.score.toFixed(2)}</span>
              </div>
            ))}
            {data.leakageAlerts.length === 0 && <p className="muted">No leakage alerts available.</p>}
          </div>
        </div>
      </div>
    </section>
  );
}
