import { apiFetchJson } from "./client";
import { endpoints } from "./endpoints";
import type {
  OperationsSnapshot,
  OpsLeakageSummary,
} from "../types/operations";

type ListResponse = {
  items?: Array<Record<string, unknown>>;
};

type MetricsResponse = {
  events?: unknown;
  graph_deltas?: unknown;
  anomalies?: unknown;
  mitigations?: unknown;
};

type IocExportResponse = {
  count?: unknown;
  actions?: unknown[];
  iocs?: {
    ips?: unknown[];
    domains?: unknown[];
    providers?: unknown[];
    endpoints?: unknown[];
  };
};

type AIExplanationResponse = {
  evidence_hashes?: unknown[];
};

type LeakageSummaryResponse = {
  window_days?: unknown;
  total_alerts?: unknown;
  suspected_amount_total?: unknown;
  by_detector?: Record<string, unknown>;
  by_severity?: Record<string, unknown>;
};

const asString = (value: unknown, fallback = ""): string => {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return fallback;
  return String(value);
};

const asNumber = (value: unknown, fallback = 0): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const asStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  return value.map((v) => asString(v, "")).filter((v) => v !== "");
};

const toClock = (iso: unknown): string => {
  if (typeof iso !== "string" || iso.trim() === "") return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

const toCounts = (input: Record<string, unknown> | undefined): Record<string, number> => {
  if (!input) return {};
  return Object.fromEntries(Object.entries(input).map(([k, v]) => [k, asNumber(v, 0)]));
};

const fallbackSnapshot: OperationsSnapshot = {
  metrics: { events: 0, graphDeltas: 0, anomalies: 0, mitigations: 0 },
  anomalies: [],
  mitigations: [],
  iocExport: { records: 0, actions: 0, ips: 0, domains: 0, providers: 0, endpoints: 0 },
  predictions: [],
  economySignals: [],
  procurementAnomalies: [],
  guardrailDecisions: [],
  integrityAlerts: [],
  leakageAlerts: [],
  leakageSummary: {
    windowDays: 30,
    totalAlerts: 0,
    suspectedAmountTotal: 0,
    byDetector: {},
    bySeverity: {},
  },
};

const safeFetch = async <T>(fn: () => Promise<T>, fallback: T): Promise<T> => {
  try {
    return await fn();
  } catch {
    return fallback;
  }
};

const mapLeakageSummary = (res: LeakageSummaryResponse): OpsLeakageSummary => ({
  windowDays: asNumber(res.window_days, 30),
  totalAlerts: asNumber(res.total_alerts, 0),
  suspectedAmountTotal: asNumber(res.suspected_amount_total, 0),
  byDetector: toCounts(res.by_detector),
  bySeverity: toCounts(res.by_severity),
});

export async function fetchOperationsSnapshot(): Promise<OperationsSnapshot> {
  const [
    metricsRes,
    anomaliesRes,
    mitigationsRes,
    iocExportRes,
    predictionsRes,
    economySignalsRes,
    procurementRes,
    guardrailRes,
    integrityRes,
    leakageAlertsRes,
    leakageSummaryRes,
  ] = await Promise.all([
    safeFetch(() => apiFetchJson<MetricsResponse>(endpoints.metrics()), {}),
    safeFetch(() => apiFetchJson<ListResponse>(endpoints.anomalies(8, 0)), {}),
    safeFetch(() => apiFetchJson<ListResponse>(endpoints.mitigations(8, 0)), {}),
    safeFetch(() => apiFetchJson<IocExportResponse>(endpoints.mitigationsExport()), {}),
    safeFetch(() => apiFetchJson<ListResponse>(endpoints.aiPredictions(8, 0)), {}),
    safeFetch(() => apiFetchJson<ListResponse>(endpoints.economySignals(8, 0)), {}),
    safeFetch(() => apiFetchJson<ListResponse>(endpoints.economyProcurementAnomalies(8, 0)), {}),
    safeFetch(() => apiFetchJson<ListResponse>(endpoints.economyGuardrailDecisions(8, 0)), {}),
    safeFetch(() => apiFetchJson<ListResponse>(endpoints.economyIntegrityAlerts(8, 0)), {}),
    safeFetch(() => apiFetchJson<ListResponse>(endpoints.economyLeakageAlerts(8, 0)), {}),
    safeFetch(() => apiFetchJson<LeakageSummaryResponse>(endpoints.economyLeakageSummary(30)), {}),
  ]);

  const predictionItems = predictionsRes.items ?? [];
  const explanations = await Promise.all(
    predictionItems.slice(0, 8).map(async (item) => {
      const id = asString(item.id, "");
      if (!id) return { id: "", evidenceCount: 0 };
      const explanation = await safeFetch(
        () => apiFetchJson<AIExplanationResponse>(endpoints.aiPredictionExplanation(id)),
        {},
      );
      return {
        id,
        evidenceCount: Array.isArray(explanation.evidence_hashes) ? explanation.evidence_hashes.length : 0,
      };
    }),
  );
  const evidenceMap = new Map(explanations.map((e) => [e.id, e.evidenceCount]));

  return {
    metrics: {
      events: asNumber(metricsRes.events, 0),
      graphDeltas: asNumber(metricsRes.graph_deltas, 0),
      anomalies: asNumber(metricsRes.anomalies, 0),
      mitigations: asNumber(metricsRes.mitigations, 0),
    },
    anomalies: (anomaliesRes.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      serviceId: asString(item.service_id, "unknown"),
      endpoint: asString(item.endpoint, "n/a"),
      score: asNumber(item.score, 0),
      reasonCodes: asStringArray(item.reason_codes),
      windowEnd: toClock(item.window_end),
    })),
    mitigations: (mitigationsRes.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      kind: asString(item.kind, "mitigation"),
      refId: asString(item.ref_id, "n/a"),
      stakeholders: asStringArray(item.stakeholders),
      createdAt: toClock(item.created_at),
    })),
    iocExport: {
      records: asNumber(iocExportRes.count, 0),
      actions: Array.isArray(iocExportRes.actions) ? iocExportRes.actions.length : 0,
      ips: Array.isArray(iocExportRes.iocs?.ips) ? iocExportRes.iocs?.ips.length : 0,
      domains: Array.isArray(iocExportRes.iocs?.domains) ? iocExportRes.iocs?.domains.length : 0,
      providers: Array.isArray(iocExportRes.iocs?.providers) ? iocExportRes.iocs?.providers.length : 0,
      endpoints: Array.isArray(iocExportRes.iocs?.endpoints) ? iocExportRes.iocs?.endpoints.length : 0,
    },
    predictions: predictionItems.map((item) => {
      const id = asString(item.id, "");
      return {
        id,
        entityKey: asString(item.entity_key, "unknown"),
        predictionType: asString(item.prediction_type, "risk"),
        score: asNumber(item.score, 0),
        reasonCodes: asStringArray(item.reason_codes),
        evidenceCount: evidenceMap.get(id) ?? 0,
      };
    }),
    economySignals: (economySignalsRes.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      signalType: asString(item.signal_type, "signal"),
      agency: asString(item.agency, "unknown"),
      sector: asString(item.sector, "unknown"),
      severity: asString(item.severity, "low"),
      score: asNumber(item.score, 0),
    })),
    procurementAnomalies: (procurementRes.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      tenderId: asString(item.tender_id, "n/a"),
      vendorId: asString(item.vendor_id, "n/a"),
      agency: asString(item.agency, "unknown"),
      severity: asString(item.severity, "low"),
      score: asNumber(item.score, 0),
    })),
    guardrailDecisions: (guardrailRes.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      tenderId: asString(item.tender_id, "n/a"),
      vendorId: asString(item.vendor_id, "n/a"),
      decision: asString(item.decision, "allow"),
      severity: asString(item.severity, "low"),
      score: asNumber(item.score, 0),
    })),
    integrityAlerts: (integrityRes.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      sourceSystem: asString(item.source_system, "unknown"),
      recordType: asString(item.record_type, "record"),
      alertType: asString(item.alert_type, "tamper"),
      severity: asString(item.severity, "low"),
      status: asString(item.status, "open"),
      confidence: asNumber(item.confidence, 0),
    })),
    leakageAlerts: (leakageAlertsRes.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      detectorType: asString(item.detector_type, "detector"),
      agency: asString(item.agency, "unknown"),
      vendorId: asString(item.vendor_id, "n/a"),
      severity: asString(item.severity, "low"),
      score: asNumber(item.score, 0),
    })),
    leakageSummary: mapLeakageSummary(leakageSummaryRes),
  };
}

export async function runLeakageDetection(windowDays = 30): Promise<OperationsSnapshot["leakageSummary"]> {
  await safeFetch(
    () => apiFetchJson<Record<string, unknown>>(endpoints.economyLeakageRun(windowDays), { method: "POST" }),
    {},
  );
  const summary = await safeFetch(
    () => apiFetchJson<LeakageSummaryResponse>(endpoints.economyLeakageSummary(windowDays)),
    {},
  );
  return mapLeakageSummary(summary);
}

export const operationsFallbackSnapshot = fallbackSnapshot;
