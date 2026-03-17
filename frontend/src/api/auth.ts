import { apiFetchJson } from "./client";
import { endpoints } from "./endpoints";
import type { AuthSession, AuthUser, Principal } from "../types/auth";

const SESSION_KEY = "sentinel_auth_session";
const PRINCIPAL_KEY = "sentinel_principal";
export const LOGIN_NOTICE_KEY = "sentinel_login_notice";

// ── Persist / load ─────────────────────────────────────────────────────────

export function saveSession(session: AuthSession): void {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  localStorage.setItem("sentinel_access_token", session.access_token);
  localStorage.setItem("sentinel_refresh_token", session.refresh_token);
  localStorage.setItem(PRINCIPAL_KEY, JSON.stringify(session.principal));
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
  localStorage.removeItem("sentinel_access_token");
  localStorage.removeItem("sentinel_refresh_token");
  localStorage.removeItem(PRINCIPAL_KEY);
}

export function loadPrincipal(): Principal | null {
  try {
    const raw = localStorage.getItem(PRINCIPAL_KEY);
    return raw ? (JSON.parse(raw) as Principal) : null;
  } catch {
    return null;
  }
}

export function loadSession(): AuthSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as AuthSession;
    // Check access token expiry
    if (new Date(session.access_expires_at) < new Date()) return null;
    return session;
  } catch {
    return null;
  }
}

export function getRefreshToken(): string | null {
  return localStorage.getItem("sentinel_refresh_token");
}

// ── API calls ─────────────────────────────────────────────────────────────

export async function apiLogin(
  username: string,
  password: string,
  otpCode?: string,
): Promise<AuthSession> {
  const body: Record<string, string> = { username, password };
  if (otpCode) body.otp_code = otpCode;
  return apiFetchJson<AuthSession>(endpoints.authLogin(), {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
}

export async function apiRefresh(refreshToken: string): Promise<AuthSession> {
  return apiFetchJson<AuthSession>(endpoints.authRefresh(), {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
    headers: { "Content-Type": "application/json" },
  });
}

export async function apiLogout(refreshToken: string): Promise<void> {
  await apiFetchJson<unknown>(endpoints.authLogout(), {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
    headers: { "Content-Type": "application/json" },
  });
}

export async function apiGetMe(): Promise<Principal> {
  return apiFetchJson<Principal>(endpoints.authMe());
}

export async function apiListUsers(params?: {
  access_level?: string;
  section_code?: string;
}): Promise<{ total: number; items: AuthUser[] }> {
  const q: Record<string, string | number> = { limit: 100 };
  if (params?.access_level) q.access_level = params.access_level;
  if (params?.section_code) q.section_code = params.section_code;
  return apiFetchJson<{ total: number; items: AuthUser[] }>(endpoints.authUsers(q));
}

export async function apiCreateUser(payload: {
  username: string;
  display_name?: string;
  password: string;
  role: string;
  access_level: "section" | "central";
  section_code?: string;
}): Promise<AuthUser> {
  return apiFetchJson<AuthUser>(endpoints.authUsersCreate(), {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
  });
}

export async function apiAdminResetPassword(
  username: string,
  newPassword: string,
): Promise<void> {
  await apiFetchJson<unknown>(endpoints.authUserPasswordReset(username), {
    method: "POST",
    body: JSON.stringify({ new_password: newPassword, revoke_existing_sessions: true }),
    headers: { "Content-Type": "application/json" },
  });
}

export async function apiStartMfaEnrollment(): Promise<{
  status: string;
  username: string;
  secret: string;
  issuer: string;
  provisioning_uri: string;
}> {
  return apiFetchJson(endpoints.authMfaEnrollStart(), {
    method: "POST",
  });
}

export async function apiVerifyMfaEnrollment(
  otpCode: string,
): Promise<{ status: string; mfa_enabled: boolean; revoked_sessions: number }> {
  return apiFetchJson(endpoints.authMfaEnrollVerify(), {
    method: "POST",
    body: JSON.stringify({ otp_code: otpCode }),
    headers: { "Content-Type": "application/json" },
  });
}

export async function apiDisableMfa(
  otpCode: string,
  currentPassword: string,
): Promise<{ status: string; mfa_enabled: boolean; revoked_sessions: number }> {
  return apiFetchJson(endpoints.authMfaDisable(), {
    method: "POST",
    body: JSON.stringify({ otp_code: otpCode, current_password: currentPassword }),
    headers: { "Content-Type": "application/json" },
  });
}
