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

  const selectedType = useMemo(
    () => catalog?.report_types.find((item) => item.report_type === request.report_type),
    [catalog, request.report_type],
  );

  const summary = (preview?.summary as Record<string, unknown> | undefined) ?? {};
  const findings = Array.isArray(preview?.findings) ? (preview?.findings as Array<Record<string, unknown>>) : [];
  const governance = (preview?.governance as Record<string, unknown> | undefined) ?? {};

  async function handlePreview() {
    setLoading(true);
    setError(null);
    setStatus(null);
    try {
      const report = await generateReport({ ...request, format: "json" });
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
    setDownloading(true);
    setError(null);
    try {
      const filename = await downloadReport(request);
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

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>Report Builder</h3>
            <span className="muted">HTML or JSON download</span>
          </div>

          {!catalog ? (
            <div className="state-box">
              <Loader2 size={18} className="spin" />
              <p>Loading report catalog…</p>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 14 }}>
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
                <label>
                  <p className="label">Entity key</p>
                  <input
                    className="search"
                    placeholder="ip:1.2.3.4 or account_h:..."
                    value={request.entity_key ?? ""}
                    onChange={(event) => setRequest((current) => ({ ...current, entity_key: event.target.value }))}
                  />
                </label>
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
                <button className="ghost" type="button" onClick={() => void handlePreview()} disabled={loading}>
                  {loading ? "Generating…" : "Preview JSON"}
                </button>
                <button className="ghost" type="button" onClick={() => void handleDownload()} disabled={downloading}>
                  {downloading ? "Downloading…" : "Download report"}
                </button>
              </div>

              {selectedType && (
                <div className="panel-subsection">
                  <h4>{selectedType.title}</h4>
                  <p className="muted">{selectedType.description}</p>
                  <div className="chip-row">
                    {selectedType.audience.map((item) => (
                      <span key={item} className="chip mono">
                        {item}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {status && <p className="muted">{status}</p>}
              {error && <p className="muted" style={{ color: "var(--danger, #ef4444)" }}>{error}</p>}
            </div>
          )}
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Preview</h3>
            <span className="muted">Non-technical first</span>
          </div>

          {!preview ? (
            <div className="state-box">
              <FileText size={18} />
              <p>Generate a preview to inspect the plain-English summary.</p>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 14 }}>
              <div className="panel-subsection">
                <h4>{String(summary.headline ?? "Untitled report")}</h4>
                <p>{String(summary.overview ?? "No overview available.")}</p>
                <p><strong>Why it matters:</strong> {String(summary.why_it_matters ?? "Not stated.")}</p>
                <p><strong>Next step:</strong> {String(summary.next_step ?? "Not stated.")}</p>
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
            </div>
          )}
        </div>
      </div>

      {preview && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="panel-header">
            <h3>Raw Preview Payload</h3>
            <span className="muted">JSON structure returned by the backend</span>
          </div>
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", overflowX: "auto" }}>
            {JSON.stringify(preview, null, 2)}
          </pre>
        </div>
      )}
    </section>
  );
}
