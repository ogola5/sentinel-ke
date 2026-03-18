import { ApiError, apiFetchJson } from "./client";
import { endpoints } from "./endpoints";
import type {
  AIFeedback,
  AIDriftReport,
  AIPrediction,
  AIScenarioForecast,
  CryptoPosture,
  EntityTrustSummary,
  GNNTrainingRun,
  PlatformTrustSummary,
  SelfTestResult,
} from "../types/ai";

interface ListResponse<T> {
  total?: number;
  items: T[];
}

interface QueryOptions {
  strict?: boolean;
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

const asNumber = (value: unknown, fallback = 0): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const asString = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;

const asBoolean = (value: unknown): boolean => value === true;

export async function triggerGNNTrain(
  domain: "cyber" | "corruption",
  epochs = 25,
  options: {
    waitForCompletion?: boolean;
    allowDemoRealDataOverride?: boolean;
    allowDemoFairnessOverride?: boolean;
  } = {},
): Promise<Record<string, unknown>> {
  return apiFetchJson(endpoints.aiGNNTrain(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      domain,
      epochs,
      wait_for_completion: options.waitForCompletion ?? true,
      allow_demo_real_data_override: options.allowDemoRealDataOverride ?? true,
      allow_demo_fairness_override: options.allowDemoFairnessOverride ?? true,
    }),
  });
}

export async function seedDemoData(
  domain: "cyber" | "corruption",
): Promise<{ accepted: boolean; domain: string; message: string }> {
  const url = domain === "cyber" ? endpoints.demoIngestCyber() : endpoints.demoIngestCorruption();
  return apiFetchJson(url, { method: "POST" });
}

export async function bootstrapDemoData(
  domain: "cyber" | "corruption",
  scenario = "ddos_vpn_fraud",
): Promise<{ accepted: boolean; domain: string; scenario: string; message: string }> {
  return apiFetchJson(endpoints.demoBootstrap(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      domain,
      scenario,
      epochs: 25,
      allow_demo_real_data_override: true,
      allow_demo_fairness_override: true,
    }),
  });
}

export async function startDemoScenario(
  scenario: string,
): Promise<{ accepted: boolean; status: string; scenario: string; normalized_scenario?: string; message?: string }> {
  return apiFetchJson(endpoints.demoScenarioStart(scenario), { method: "POST" });
}

export async function fetchGNNTrainingRuns(limit = 10, options: QueryOptions = {}): Promise<GNNTrainingRun[]> {
  try {
    const data = await apiFetchJson<ListResponse<GNNTrainingRun> | GNNTrainingRun[]>(
      endpoints.aiTrainingRuns(limit),
    );
    return Array.isArray(data) ? data : (data.items ?? []);
  } catch (err) {
    if (options.strict || !(err instanceof ApiError) || err.status >= 500 || err.status === 401 || err.status === 403) {
      throw err;
    }
    return [];
  }
}

export async function fetchAIPredictions(limit = 20, windowKey?: string, options: QueryOptions = {}): Promise<AIPrediction[]> {
  try {
    const data = await apiFetchJson<ListResponse<AIPrediction> | AIPrediction[]>(
      endpoints.aiPredictions(limit, 0, windowKey),
    );
    return Array.isArray(data) ? data : (data.items ?? []);
  } catch (err) {
    if (options.strict || !(err instanceof ApiError) || err.status >= 500 || err.status === 401 || err.status === 403) {
      throw err;
    }
    return [];
  }
}

export async function fetchEntityPredictions(
  entityKey: string,
  options: {
    limit?: number;
    predictionType?: string;
    windowKey?: string;
    strict?: boolean;
  } = {},
): Promise<AIPrediction[]> {
  try {
    const data = await apiFetchJson<ListResponse<AIPrediction> | AIPrediction[]>(
      endpoints.aiPredictionsByEntity(entityKey, options.limit ?? 20, 0, options.windowKey, options.predictionType),
    );
    return Array.isArray(data) ? data : (data.items ?? []);
  } catch (err) {
    if (options.strict || !(err instanceof ApiError) || err.status >= 500 || err.status === 401 || err.status === 403) {
      throw err;
    }
    return [];
  }
}

export async function fetchPredictionExplanation(
  predictionId: string,
): Promise<Record<string, unknown> | null> {
  try {
    return await apiFetchJson<Record<string, unknown>>(endpoints.aiPredictionExplanation(predictionId));
  } catch {
    return null;
  }
}

export async function submitAIFeedback(
  predictionId: string,
  feedbackLabel: 0 | 1 | 2,
  analystId: string,
  notes?: string,
): Promise<AIFeedback | null> {
  try {
    return await apiFetchJson<AIFeedback>(
      endpoints.aiFeedbackSubmit(predictionId, feedbackLabel, analystId, notes),
      { method: "POST" },
    );
  } catch {
    return null;
  }
}

export async function fetchAIFeedback(analystId: string, limit = 200): Promise<AIFeedback[]> {
  try {
    const data = await apiFetchJson<ListResponse<AIFeedback> | AIFeedback[]>(
      endpoints.aiFeedbackList(limit, 0, analystId),
    );
    return Array.isArray(data) ? data : (data.items ?? []);
  } catch {
    return [];
  }
}

export async function submitFeedback(
  predictionId: string,
  feedbackLabel: 0 | 1 | 2,
  analystId: string,
  notes?: string,
): Promise<void> {
  const response = await submitAIFeedback(predictionId, feedbackLabel, analystId, notes);
  if (!response) {
    throw new Error("feedback_submit_failed");
  }
}

