import { useEffect, useMemo, useState } from "react";
import { FileText, Loader2, ShieldCheck } from "lucide-react";

import ArchitectureFlow from "../app/ArchitectureFlow";
import {
  type ReportCatalog,
  type ReportFormat,
  type ReportPeriod,
  type ReportRequest,
  type ReportType,
  downloadReport,
  fetchReportCatalog,
  generateReport,
} from "../api/reports";
import { fetchAIPredictions } from "../api/ai";
import type { AIPrediction } from "../types/ai";
import type { Principal } from "../types/auth";

const DEFAULT_REQUEST: ReportRequest = {
  report_type: "incident_brief",
  period: "daily",
  format: "html",
  prediction_type: "risk_gnn",
  classification: "RESTRICTED",
};

function requiresField(reportType: ReportType, field: keyof ReportRequest): boolean {
  if (reportType === "entity_investigation") return field === "entity_key";
  if (reportType === "campaign_case") return field === "campaign_id";
  if (reportType === "legal_evidence_bundle") return field === "bundle_id" || field === "campaign_id";
  if (reportType === "ai_decision_explanation") return field === "prediction_id" || field === "entity_key";
  return false;
}

function canAccessLegalReports(principal: Principal): boolean {
  return principal.access_level === "central" || principal.scopes.includes("*") || principal.scopes.includes("legal.read") || principal.scopes.includes("legal.write");
}

