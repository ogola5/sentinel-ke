const resolveApiBase = (): string => {
  // Explicit override (production builds set VITE_API_BASE_URL at build time)
  const fromEnv = String(import.meta.env.VITE_API_BASE_URL ?? "").trim();
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  // Default: relative URLs so all requests go through the Vite dev-server proxy.
  // Docker:  VITE_API_PROXY_TARGET=http://backend:8000  (set in docker-compose)
  // Local:   proxy falls back to http://localhost:8000
  // This avoids CORS entirely — the proxy is same-origin from the browser's view.
  return "";
};

const API_BASE = resolveApiBase();

const withBase = (path: string) => `${API_BASE}${path}`;

const withQuery = (
  path: string,
  query: Record<string, string | number | boolean | undefined | null>,
) => {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([k, v]) => {
    if (v === undefined || v === null) return;
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
  aiPredictions: (limit = 10, offset = 0, windowKey?: string) =>
    withQuery("/v1/ai/predictions", { limit, offset, window_key: windowKey }),
  aiFeedbackBase: () => withBase("/v1/ai/feedback"),
  aiPredictionExplanation: (predictionId: string) =>
    withBase(`/v1/ai/explanations/${encodeURIComponent(predictionId)}`),
  aiFeedbackSubmit: (predictionId: string, feedbackLabel: number, analystId: string, notes?: string) =>
    withQuery("/v1/ai/feedback", {
      prediction_id: predictionId,
      feedback_label: feedbackLabel,
      analyst_id: analystId,
      notes,
    }),
  aiFeedbackList: (limit = 50, offset = 0, analystId?: string) =>
    withQuery("/v1/ai/feedback", { limit, offset, analyst_id: analystId }),
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

  // Defense & Containment
  defenseIncidents: (limit = 20, offset = 0) => withQuery("/v1/defense/incidents/runs", { limit, offset }),
  defenseWebhooks: (section_code?: string) =>
    withQuery("/v1/defense/webhooks", section_code ? { section_code } : {}),
  defenseWebhookDeliveries: (limit = 50, offset = 0) =>
    withQuery("/v1/defense/webhooks/deliveries", { limit, offset }),
  defenseVulnerabilities: (limit = 20, status?: string) =>
    withQuery("/v1/defense/vulnerabilities", { limit, ...(status ? { status } : {}) }),

  // Federation
  federationPartners: (limit = 50) => withQuery("/v1/federation/partners", { limit }),
  federationPatterns: (limit = 50, hours = 24, minRisk = 0.6) =>
    withQuery("/v1/federation/stream", { limit, hours, min_risk: minRisk }),
  federationCorrelations: (limit = 20) => withQuery("/v1/federation/correlations", { limit }),

  // AI / GNN
  aiTrainingRuns: (limit = 10, offset = 0) => withQuery("/v1/ai/gnn/runs", { limit, offset }),
  aiGNNTrain: () => withBase("/v1/ai/gnn/train"),
  aiIndicatorsSummary: (days = 7) => withQuery("/v1/ai/indicators/summary", { days }),

  // Demo data seeding
  demoIngestCyber: () => withBase("/v1/demo/ingest-synthetic-gnn-data"),
  demoIngestCorruption: () => withBase("/v1/demo/ingest-corruption-data"),

  // Crypto posture
  cryptoPosture: () => withBase("/v1/crypto/posture"),
  cryptoSelfTest: () => withBase("/v1/crypto/posture/self-test"),

  // AI forecasting, tool attribution, paths, fusion, NL copilot
  aiForecast: (days = 30, horizon = 7, alpha = 0.3, beta = 0.1) =>
    withQuery("/v1/ai/forecast", { days, horizon, alpha, beta }),
  aiToolAttribution: (entityKey: string) =>
    withQuery("/v1/ai/tool-attribution", { entity_key: entityKey }),
  aiToolsSummary: (limit = 10) => withQuery("/v1/ai/tools/summary", { limit }),
  aiPaths: (entityKey: string, windowKey?: string) =>
    withQuery("/v1/ai/paths", { entity_key: entityKey, window_key: windowKey }),
  aiFusion: (entityKey: string, windowKey?: string) =>
    withQuery("/v1/ai/fusion", { entity_key: entityKey, window_key: windowKey }),
  aiQuery: () => withBase("/v1/ai/query"),

  // Real-time SSE stream
  // Pass ?token=<FRONTEND_API_KEY> — EventSource cannot set custom headers
  eventStream: (apiKey?: string) =>
    withBase(apiKey ? `/v1/stream/events?token=${encodeURIComponent(apiKey)}` : "/v1/stream/events"),

  // Auth
  authLogin: () => withBase("/v1/auth/login"),
  authRefresh: () => withBase("/v1/auth/refresh"),
  authLogout: () => withBase("/v1/auth/logout"),
  authMe: () => withBase("/v1/auth/me"),
  authUsers: (q: Record<string, string | number | boolean | undefined | null> = {}) => withQuery("/v1/auth/users", q),
  authUsersCreate: () => withBase("/v1/auth/users"),
  authUserPasswordReset: (username: string) =>
    withBase(`/v1/auth/users/${encodeURIComponent(username)}/password/reset`),
  authPolicies: () => withBase("/v1/auth/policies"),
};

export type Endpoints = typeof endpoints;
