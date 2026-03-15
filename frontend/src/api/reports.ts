import { apiFetchBlob, apiFetchJson } from "./client";
import { endpoints } from "./endpoints";

export type ReportType =
  | "incident_brief"
  | "entity_investigation"
  | "campaign_case"
  | "legal_evidence_bundle"
  | "ai_decision_explanation"
  | "model_governance";

export type ReportPeriod =
  | "hourly"
  | "daily"
  | "weekly"
  | "monthly"
  | "quarterly"
  | "semi_annual"
  | "annual";

export type ReportFormat = "json" | "html" | "pdf";

export type ReportRequest = {
  report_type: ReportType;
  period: ReportPeriod;
  format: ReportFormat;
  prediction_type?: string;
  entity_key?: string;
  campaign_id?: string;
  bundle_id?: string;
  prediction_id?: string;
  model_version?: string;
  classification?: string;
};

export type ReportCatalog = {
  report_types: Array<{
    report_type: ReportType;
    title: string;
    audience: string[];
    description: string;
    required_fields: string[];
    supported_formats: ReportFormat[];
  }>;
  periods: Array<{ id: ReportPeriod; label: string; lookback_days: number }>;
  formats: ReportFormat[];
};

export async function fetchReportCatalog(): Promise<ReportCatalog> {
  return apiFetchJson<ReportCatalog>(endpoints.reportsCatalog());
}

export async function generateReport(payload: ReportRequest): Promise<Record<string, unknown>> {
  return apiFetchJson<Record<string, unknown>>(endpoints.reportsGenerate(), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

function parseFilename(headerValue: string | null, fallback: string): string {
  if (!headerValue) return fallback;
  const match = headerValue.match(/filename="?([^"]+)"?/i);
  return match?.[1] ?? fallback;
}

export async function downloadReport(payload: ReportRequest): Promise<string> {
  const { response, blob } = await apiFetchBlob(endpoints.reportsDownload(), {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const extension = payload.format === "html" ? "html" : payload.format === "pdf" ? "pdf" : "json";
  const fallback = `sentinel-${payload.report_type}.${extension}`;
  const filename = parseFilename(response.headers.get("Content-Disposition"), fallback);
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
  return filename;
}