export default function ReportsCenter({ principal }: { principal: Principal }) {
  const [catalog, setCatalog] = useState<ReportCatalog | null>(null);
  const [request, setRequest] = useState<ReportRequest>(DEFAULT_REQUEST);
  const [entitySuggestions, setEntitySuggestions] = useState<AIPrediction[]>([]);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setCatalog(await fetchReportCatalog());
      } catch (err) {
        setError(String(err));
      }
    })();
  }, []);

  useEffect(() => {
    void (async () => {
      if (
        request.report_type !== "entity_investigation" &&
        request.report_type !== "ai_decision_explanation"
      ) {
        setEntitySuggestions([]);
        return;
      }
      try {
        const rows = await fetchAIPredictions(12);
        const filtered = rows.filter((row) => row.prediction_type === (request.prediction_type ?? "risk_gnn"));
        setEntitySuggestions(filtered);
      } catch {
        setEntitySuggestions([]);
      }
    })();
  }, [request.report_type, request.prediction_type]);

  const selectedType = useMemo(
    () => catalog?.report_types.find((item) => item.report_type === request.report_type),
    [catalog, request.report_type],
  );
  const allowLegalReports = canAccessLegalReports(principal);
  const visibleReportTypes = useMemo(
    () => (catalog?.report_types ?? []).filter((item) => allowLegalReports || item.report_type !== "legal_evidence_bundle"),
    [allowLegalReports, catalog],
  );

  useEffect(() => {
    if (allowLegalReports) return;
    if (request.report_type === "legal_evidence_bundle") {
      setRequest((current) => ({ ...current, report_type: "incident_brief" }));
    }
  }, [allowLegalReports, request.report_type]);

  const summary = (preview?.summary as Record<string, unknown> | undefined) ?? {};
  const findings = Array.isArray(preview?.findings) ? (preview?.findings as Array<Record<string, unknown>>) : [];
  const governance = (preview?.governance as Record<string, unknown> | undefined) ?? {};

  function sanitizeRequest(current: ReportRequest): ReportRequest {
    return {
      ...current,
      entity_key: current.entity_key?.trim() || undefined,
      campaign_id: current.campaign_id?.trim() || undefined,
      bundle_id: current.bundle_id?.trim() || undefined,
      prediction_id: current.prediction_id?.trim() || undefined,
      model_version: current.model_version?.trim() || undefined,
      classification: current.classification?.trim() || "RESTRICTED",
      prediction_type: current.prediction_type?.trim() || "risk_gnn",
    };
  }

  function validateRequest(current: ReportRequest): string | null {
    if (requiresField(current.report_type, "entity_key") && !current.entity_key?.trim()) {
      return "Choose a real entity key from suggestions or enter one manually.";
    }
    if (requiresField(current.report_type, "campaign_id") && !current.campaign_id?.trim()) {
      return "Campaign ID is required for this report.";
    }
    if (current.report_type === "legal_evidence_bundle" && !current.bundle_id?.trim() && !current.campaign_id?.trim()) {
      return "Provide a bundle ID or campaign ID for the legal evidence bundle report.";
    }
    if (current.report_type === "ai_decision_explanation" && !current.prediction_id?.trim() && !current.entity_key?.trim()) {
      return "Provide a prediction ID or entity key for the AI decision explanation report.";
    }
    return null;
  }

  async function handlePreview() {
    const nextRequest = sanitizeRequest(request);
    const validationError = validateRequest(nextRequest);
    if (validationError) {
      setError(validationError);
      setStatus(null);
      setPreview(null);
      return;
    }
    setLoading(true);
    setError(null);
    setStatus(null);
    try {
      const report = await generateReport({ ...nextRequest, format: "json" });
      setPreview(report);
      setStatus("Preview generated.");
    } catch (err) {
      setError(String(err));
      setPreview(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleDownload() {
    const nextRequest = sanitizeRequest(request);
    const validationError = validateRequest(nextRequest);
    if (validationError) {
      setError(validationError);
      setStatus(null);
      return;
    }
    setDownloading(true);
    setError(null);
    try {
      const filename = await downloadReport(nextRequest);
      setStatus(`Downloaded ${filename}`);
    } catch (err) {
      setError(String(err));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S8</p>
          <h2>Operational Reports</h2>
          <p className="subtle">
            Turn predictions, campaigns, and cases into readable outputs without losing audit context.
          </p>
        </div>
      </div>

      <ArchitectureFlow
        label="Report flow"
        title="How reports fit into the operating loop"
        summary="Reports should package one operational object clearly: a prediction, campaign, entity, or evidence bundle."
        steps={[
          { stage: "Source", title: "Choose one subject", detail: "Start from a prediction, entity, campaign, or legal bundle.", tone: "info" },
          { stage: "Brief", title: "Preview plain language", detail: "Read the executive summary before exporting anything.", tone: "accent" },
          { stage: "Evidence", title: "Keep governance attached", detail: "Attach findings, model state, and evidence references.", tone: "warning" },
          { stage: "Export", title: "Send the right format", detail: "Download the operator or leadership output you actually need.", tone: "danger" },
        ]}
      />

      <div className="grid-two reports-layout">
        <div className="panel workflow-stage-panel">
          <div className="panel-header">
            <h3>Report builder</h3>
            <span className="muted">Choose output and subject</span>
          </div>

          {!catalog ? (
            <div className="state-box">
              <Loader2 size={18} className="spin" />
              <p>Loading report catalog…</p>
            </div>
          ) : (
            <div className="workflow-stack">
              <label>
                <p className="label">Report type</p>
                <select
                  className="search"
                  value={request.report_type}
                  onChange={(event) => setRequest((current) => ({
                    ...current,
                    report_type: event.target.value as ReportType,
                  }))}
                >
                  {visibleReportTypes.map((item) => (
                    <option key={item.report_type} value={item.report_type}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </label>

              {!allowLegalReports && (
                <div className="info-note">
                  <ShieldCheck size={13} style={{ flexShrink: 0 }} />
                  <span>
                    Legal evidence bundle reports are shown only to central or legal-scope users.
                  </span>
                </div>
              )}

              {selectedType && (
                <div className="workflow-summary-banner">
                  <strong>{selectedType.title}</strong>
                  <div className="chip-row" style={{ marginTop: 10 }}>
                    {selectedType.audience.map((item) => (
                      <span key={item} className="chip mono">
                        {item}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <label>
                <p className="label">Period</p>
                <select
                  className="search"
                  value={request.period}
                  onChange={(event) => setRequest((current) => ({
                    ...current,
                    period: event.target.value as ReportPeriod,
                  }))}
                >
                  {catalog.periods.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                <p className="label">Format</p>
                <select
                  className="search"
                  value={request.format}
                  onChange={(event) => setRequest((current) => ({
                    ...current,
                    format: event.target.value as ReportFormat,
                  }))}
                >
                  {catalog.formats.map((item) => (
                    <option key={item} value={item}>
                      {item.toUpperCase()}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                <p className="label">Prediction type</p>
                <select
                  className="search"
                  value={request.prediction_type}
                  onChange={(event) => setRequest((current) => ({
                    ...current,
                    prediction_type: event.target.value,
                  }))}
                >
                  <option value="risk_gnn">risk_gnn</option>
                  <option value="corruption_risk">corruption_risk</option>
                </select>
              </label>

              <label>
                <p className="label">Classification</p>
                <select
                  className="search"
                  value={request.classification}
                  onChange={(event) => setRequest((current) => ({
                    ...current,
                    classification: event.target.value,
                  }))}
                >
                  <option value="PUBLIC">PUBLIC</option>
                  <option value="RESTRICTED">RESTRICTED</option>
                  <option value="INTERNAL">INTERNAL</option>
                </select>
              </label>

              {(requiresField(request.report_type, "entity_key") || request.report_type === "ai_decision_explanation") && (
                <div style={{ display: "grid", gap: 8 }}>
                  <label>
                    <p className="label">Entity key</p>
                    <input
                      className="search"
                      placeholder="Choose a live entity below or enter one manually"
                      value={request.entity_key ?? ""}
                      onChange={(event) => setRequest((current) => ({ ...current, entity_key: event.target.value }))}
                    />
                  </label>
                  {entitySuggestions.length > 0 && (
                    <div className="panel-subsection">
                      <h4>Live suggestions</h4>
                      <div className="chip-row">
                        {entitySuggestions.slice(0, 8).map((item) => (
                          <button
                            key={`${item.id}-${item.entity_key}`}
                            type="button"
                            className="chip mono"
                            onClick={() => setRequest((current) => ({ ...current, entity_key: item.entity_key }))}
                            title={`Score ${Number(item.score ?? 0).toFixed(2)}`}
                          >
                            {item.entity_key}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {(requiresField(request.report_type, "campaign_id") || request.report_type === "legal_evidence_bundle") && (
                <label>
                  <p className="label">Campaign ID</p>
                  <input
                    className="search"
                    placeholder="Campaign UUID"
                    value={request.campaign_id ?? ""}
                    onChange={(event) => setRequest((current) => ({ ...current, campaign_id: event.target.value }))}
                  />
                </label>
              )}

              {request.report_type === "legal_evidence_bundle" && (
                <label>
                  <p className="label">Bundle ID</p>
                  <input
                    className="search"
                    placeholder="Optional legal bundle ID"
                    value={request.bundle_id ?? ""}
                    onChange={(event) => setRequest((current) => ({ ...current, bundle_id: event.target.value }))}
                  />
                </label>
              )}

              {request.report_type === "ai_decision_explanation" && (
                <label>
                  <p className="label">Prediction ID</p>
                  <input
                    className="search"
                    placeholder="Optional prediction UUID"
                    value={request.prediction_id ?? ""}
                    onChange={(event) => setRequest((current) => ({ ...current, prediction_id: event.target.value }))}
                  />
                </label>
              )}

              {request.report_type === "model_governance" && (
                <label>
                  <p className="label">Model version</p>
                  <input
                    className="search"
                    placeholder="Optional model version"
                    value={request.model_version ?? ""}
                    onChange={(event) => setRequest((current) => ({ ...current, model_version: event.target.value }))}
                  />
                </label>
              )}

              <div className="chip-row" style={{ marginTop: 4 }}>
                <button className="btn-accent" type="button" onClick={() => void handlePreview()} disabled={loading}>
                  {loading ? "Generating…" : "Preview JSON"}
                </button>
                <button className="ghost" type="button" onClick={() => void handleDownload()} disabled={downloading}>
                  {downloading ? "Downloading…" : "Download report"}
                </button>
              </div>

              {status && <p className="muted">{status}</p>}
              {error && <p className="muted" style={{ color: "var(--danger, #ef4444)" }}>{error}</p>}
            </div>
          )}
        </div>

        <div className="panel workflow-stage-panel">
          <div className="panel-header">
            <h3>Preview and findings</h3>
            <span className="muted">Executive summary first</span>
          </div>

          {!preview ? (
            <div className="state-box">
              <FileText size={18} />
              <p>Generate a preview to inspect the plain-English summary.</p>
            </div>
          ) : (
            <div className="workflow-stack">
              <div className="workflow-summary-banner">
                <div>
                  <strong>{String(summary.headline ?? "Untitled report")}</strong>
                  <p className="muted" style={{ margin: "4px 0 0" }}>{String(summary.overview ?? "No overview available.")}</p>
                </div>
                <div>
                  <div className="label">Next step</div>
                  <div>{String(summary.next_step ?? "Not stated.")}</div>
                </div>
              </div>

              <div className="panel-subsection">
                <h4>Plain-English summary</h4>
                <p><strong>Why it matters:</strong> {String(summary.why_it_matters ?? "Not stated.")}</p>
                <p><strong>Confidence:</strong> {String(summary.confidence_statement ?? "Not stated.")}</p>
              </div>

              <div className="panel-subsection">
                <h4>Key findings</h4>
                <div className="list">
                  {findings.length === 0 ? (
                    <div className="list-item muted">No findings in preview.</div>
                  ) : findings.map((item, index) => (
                    <div key={`${item.title ?? "finding"}-${index}`} className="list-item">
                      <strong>{String(item.title ?? "Finding")}</strong>
                      <div className="muted">{String(item.plain_text ?? "")}</div>
                    </div>
                  ))}
                </div>
              </div>

              <details className="panel panel-details">
                <summary>
                  <span>Governance snapshot</span>
                  <span className="muted">Model and real-data state</span>
                </summary>
                <div className="chip-row">
                  <span className="chip mono">
                    model {String(governance.model_version ?? "n/a")}
                  </span>
                  <span className="chip mono">
                    prediction {String(governance.prediction_type ?? request.prediction_type ?? "n/a")}
                  </span>
                  <span className="chip mono">
                    real-data gate {String((governance.real_data_gate as Record<string, unknown> | undefined)?.passed ?? "n/a")}
                  </span>
                </div>
              </details>

              <div className="panel-subsection" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <ShieldCheck size={18} />
                <p className="muted" style={{ margin: 0 }}>
                  Each report is structured as summary, analyst detail, and evidence appendix.
                </p>
              </div>

              <details className="collapsible-panel">
                <summary>
                  <span>Raw preview payload</span>
                  <span className="muted">Open only if you need the JSON structure</span>
                </summary>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap", overflowX: "auto" }}>
                  {JSON.stringify(preview, null, 2)}
                </pre>
              </details>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
