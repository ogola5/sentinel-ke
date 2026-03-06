/**
 * OperationsCenter — S7: Operations & Economy
 *
 * Six summary cards on the main view.
 * Click any card → DetailPanel slides in with the full detail section.
 *
 * Cards: Live Metrics · Anomalies · Economy Signals · Procurement · Guardrail/Integrity · Leakage
 */
import { useState } from "react";
import type { OperationsSnapshot } from "../types/operations";
import DetailPanel from "../components/DetailPanel";

type DetailKey = "metrics" | "anomalies" | "economy" | "procurement" | "integrity" | "leakage" | null;

type OperationsCenterProps = {
  data: OperationsSnapshot;
  onRunLeakage: () => void;
  leakageActionLabel: string;
};

const severityClass = (severity: string) => {
  const s = severity.toLowerCase();
  if (s === "high" || s === "critical" || s === "block") return "severity-pill severity-high";
  if (s === "medium" || s === "review")                   return "severity-pill severity-medium";
  return "severity-pill severity-low";
};

const compactAmount = (value: number): string =>
  new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);

export default function OperationsCenter({ data, onRunLeakage, leakageActionLabel }: OperationsCenterProps) {
  const [openDetail, setOpenDetail] = useState<DetailKey>(null);

  const close = () => setOpenDetail(null);

  // ── Summary card helpers ────────────────────────────────────────────────────
  const anomalyHigh = data.anomalies.filter((a) => a.score >= 0.8).length;
  const ecoHigh     = data.economySignals.filter((s) => s.severity.toLowerCase() === "high").length;
  const leakageKes  = compactAmount(data.leakageSummary.suspectedAmountTotal);

  return (
    <section className="screen">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="screen-header">
        <div>
          <p className="eyebrow">S7</p>
          <h2>Operations &amp; Economy</h2>
          <p className="subtle">Backend-integrated analytics · guardrails · integrity · leakage</p>
        </div>
        <button className="ghost" type="button" onClick={onRunLeakage}>
          {leakageActionLabel}
        </button>
      </div>

      {/* ── Six summary cards ───────────────────────────────────────────── */}
      <div className="ops-card-grid">
        {/* 1 · Live Metrics */}
        <button type="button" className="ops-card" onClick={() => setOpenDetail("metrics")}>
          <p className="ops-card-label">Live Metrics</p>
          <p className="ops-card-value">{data.metrics.events}</p>
          <p className="ops-card-sub">events · {data.metrics.graphDeltas} graph Δ</p>
          <p className="ops-card-cta">View breakdown →</p>
        </button>

        {/* 2 · Anomalies */}
        <button type="button" className={`ops-card${anomalyHigh > 0 ? " ops-card-alert" : ""}`}
          onClick={() => setOpenDetail("anomalies")}>
          <p className="ops-card-label">Anomalies</p>
          <p className="ops-card-value">{data.anomalies.length}</p>
          <p className="ops-card-sub">{anomalyHigh} high-severity</p>
          <p className="ops-card-cta">View anomalies →</p>
        </button>

        {/* 3 · Economy Signals */}
        <button type="button" className={`ops-card${ecoHigh > 0 ? " ops-card-alert" : ""}`}
          onClick={() => setOpenDetail("economy")}>
          <p className="ops-card-label">Economy Signals</p>
          <p className="ops-card-value">{data.economySignals.length}</p>
          <p className="ops-card-sub">{ecoHigh} high-severity</p>
          <p className="ops-card-cta">View signals →</p>
        </button>

        {/* 4 · Procurement */}
        <button type="button" className="ops-card" onClick={() => setOpenDetail("procurement")}>
          <p className="ops-card-label">Procurement</p>
          <p className="ops-card-value">{data.procurementAnomalies.length}</p>
          <p className="ops-card-sub">tender/vendor anomalies</p>
          <p className="ops-card-cta">View procurement →</p>
        </button>

        {/* 5 · Guardrail / Integrity */}
        <button type="button" className="ops-card" onClick={() => setOpenDetail("integrity")}>
          <p className="ops-card-label">Guardrail &amp; Integrity</p>
          <p className="ops-card-value">{data.guardrailDecisions.length + data.integrityAlerts.length}</p>
          <p className="ops-card-sub">{data.guardrailDecisions.length} decisions · {data.integrityAlerts.length} alerts</p>
          <p className="ops-card-cta">View guardrail →</p>
        </button>

        {/* 6 · Leakage */}
        <button type="button" className={`ops-card${data.leakageSummary.totalAlerts > 0 ? " ops-card-alert" : ""}`}
          onClick={() => setOpenDetail("leakage")}>
          <p className="ops-card-label">Leakage Monitor</p>
          <p className="ops-card-value">KES {leakageKes}</p>
          <p className="ops-card-sub">{data.leakageSummary.totalAlerts} alerts · {data.leakageSummary.windowDays}d window</p>
          <p className="ops-card-cta">View leakage →</p>
        </button>
      </div>

      {/* ── Detail panels ───────────────────────────────────────────────── */}

      {/* Metrics */}
      <DetailPanel open={openDetail === "metrics"} title="Live Metrics" onClose={close}>
        <div className="ops-metric-grid">
          {[
            ["Events",       data.metrics.events],
            ["Graph Deltas", data.metrics.graphDeltas],
            ["Anomalies",    data.metrics.anomalies],
            ["Mitigations",  data.metrics.mitigations],
          ].map(([label, val]) => (
            <div key={String(label)} className="panel metric-card">
              <p className="label">{label}</p>
              <p className="metric-value mono">{val}</p>
            </div>
          ))}
        </div>
        <div className="panel-subsection">
          <h4>IOC Export</h4>
          <div className="ops-ioc-grid">
            {[
              ["Records",   data.iocExport.records],
              ["Actions",   data.iocExport.actions],
              ["IPs",       data.iocExport.ips],
              ["Domains",   data.iocExport.domains],
              ["Providers", data.iocExport.providers],
              ["Endpoints", data.iocExport.endpoints],
            ].map(([l, v]) => (
              <div key={String(l)} className="ops-ioc-item">
                <p className="label">{l}</p>
                <p className="stat mono">{v}</p>
              </div>
            ))}
          </div>
        </div>
      </DetailPanel>

      {/* Anomalies */}
      <DetailPanel open={openDetail === "anomalies"} title="Anomalies & AI Predictions" onClose={close}>
        <div className="ops-list">
          {data.anomalies.map((item) => (
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
          {data.anomalies.length === 0 && <p className="muted">No anomalies available.</p>}
        </div>
        <div className="panel-subsection">
          <h4>AI Predictions</h4>
          <div className="ops-list">
            {data.predictions.map((item) => (
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
      </DetailPanel>

      {/* Economy */}
      <DetailPanel open={openDetail === "economy"} title="Economic Signals" onClose={close}>
        <div className="ops-list">
          {data.economySignals.map((item) => (
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
      </DetailPanel>

      {/* Procurement */}
      <DetailPanel open={openDetail === "procurement"} title="Procurement Anomalies" onClose={close}>
        <div className="ops-list">
          {data.procurementAnomalies.map((item) => (
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
      </DetailPanel>

      {/* Guardrail + Integrity */}
      <DetailPanel open={openDetail === "integrity"} title="Guardrail & Integrity" onClose={close}>
        <div className="ops-list">
          {data.guardrailDecisions.map((item) => (
            <div key={item.id} className="ops-row">
              <div>
                <p className="mono">{item.tenderId}</p>
                <p className="muted">{item.vendorId}</p>
              </div>
              <span className={severityClass(item.decision)}>{item.decision}</span>
              <span className="mono">{item.score.toFixed(2)}</span>
            </div>
          ))}
          {data.guardrailDecisions.length === 0 && <p className="muted">No guardrail decisions.</p>}
        </div>
        <div className="panel-subsection">
          <h4>External Integrity Alerts</h4>
          <div className="ops-list">
            {data.integrityAlerts.map((item) => (
              <div key={item.id} className="ops-row">
                <div>
                  <p>{item.sourceSystem}</p>
                  <p className="muted">{item.recordType} / {item.alertType}</p>
                </div>
                <span className={severityClass(item.severity)}>{item.severity}</span>
                <span className="mono">{Math.round(item.confidence * 100)}%</span>
              </div>
            ))}
            {data.integrityAlerts.length === 0 && <p className="muted">No integrity alerts.</p>}
          </div>
        </div>
      </DetailPanel>

      {/* Leakage */}
      <DetailPanel open={openDetail === "leakage"} title="Leakage Monitor" onClose={close}>
        <div className="ops-leakage-summary">
          <div><p className="label">Window</p><p className="stat mono">{data.leakageSummary.windowDays} days</p></div>
          <div><p className="label">Total alerts</p><p className="stat mono">{data.leakageSummary.totalAlerts}</p></div>
          <div>
            <p className="label">Suspected amount</p>
            <p className="stat mono">KES {leakageKes}</p>
          </div>
        </div>
        <div className="panel-subsection">
          <h4>Recent Leakage Alerts</h4>
          <div className="ops-list">
            {data.leakageAlerts.map((item) => (
              <div key={item.id} className="ops-row">
                <div>
                  <p>{item.detectorType}</p>
                  <p className="muted">{item.vendorId} / {item.agency}</p>
                </div>
                <span className={severityClass(item.severity)}>{item.severity}</span>
                <span className="mono">{item.score.toFixed(2)}</span>
              </div>
            ))}
            {data.leakageAlerts.length === 0 && <p className="muted">No leakage alerts.</p>}
          </div>
        </div>
        <div className="dp-actions">
          <button className="ghost" type="button" onClick={onRunLeakage}>{leakageActionLabel}</button>
        </div>
      </DetailPanel>
    </section>
  );
}
