export class ApiError extends Error {
  status: number;
  detail: string;
  code?: string;
  requestId?: string;

  constructor(status: number, detail: string, code?: string, requestId?: string) {
    super(`API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.requestId = requestId;
  }
}

type ClientCredentialKey = "apiKey" | "accessToken" | "legalGrantToken" | "legalTarget";

const STORAGE_KEYS: Record<ClientCredentialKey, string> = {
  apiKey: "sentinel_api_key",
  accessToken: "sentinel_access_token",
  legalGrantToken: "sentinel_legal_grant_token",
  legalTarget: "sentinel_legal_target",
};

export type ClientCredentials = {
  apiKey: string;
  accessToken: string;
  legalGrantToken: string;
  legalTarget: string;
};

const readFromStorage = (key: ClientCredentialKey): string => {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(STORAGE_KEYS[key])?.trim() ?? "";
};

const writeToStorage = (key: ClientCredentialKey, value: string): void => {
  if (typeof window === "undefined") return;
  const cleaned = value.trim();
  if (cleaned === "") {
    window.localStorage.removeItem(STORAGE_KEYS[key]);
    return;
  }
  window.localStorage.setItem(STORAGE_KEYS[key], cleaned);
};

export const loadClientCredentials = (): ClientCredentials => ({
  apiKey: readFromStorage("apiKey"),
  accessToken: readFromStorage("accessToken"),
  legalGrantToken: readFromStorage("legalGrantToken"),
  legalTarget: readFromStorage("legalTarget"),
});

export const saveClientCredentials = (next: Partial<ClientCredentials>): ClientCredentials => {
  const current = loadClientCredentials();
  const merged: ClientCredentials = {
    apiKey: (next.apiKey ?? current.apiKey).trim(),
    accessToken: (next.accessToken ?? current.accessToken).trim(),
    legalGrantToken: (next.legalGrantToken ?? current.legalGrantToken).trim(),
    legalTarget: (next.legalTarget ?? current.legalTarget).trim(),
  };
  writeToStorage("apiKey", merged.apiKey);
  writeToStorage("accessToken", merged.accessToken);
  writeToStorage("legalGrantToken", merged.legalGrantToken);
  writeToStorage("legalTarget", merged.legalTarget);
  return merged;
};

const getConfiguredApiKey = (): string | null => {
  const fromEnv = import.meta.env.VITE_API_KEY;
  if (fromEnv && String(fromEnv).trim() !== "") {
    return String(fromEnv).trim();
  }
  const fromStorage = readFromStorage("apiKey");
  if (fromStorage && fromStorage.trim() !== "") {
    return fromStorage.trim();
  }
  return null;
};

const getConfiguredAccessToken = (): string | null => {
  const fromEnv = import.meta.env.VITE_ACCESS_TOKEN;
  if (fromEnv && String(fromEnv).trim() !== "") {
    return String(fromEnv).trim();
  }
  const fromStorage = readFromStorage("accessToken");
  if (fromStorage && fromStorage.trim() !== "") {
    return fromStorage.trim();
  }
  return null;
};

const getConfiguredLegalGrantToken = (): string | null => {
  const fromEnv = import.meta.env.VITE_LEGAL_GRANT_TOKEN;
  if (fromEnv && String(fromEnv).trim() !== "") {
    return String(fromEnv).trim();
  }
  const fromStorage = readFromStorage("legalGrantToken");
  if (fromStorage && fromStorage.trim() !== "") {
    return fromStorage.trim();
  }
  return null;
};

const getConfiguredLegalTarget = (): string | null => {
  const fromEnv = import.meta.env.VITE_LEGAL_TARGET;
  if (fromEnv && String(fromEnv).trim() !== "") {
    return String(fromEnv).trim();
  }
  const fromStorage = readFromStorage("legalTarget");
  if (fromStorage && fromStorage.trim() !== "") {
    return fromStorage.trim();
  }
  return null;
};

const parseResponseBody = (text: string): unknown => {
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
};

export type ApiFetchOptions = {
  requireLegalGrantToken?: boolean;
};

export async function apiFetchJson<T>(
  url: string,
  init: RequestInit = {},
  options: ApiFetchOptions = {},
): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  if (!headers.has("Accept")) headers.set("Accept", "application/json");

  const method = (init.method ?? "GET").toUpperCase();
  if (method !== "GET" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const key = getConfiguredApiKey();
  if (key && !headers.has("X-API-Key")) {
    headers.set("X-API-Key", key);
  }

  const accessToken = getConfiguredAccessToken();
  if (accessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  const legalToken = getConfiguredLegalGrantToken();
  const legalTarget = getConfiguredLegalTarget();
  if (options.requireLegalGrantToken) {
    if (!legalToken) {
      throw new ApiError(400, "missing_client_legal_grant_token");
    }
    if (!headers.has("X-Legal-Grant-Token")) {
      headers.set("X-Legal-Grant-Token", legalToken);
    }
    if (legalTarget && !headers.has("X-Legal-Target")) {
      headers.set("X-Legal-Target", legalTarget);
    }
  }

  const response = await fetch(url, { ...init, headers });
  const text = await response.text();
  const data = parseResponseBody(text);

  if (!response.ok) {
    const payload = typeof data === "object" && data !== null ? (data as Record<string, unknown>) : null;
    const errorObj =
      payload && typeof payload.error === "object" && payload.error !== null
        ? (payload.error as Record<string, unknown>)
        : null;

    const detail =
      (payload && "detail" in payload && String(payload.detail)) ||
      (errorObj && "message" in errorObj && String(errorObj.message)) ||
      response.statusText ||
      "request_failed";
    const code = errorObj && "code" in errorObj ? String(errorObj.code) : undefined;
    const requestId =
      (errorObj && "request_id" in errorObj && String(errorObj.request_id)) ||
      response.headers.get("X-Request-ID") ||
      undefined;
    throw new ApiError(response.status, detail, code, requestId);
  }

  return data as T;
}

export async function apiPostJson<T, B extends object>(url: string, body: B): Promise<T> {
  return apiFetchJson<T>(url, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