export async function fetchCryptoPosture(): Promise<CryptoPosture | null> {
  try {
    const raw = await apiFetchJson<unknown>(endpoints.cryptoPosture());
    const data = asRecord(raw);
    const alg = asRecord(data.algorithms);
    const signature = asRecord(alg.digital_signature);
    const kdf = asRecord(alg.password_kdf);
    const nist = asRecord(data.nist_compliance);
    const fips203 = asBoolean(nist["FIPS-203"]);
    const fips204 = asBoolean(nist["FIPS-204"]);
    const fips197 = asBoolean(nist["FIPS-197"]);
    const compliant = fips203 && fips204 && fips197 && asString(data.pqc_mode, "").toLowerCase() !== "classical";

    return {
      pqc_mode: asString(data.pqc_mode, "unknown"),
      tls_mode: asString(data.tls_mode, "unknown"),
      kms_provider: asString(data.kms_provider, "unknown"),
      key_rotation_days: asNumber(data.key_rotation_days, 90),
      signing_alg: asString(signature.id, "unknown"),
      password_kdf: asString(kdf.id, "unknown"),
      compliant,
      details_json: data,
      algorithms: alg,
      token_format: asRecord(data.token_format),
      mfa_encryption: asRecord(data.mfa_encryption),
      nist_compliance: {
        "FIPS-203": fips203,
        "FIPS-204": fips204,
        "FIPS-197": fips197,
      },
    };
  } catch {
    return null;
  }
}

export async function fetchAIForecast(
  days = 30,
  horizon = 7,
): Promise<Record<string, unknown> | null> {
  try {
    return await apiFetchJson<Record<string, unknown>>(endpoints.aiForecast(days, horizon));
  } catch {
    return null;
  }
}

export async function fetchAIScenarioForecast(
  scenario: string,
  lookbackHours = 48,
  horizonHours = 24,
): Promise<AIScenarioForecast | null> {
  try {
    return await apiFetchJson<AIScenarioForecast>(
      endpoints.aiScenarioForecast(scenario, lookbackHours, horizonHours),
    );
  } catch {
    return null;
  }
}

export async function fetchToolAttribution(entityKey: string): Promise<Record<string, unknown> | null> {
  try {
    return await apiFetchJson<Record<string, unknown>>(endpoints.aiToolAttribution(entityKey));
  } catch {
    return null;
  }
}

export async function fetchToolsSummary(limit = 10): Promise<Record<string, unknown>[]> {
  try {
    const data = await apiFetchJson<{ items?: Record<string, unknown>[] } | Record<string, unknown>[]>(
      endpoints.aiToolsSummary(limit),
    );
    return Array.isArray(data) ? data : (data.items ?? []);
  } catch {
    return [];
  }
}

export async function fetchEntityPaths(
  entityKey: string,
  windowKey?: string,
): Promise<Record<string, unknown> | null> {
  try {
    return await apiFetchJson<Record<string, unknown>>(endpoints.aiPaths(entityKey, windowKey));
  } catch {
    return null;
  }
}

export async function fetchEntityFusion(
  entityKey: string,
  windowKey?: string,
): Promise<Record<string, unknown> | null> {
  try {
    return await apiFetchJson<Record<string, unknown>>(endpoints.aiFusion(entityKey, windowKey));
  } catch {
    return null;
  }
}

export async function fetchEntityTrustSummary(
  entityKey: string,
  predictionType?: string,
): Promise<EntityTrustSummary | null> {
  try {
    return await apiFetchJson<EntityTrustSummary>(endpoints.aiTrustEntity(entityKey, predictionType));
  } catch {
    return null;
  }
}

export async function fetchPlatformTrustSummary(): Promise<PlatformTrustSummary | null> {
  try {
    return await apiFetchJson<PlatformTrustSummary>(endpoints.aiTrustSummary());
  } catch {
    return null;
  }
}

export async function fetchDriftReports(
  limit = 10,
  predictionType?: string,
  status?: string,
): Promise<AIDriftReport[]> {
  try {
    const data = await apiFetchJson<ListResponse<AIDriftReport> | AIDriftReport[]>(
      endpoints.aiDriftReports(limit, 0, predictionType, status),
    );
    return Array.isArray(data) ? data : (data.items ?? []);
  } catch {
    return [];
  }
}

export async function runDriftCheck(
  predictionType: "risk_gnn" | "corruption_risk",
): Promise<Record<string, unknown> | null> {
  try {
    return await apiFetchJson<Record<string, unknown>>(endpoints.aiDriftRun(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prediction_type: predictionType }),
    });
  } catch {
    return null;
  }
}

export async function queryAICopilot(
  question: string,
  context?: Record<string, unknown>,
): Promise<Record<string, unknown> | null> {
  try {
    return await apiFetchJson<Record<string, unknown>>(endpoints.aiQuery(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, context }),
    });
  } catch {
    return null;
  }
}

export async function runCryptoSelfTest(): Promise<SelfTestResult[]> {
  try {
    const raw = await apiFetchJson<unknown>(endpoints.cryptoSelfTest());
    if (Array.isArray(raw)) {
      return raw as SelfTestResult[];
    }
    const obj = asRecord(raw);
    const tests = asRecord(obj.tests);

    return Object.entries(tests).map(([testName, v]) => {
      const details = asRecord(v);
      const elapsed = details.elapsed_ms ?? details.duration_ms;
      const detailBits: string[] = [];
      if (details.standard != null) detailBits.push(String(details.standard));
      if (details.scheme != null) detailBits.push(`scheme=${String(details.scheme)}`);
      if (details.library != null) detailBits.push(`lib=${String(details.library)}`);
      return {
        test: testName,
        passed: asBoolean(details.pass) || asBoolean(details.passed),
        duration_ms: elapsed != null ? asNumber(elapsed) : undefined,
        detail: detailBits.join(" · ") || null,
      };
    });
  } catch {
    return [];
  }
}
