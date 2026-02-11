const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

const withBase = (path: string) => `${API_BASE}${path}`;

const withQuery = (path: string, query: Record<string, string | number | undefined>) => {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([k, v]) => {
    if (v === undefined) return;
    params.set(k, String(v));
  });
  const qs = params.toString();
  return withBase(qs ? `${path}?${qs}` : path);
};

export const endpoints = {
  health: () => withBase("/health"),
  ready: () => withBase("/ready"),
  eventsSearch: (size = 100) => withQuery("/v1/events/search", { size }),
  eventsTimeline: (startIso: string, endIso: string, interval = "5m") =>
    withQuery("/v1/events/timeline", { start: startIso, end: endIso, interval }),
  campaigns: (limit = 20, offset = 0) => withQuery("/v1/campaigns", { limit, offset }),
  campaignEvidence: (campaignId: string, limit = 200) =>
    withQuery(`/v1/campaigns/${encodeURIComponent(campaignId)}/evidence`, { limit }),
  ddosAlerts: (limit = 20, offset = 0) => withQuery("/v1/ddos/alerts", { limit, offset }),
  ddosIndicators: (serviceId: string, endpoint?: string, minutes = 60) =>
    withQuery("/v1/ddos/indicators", {
      service_id: serviceId,
      endpoint,
      minutes,
      bucket: "5m",
    }),
  infraClusters: (limit = 10, offset = 0) => withQuery("/v1/infra/clusters", { limit, offset }),
  infraClusterById: (clusterId: string) => withBase(`/v1/infra/clusters/${encodeURIComponent(clusterId)}`),
  metrics: () => withBase("/v1/metrics"),
  anomalies: (limit = 10, offset = 0) => withQuery("/v1/anomalies", { limit, offset }),
  mitigations: (limit = 10, offset = 0) => withQuery("/v1/mitigations", { limit, offset }),
  mitigationsExport: () => withBase("/v1/mitigations/export"),
  aiPredictions: (limit = 10, offset = 0) => withQuery("/v1/ai/predictions", { limit, offset }),
  aiPredictionExplanation: (predictionId: string) =>
    withBase(`/v1/ai/explanations/${encodeURIComponent(predictionId)}`),
  economySignals: (limit = 10, offset = 0) => withQuery("/v1/economy/signals", { limit, offset }),
  economyProcurementAnomalies: (limit = 10, offset = 0) =>
    withQuery("/v1/economy/procurement/anomalies", { limit, offset }),
  economyGuardrailDecisions: (limit = 10, offset = 0) =>
    withQuery("/v1/economy/guardrail/decisions", { limit, offset }),
  economyIntegrityAlerts: (limit = 10, offset = 0) =>
    withQuery("/v1/economy/integrity/alerts", { limit, offset }),
  economyLeakageAlerts: (limit = 10, offset = 0) =>
    withQuery("/v1/economy/leakage/alerts", { limit, offset }),
  economyLeakageSummary: (windowDays = 30) =>
    withQuery("/v1/economy/leakage/summary", { window_days: windowDays }),
  economyLeakageRun: (windowDays = 30) =>
    withQuery("/v1/economy/leakage/run", { window_days: windowDays }),
  caseFromCampaign: (campaignId: string) =>
    withBase(`/v1/cases/from-campaign/${encodeURIComponent(campaignId)}`),
  stixCaseByCampaign: (campaignId: string) =>
    withBase(`/v1/stix/case/${encodeURIComponent(campaignId)}`),
};

export type Endpoints = typeof endpoints;
