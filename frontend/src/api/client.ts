export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

const getConfiguredApiKey = (): string | null => {
  const fromEnv = import.meta.env.VITE_API_KEY;
  if (fromEnv && String(fromEnv).trim() !== "") {
    return String(fromEnv).trim();
  }
  const fromStorage = window.localStorage.getItem("sentinel_api_key");
  if (fromStorage && fromStorage.trim() !== "") {
    return fromStorage.trim();
  }
  return null;
};

export async function apiFetchJson<T>(url: string, init: RequestInit = {}): Promise<T> {
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

  const response = await fetch(url, { ...init, headers });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail =
      (data && typeof data === "object" && "detail" in data && String((data as { detail: unknown }).detail)) ||
      response.statusText ||
      "request_failed";
    throw new ApiError(response.status, detail);
  }

  return data as T;
}

export async function apiPostJson<T, B extends object>(url: string, body: B): Promise<T> {
  return apiFetchJson<T>(url, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
