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

export const emptyOperationsSnapshot: OperationsSnapshot = {
  metrics: { events: 0, graphDeltas: 0, anomalies: 0, mitigations: 0 },
  availability: {
    cyberFeedsOk: false,
    integrityFeedsOk: false,
    leakageFeedsOk: false,
  },
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

type ApiSliceResult<T> = {
  ok: boolean;
  value: T;
};

const safeFetch = async <T>(fn: () => Promise<T>, fallback: T): Promise<ApiSliceResult<T>> => {
  try {
    return { ok: true, value: await fn() };
  } catch {
    return { ok: false, value: fallback };
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

  const slices = [
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
  ];
  if (slices.every((slice) => !slice.ok)) {
    throw new Error("operations_endpoints_unavailable");
  }

  const predictionItems = predictionsRes.value.items ?? [];
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
        evidenceCount: Array.isArray(explanation.value.evidence_hashes) ? explanation.value.evidence_hashes.length : 0,
      };
    }),
  );
  const evidenceMap = new Map(explanations.map((e) => [e.id, e.evidenceCount]));

  return {
    metrics: {
      events: asNumber(metricsRes.value.events, 0),
      graphDeltas: asNumber(metricsRes.value.graph_deltas, 0),
      anomalies: asNumber(metricsRes.value.anomalies, 0),
      mitigations: asNumber(metricsRes.value.mitigations, 0),
    },
    availability: {
      cyberFeedsOk: metricsRes.ok || anomaliesRes.ok || predictionsRes.ok || mitigationsRes.ok,
      integrityFeedsOk: economySignalsRes.ok || procurementRes.ok || guardrailRes.ok || integrityRes.ok,
      leakageFeedsOk: leakageAlertsRes.ok || leakageSummaryRes.ok,
    },
    anomalies: (anomaliesRes.value.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      serviceId: asString(item.service_id, "unknown"),
      endpoint: asString(item.endpoint, "n/a"),
      score: asNumber(item.score, 0),
      reasonCodes: asStringArray(item.reason_codes),
      windowEnd: toClock(item.window_end),
    })),
    mitigations: (mitigationsRes.value.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      kind: asString(item.kind, "mitigation"),
      refId: asString(item.ref_id, "n/a"),
      stakeholders: asStringArray(item.stakeholders),
      createdAt: toClock(item.created_at),
    })),
    iocExport: {
      records: asNumber(iocExportRes.value.count, 0),
      actions: Array.isArray(iocExportRes.value.actions) ? iocExportRes.value.actions.length : 0,
      ips: Array.isArray(iocExportRes.value.iocs?.ips) ? iocExportRes.value.iocs?.ips.length : 0,
      domains: Array.isArray(iocExportRes.value.iocs?.domains) ? iocExportRes.value.iocs?.domains.length : 0,
      providers: Array.isArray(iocExportRes.value.iocs?.providers) ? iocExportRes.value.iocs?.providers.length : 0,
      endpoints: Array.isArray(iocExportRes.value.iocs?.endpoints) ? iocExportRes.value.iocs?.endpoints.length : 0,
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
    economySignals: (economySignalsRes.value.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      signalType: asString(item.signal_type, "signal"),
      agency: asString(item.agency, "unknown"),
      sector: asString(item.sector, "unknown"),
      severity: asString(item.severity, "low"),
      score: asNumber(item.score, 0),
    })),
    procurementAnomalies: (procurementRes.value.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      tenderId: asString(item.tender_id, "n/a"),
      vendorId: asString(item.vendor_id, "n/a"),
      agency: asString(item.agency, "unknown"),
      amount: asNumber(item.amount, 0),
      severity: asString(item.severity, "low"),
      score: asNumber(item.score, 0),
    })),
    guardrailDecisions: (guardrailRes.value.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      tenderId: asString(item.tender_id, "n/a"),
      vendorId: asString(item.vendor_id, "n/a"),
      decision: asString(item.decision, "allow"),
      severity: asString(item.severity, "low"),
      score: asNumber(item.score, 0),
    })),
    integrityAlerts: (integrityRes.value.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      sourceSystem: asString(item.source_system, "unknown"),
      recordType: asString(item.record_type, "record"),
      alertType: asString(item.alert_type, "tamper"),
      severity: asString(item.severity, "low"),
      status: asString(item.status, "open"),
      confidence: asNumber(item.confidence, 0),
    })),
    leakageAlerts: (leakageAlertsRes.value.items ?? []).map((item) => ({
      id: asString(item.id, ""),
      detectorType: asString(item.detector_type, "detector"),
      agency: asString(item.agency, "unknown"),
      vendorId: asString(item.vendor_id, "n/a"),
      severity: asString(item.severity, "low"),
      score: asNumber(item.score, 0),
    })),
    leakageSummary: mapLeakageSummary(leakageSummaryRes.value),
  };
}

export async function runLeakageDetection(windowDays = 30): Promise<OperationsSnapshot["leakageSummary"]> {
  await apiFetchJson<Record<string, unknown>>(
    endpoints.economyLeakageRun(windowDays),
    { method: "POST" },
    { requireLegalGrantToken: true },
  );
  const summary = await safeFetch(
    () => apiFetchJson<LeakageSummaryResponse>(endpoints.economyLeakageSummary(windowDays)),
    {},
  );
  return mapLeakageSummary(summary.value);
}
