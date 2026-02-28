export type AccessLevel = "section" | "central";

export type UserRole = "admin" | "analyst" | "operator" | "auditor";

export interface Principal {
  user_id: string;
  username: string;
  display_name: string | null;
  role: string;
  access_level: AccessLevel;
  section_code: string | null;
  scopes: string[];
  principal_type: "user" | "api_key";
}

export interface AuthSession {
  access_token: string;
  refresh_token: string;
  access_expires_at: string;
  refresh_expires_at: string;
  principal: Principal;
}

export interface AuthUser {
  user_id: string;
  username: string;
  display_name: string | null;
  role: string;
  access_level: AccessLevel;
  section_code: string | null;
  scopes: string[];
  is_active: boolean;
  mfa_enabled: boolean;
  failed_login_count: number;
  locked_until: string | null;
  created_at: string;
  updated_at: string;
}

// Kenya agency registry
export const KENYA_AGENCIES: Record<string, { name: string; color: string }> = {
  KPS:  { name: "Kenya Police Service",                color: "var(--info)" },
  DCI:  { name: "Directorate of Criminal Investigations", color: "var(--warning)" },
  EACC: { name: "Ethics & Anti-Corruption Commission",  color: "var(--risk-critical)" },
  KRA:  { name: "Kenya Revenue Authority",              color: "var(--accent)" },
  ODPP: { name: "Office of Director of Public Prosecutions", color: "var(--risk-high)" },
  CBK:  { name: "Central Bank of Kenya",                color: "var(--warning)" },
  NIS:  { name: "National Intelligence Service",        color: "var(--risk-critical)" },
  KAA:  { name: "Kenya Airports Authority",             color: "var(--info)" },
  OAG:  { name: "Office of the Auditor General",        color: "var(--accent)" },
  NTSA: { name: "National Transport & Safety Authority", color: "var(--info)" },
};

export function agencyName(code: string | null): string {
  if (!code) return "Central Command";
  return KENYA_AGENCIES[code]?.name ?? code;
}

export function agencyColor(code: string | null): string {
  if (!code) return "var(--accent)";
  return KENYA_AGENCIES[code]?.color ?? "var(--ink-muted)";
}

// Can the user execute containment actions?
export function canExecute(principal: Principal): boolean {
  return principal.role === "operator" || principal.role === "admin";
}

// Can the user manage users?
export function canManageUsers(principal: Principal): boolean {
  return principal.access_level === "central";
}

// Is this a central command user?
export function isCentral(principal: Principal): boolean {
  return principal.access_level === "central";
}

// Auditor-only role (limited nav)
export function isAuditorOnly(principal: Principal): boolean {
  return principal.role === "auditor";
}
