import { endpoints } from "./endpoints";

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
const SESSION_KEY = "sentinel_auth_session";
const REFRESH_TOKEN_KEY = "sentinel_refresh_token";
const PRINCIPAL_KEY = "sentinel_principal";
const AUTH_EXPIRED_EVENT = "sentinel:auth-expired";

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

type RefreshSessionResponse = {
  access_token?: unknown;
  refresh_token?: unknown;
  access_expires_at?: unknown;
  refresh_expires_at?: unknown;
  principal?: unknown;
};

let refreshInFlight: Promise<boolean> | null = null;

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

const extractApiDetail = (payload: Record<string, unknown> | null, errorObj: Record<string, unknown> | null): string => {
  if (errorObj && typeof errorObj.message === "string" && errorObj.message.trim()) {
    return errorObj.message.trim();
  }

  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === "string" && first.trim()) {
      return first.trim();
    }
    if (typeof first === "object" && first !== null) {
      const msg = (first as Record<string, unknown>).msg;
      if (typeof msg === "string" && msg.trim()) {
        return msg.trim();
      }
    }
  }

  return "request_failed";
};

const getStoredRefreshToken = (): string => {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(REFRESH_TOKEN_KEY)?.trim() ?? "";
};

const clearAuthStorage = (): void => {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SESSION_KEY);
  window.localStorage.removeItem(STORAGE_KEYS.accessToken);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  window.localStorage.removeItem(PRINCIPAL_KEY);
};

const notifyAuthExpired = (): void => {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
};

const persistRefreshedSession = (payload: unknown): boolean => {
  if (typeof window === "undefined" || typeof payload !== "object" || payload === null) return false;
  const session = payload as RefreshSessionResponse;
  if (
    typeof session.access_token !== "string" ||
    typeof session.refresh_token !== "string" ||
    typeof session.access_expires_at !== "string" ||
    typeof session.refresh_expires_at !== "string" ||
    session.principal == null
  ) {
    return false;
  }

  const normalized = {
    access_token: session.access_token,
    refresh_token: session.refresh_token,
    access_expires_at: session.access_expires_at,
    refresh_expires_at: session.refresh_expires_at,
    principal: session.principal,
  };

  window.localStorage.setItem(SESSION_KEY, JSON.stringify(normalized));
  window.localStorage.setItem(STORAGE_KEYS.accessToken, normalized.access_token);
  window.localStorage.setItem(REFRESH_TOKEN_KEY, normalized.refresh_token);
  window.localStorage.setItem(PRINCIPAL_KEY, JSON.stringify(normalized.principal));
  return true;
};

const isAuthLifecycleRequest = (url: string): boolean =>
  url.includes("/v1/auth/login") || url.includes("/v1/auth/refresh") || url.includes("/v1/auth/logout");

