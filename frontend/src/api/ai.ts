import { apiFetchJson } from "./client";
import { endpoints } from "./endpoints";
import type { AIFeedback, AIPrediction, CryptoPosture, GNNTrainingRun, SelfTestResult } from "../types/ai";

interface ListResponse<T> {
  total?: number;
  items: T[];
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

export async function fetchGNNTrainingRuns(limit = 10): Promise<GNNTrainingRun[]> {
  try {
    const data = await apiFetchJson<ListResponse<GNNTrainingRun> | GNNTrainingRun[]>(
      endpoints.aiTrainingRuns(limit),
    );
    return Array.isArray(data) ? data : (data.items ?? []);
  } catch {
    return [];
  }
}

export async function fetchAIPredictions(limit = 20, windowKey?: string): Promise<AIPrediction[]> {
  try {
    const data = await apiFetchJson<ListResponse<AIPrediction> | AIPrediction[]>(
      endpoints.aiPredictions(limit, 0, windowKey),
    );
    return Array.isArray(data) ? data : (data.items ?? []);
  } catch {
    return [];
  }
}

export async function submitAIFeedback(
  predictionId: string,
  feedbackLabel: number,
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
      endpoints.aiFeedback(limit, 0, analystId),
    );
    return Array.isArray(data) ? data : (data.items ?? []);
  } catch {
    return [];
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
