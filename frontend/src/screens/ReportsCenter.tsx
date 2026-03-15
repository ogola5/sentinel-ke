import { useEffect, useMemo, useState } from "react";
import { FileText, Loader2, ShieldCheck } from "lucide-react";

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

export default function ReportsCenter() {
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
            Generate downloadable legal, explainability, investigation, and governance reports in plain English.
          </p>
        </div>
      </div>

      <div className="panel workflow-guide-panel" style={{ background: "rgba(var(--accent-rgb), 0.08)", borderColor: "rgba(var(--accent-rgb), 0.28)" }}>
        <div className="panel-header">
          <h3>How to use this page</h3>
          <span className="muted">Build one report at a time</span>
        </div>
        <div className="detail-grid">
          <div>
            <p className="label">Step 1</p>
            <p>Choose the report type first. That decides what subject fields matter.</p>
          </div>
          <div>
            <p className="label">Step 2</p>
            <p>Use a real entity, campaign, bundle, or prediction instead of a placeholder example.</p>
          </div>
          <div>
            <p className="label">Step 3</p>
            <p>Preview before download so the plain-English summary is checked first.</p>
          </div>
          <div>
            <p className="label">Best use</p>
            <p>Use entity reports for operators, campaign reports for escalation, decision explanations for oversight, and legal bundles for evidence handling.</p>
          </div>
        </div>
      </div>

      <div className="grid-two reports-layout">
        <div className="panel workflow-stage-panel">
          <div className="panel-header">
            <h3>1. Report Builder</h3>
            <span className="muted">HTML, PDF, or JSON download</span>
          </div>

          {!catalog ? (
            <div className="state-box">
              <Loader2 size={18} className="spin" />
              <p>Loading report catalog…</p>
            </div>
          ) : (
            <div className="workflow-stack">
              <div className="panel-subsection">
                <h4>Choose the output</h4>
                <p className="muted" style={{ marginTop: 6 }}>
                  Start with the type, period, format, prediction family, and classification.
                </p>
              </div>
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
                  {catalog.report_types.map((item) => (
                    <option key={item.report_type} value={item.report_type}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </label>

              {selectedType && (
                <div className="workflow-summary-banner">
                  <strong>{selectedType.title}</strong>
                  <p className="muted" style={{ margin: "4px 0 0" }}>{selectedType.description}</p>
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

              <div className="panel-subsection">
                <h4>Choose the subject</h4>
                <p className="muted" style={{ marginTop: 6 }}>
                  Only fill the fields required for the selected report type.
                </p>
              </div>

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

              <div className="panel-subsection">
                <h4>Preview or download</h4>
                <p className="muted" style={{ marginTop: 6 }}>
                  Preview is the safe first step. Download when the summary and findings look right.
                </p>
              </div>

              <div className="chip-row" style={{ marginTop: 4 }}>
                <button className="ghost" type="button" onClick={() => void handlePreview()} disabled={loading}>
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
            <h3>2. Preview and findings</h3>
            <span className="muted">Non-technical first</span>
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

              <div className="panel-subsection">
                <h4>Governance snapshot</h4>
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
              </div>

              <div className="panel-subsection" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <ShieldCheck size={18} />
                <p className="muted" style={{ margin: 0 }}>
                  Reports are designed in three layers: plain-English summary, analyst detail, and evidence appendix.
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