const refreshAccessToken = async (): Promise<boolean> => {
  if (refreshInFlight) {
    return refreshInFlight;
  }

  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) {
    clearAuthStorage();
    notifyAuthExpired();
    return false;
  }

  refreshInFlight = (async () => {
    try {
      const response = await fetch(endpoints.authRefresh(), {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      const text = await response.text();
      const data = parseResponseBody(text);
      if (!response.ok || !persistRefreshedSession(data)) {
        clearAuthStorage();
        notifyAuthExpired();
        return false;
      }
      return true;
    } catch {
      clearAuthStorage();
      notifyAuthExpired();
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
};

export type ApiFetchOptions = {
  requireLegalGrantToken?: boolean;
  skipAuthRefresh?: boolean;
  useApiKeyAuth?: boolean;
};

export async function apiFetchJson<T>(
  url: string,
  init: RequestInit = {},
  options: ApiFetchOptions = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();

  const buildHeaders = (): Headers => {
    const headers = new Headers(init.headers ?? {});
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    if (method !== "GET" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    const accessToken = getConfiguredAccessToken();
    if (accessToken && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${accessToken}`);
    }

    const key = getConfiguredApiKey();
    const shouldAttachApiKey =
      Boolean(key) &&
      !headers.has("X-API-Key") &&
      (options.useApiKeyAuth || (!accessToken && !headers.has("Authorization")));
    if (shouldAttachApiKey && key) {
      headers.set("X-API-Key", key);
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

    return headers;
  };

  const send = async (): Promise<{ response: Response; data: unknown }> => {
    const response = await fetch(url, { ...init, headers: buildHeaders() });
    const text = await response.text();
    return { response, data: parseResponseBody(text) };
  };

  let { response, data } = await send();

  if (
    response.status === 401 &&
    !options.skipAuthRefresh &&
    !isAuthLifecycleRequest(url) &&
    (getStoredRefreshToken() || getConfiguredAccessToken())
  ) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      ({ response, data } = await send());
    }
  }

  if (!response.ok) {
    const payload = typeof data === "object" && data !== null ? (data as Record<string, unknown>) : null;
    const errorObj =
      payload && typeof payload.error === "object" && payload.error !== null
        ? (payload.error as Record<string, unknown>)
        : null;

    const detail = extractApiDetail(payload, errorObj) || response.statusText || "request_failed";
    const code = errorObj && "code" in errorObj ? String(errorObj.code) : undefined;
    const requestId =
      (errorObj && "request_id" in errorObj && String(errorObj.request_id)) ||
      response.headers.get("X-Request-ID") ||
      undefined;
    if (response.status === 401) {
      clearAuthStorage();
      notifyAuthExpired();
    }
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

export async function apiFetchBlob(
  url: string,
  init: RequestInit = {},
  options: ApiFetchOptions = {},
): Promise<{ response: Response; blob: Blob }> {
  const method = (init.method ?? "GET").toUpperCase();

  const buildHeaders = (): Headers => {
    const headers = new Headers(init.headers ?? {});
    if (!headers.has("Accept")) headers.set("Accept", "*/*");
    if (method !== "GET" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    const accessToken = getConfiguredAccessToken();
    if (accessToken && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${accessToken}`);
    }

    const key = getConfiguredApiKey();
    const shouldAttachApiKey =
      Boolean(key) &&
      !headers.has("X-API-Key") &&
      (options.useApiKeyAuth || (!accessToken && !headers.has("Authorization")));
    if (shouldAttachApiKey && key) {
      headers.set("X-API-Key", key);
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

    return headers;
  };

  const send = async (): Promise<{ response: Response; errorData?: unknown; blob?: Blob }> => {
    const response = await fetch(url, { ...init, headers: buildHeaders() });
    if (!response.ok) {
      const text = await response.text();
      return { response, errorData: parseResponseBody(text) };
    }
    return { response, blob: await response.blob() };
  };

  let result = await send();
  let response = result.response;

  if (
    response.status === 401 &&
    !options.skipAuthRefresh &&
    !isAuthLifecycleRequest(url) &&
    (getStoredRefreshToken() || getConfiguredAccessToken())
  ) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      result = await send();
      response = result.response;
    }
  }

  if (!response.ok) {
    const payload = typeof result.errorData === "object" && result.errorData !== null
      ? (result.errorData as Record<string, unknown>)
      : null;
    const errorObj =
      payload && typeof payload.error === "object" && payload.error !== null
        ? (payload.error as Record<string, unknown>)
        : null;

    const detail = extractApiDetail(payload, errorObj) || response.statusText || "request_failed";
    const code = errorObj && "code" in errorObj ? String(errorObj.code) : undefined;
    const requestId =
      (errorObj && "request_id" in errorObj && String(errorObj.request_id)) ||
      response.headers.get("X-Request-ID") ||
      undefined;
    if (response.status === 401) {
      clearAuthStorage();
      notifyAuthExpired();
    }
    throw new ApiError(response.status, detail, code, requestId);
  }

  return { response, blob: result.blob as Blob };
}
