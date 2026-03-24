import { ApiError, apiFetchJson, apiPostJson } from "./client";
import { endpoints } from "./endpoints";
import type {
  BackupAttestationRecord,
  DefenseActionDefinition,
  IncidentActionExecutionResult,
  PlaybookRun,
  RestoreDrillRecord,
  VulnFinding,
  WebhookDeliveryRecord,
  WebhookRecord,
} from "../types/defense";

interface ListResponse<T> {
  total?: number;
  items: T[];
}

interface QueryOptions {
  strict?: boolean;
}

const asString = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;

const asNumber = (value: unknown, fallback = 0): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const asBool = (value: unknown): boolean => value === true;

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

export const DEFAULT_DEFENSE_ACTIONS: DefenseActionDefinition[] = [
  {
    key: "block_ip",
    label: "Block source IP",
    description: "Drop or deny traffic from a confirmed hostile public IP.",
    delivery_mode: "webhook",
    continuity_preserving: false,
    target_hint: "Public source IP",
    category: "network",
  },
  {
    key: "rollback_block_ip",
    label: "Rollback IP block",
    description: "Reverse the latest active IP block within the rollback window.",
    delivery_mode: "internal_dispatch",
    continuity_preserving: true,
    target_hint: "Previously blocked IP",
    category: "network",
  },
  {
    key: "isolate_host",
    label: "Isolate host",
    description: "Contain a compromised workstation or server through EDR/NDR isolation.",
    delivery_mode: "webhook",
    continuity_preserving: false,
    target_hint: "Host, endpoint, or device identifier",
    category: "host",
  },
  {
    key: "rate_limit_service",
    label: "Rate-limit service",
    description: "Throttle abusive traffic while keeping the protected service reachable.",
    delivery_mode: "webhook",
    continuity_preserving: true,
    target_hint: "Service or endpoint identifier",
    category: "service",
  },
  {
    key: "enable_waf_challenge",
    label: "Enable WAF challenge",
    description: "Require challenge or bot mitigation at the edge while keeping service available.",
    delivery_mode: "webhook",
    continuity_preserving: true,
    target_hint: "Service, URL, or domain",
    category: "service",
  },
  {
    key: "reroute_to_scrubber",
    label: "Reroute to scrubber",
    description: "Move traffic into upstream DDoS scrubbing or protective transit.",
    delivery_mode: "webhook",
    continuity_preserving: true,
    target_hint: "Service or edge zone identifier",
    category: "service",
  },
  {
    key: "quarantine_email",
    label: "Quarantine email",
    description: "Quarantine a malicious sender, message, or mailbox path.",
    delivery_mode: "webhook",
    continuity_preserving: true,
    target_hint: "Mailbox, sender, or message target",
    category: "email",
  },
  {
    key: "disable_source_key",
    label: "Disable source key",
    description: "Disable a compromised source registry API key or ingest source.",
    delivery_mode: "internal",
    continuity_preserving: true,
    target_hint: "Source registry ID",
    category: "identity",
  },
  {
    key: "revoke_user",
    label: "Revoke user sessions",
    description: "Invalidate all active sessions for a compromised user account.",
    delivery_mode: "internal",
    continuity_preserving: true,
    target_hint: "Username",
    category: "identity",
  },
  {
    key: "force_password_reset",
    label: "Force password reset",
    description: "Reset a user password and revoke active sessions.",
    delivery_mode: "internal",
    continuity_preserving: true,
    target_hint: "Username",
    category: "identity",
  },
];

const toActionDefinition = (row: Record<string, unknown>): DefenseActionDefinition => ({
  key: asString(row.key),
  label: asString(row.label),
  description: asString(row.description),
  delivery_mode: (asString(row.delivery_mode, "internal") as DefenseActionDefinition["delivery_mode"]),
  continuity_preserving: asBool(row.continuity_preserving),
  target_hint: asString(row.target_hint),
  category: (asString(row.category, "host") as DefenseActionDefinition["category"]),
});

const toPlaybookRun = (row: Record<string, unknown>): PlaybookRun => ({
  id: asString(row.id),
  incident_key: asString(row.incident_key),
  section_code: (row.section_code as string | null) ?? null,
  severity: (asString(row.severity, "medium").toLowerCase() as PlaybookRun["severity"]),
  status: (asString(row.status, "running").toLowerCase() as PlaybookRun["status"]),
  created_by: asString(row.created_by),
  started_at: asString(row.started_at),
  completed_at: (row.completed_at as string | null) ?? null,
  metadata: asRecord(row.metadata),
  created_at: asString(row.created_at, ""),
  updated_at: asString(row.updated_at, ""),
});

const toWebhook = (row: Record<string, unknown>): WebhookRecord => ({
  id: asString(row.id),
  section_code: asString(row.section_code),
  action_type: asString(row.action_type),
  webhook_url: asString(row.webhook_url),
  is_active: asBool(row.is_active),
  created_at: asString(row.created_at),
});

const toDelivery = (row: Record<string, unknown>): WebhookDeliveryRecord => ({
  id: asString(row.id),
  action_id: (row.action_id as string | null) ?? null,
  section_code: (row.section_code as string | null) ?? null,
  action_type: asString(row.action_type),
  target: asString(row.target),
  webhook_url: asString(row.webhook_url),
  status: (asString(row.status, "pending").toLowerCase() as WebhookDeliveryRecord["status"]),
  http_status_code: row.http_status_code != null ? asNumber(row.http_status_code) : null,
  attempt_count: asNumber(row.attempt_count, 0),
  last_attempted_at: (row.last_attempted_at as string | null) ?? null,
  delivered_at: (row.delivered_at as string | null) ?? null,
  error_message: (row.error_message as string | null) ?? null,
  response_body: asRecord(row.response_body),
  created_at: asString(row.created_at),
});

const toBackup = (row: Record<string, unknown>): BackupAttestationRecord => ({
  id: asString(row.id),
  section_code: (row.section_code as string | null) ?? null,
  asset_id: asString(row.asset_id),
  backup_id: asString(row.backup_id),
  immutable: asBool(row.immutable),
  backup_hash: (row.backup_hash as string | null) ?? null,
  storage_tier: (row.storage_tier as string | null) ?? null,
  status: asString(row.status, "unknown"),
  rpo_hours: row.rpo_hours != null ? asNumber(row.rpo_hours) : null,
  attested_at: asString(row.attested_at),
  created_at: asString(row.created_at),
});

const toRestoreDrill = (row: Record<string, unknown>): RestoreDrillRecord => ({
  id: asString(row.id),
  section_code: (row.section_code as string | null) ?? null,
  asset_id: asString(row.asset_id),
  backup_id: asString(row.backup_id),
  success: asBool(row.success),
  rto_target_minutes: asNumber(row.rto_target_minutes, 0),
  rto_actual_minutes: row.rto_actual_minutes != null ? asNumber(row.rto_actual_minutes) : null,
  operator_id: (row.operator_id as string | null) ?? null,
  notes: (row.notes as string | null) ?? null,
  completed_at: (row.completed_at as string | null) ?? null,
  created_at: asString(row.created_at),
});

export async function fetchPlaybookRuns(limit = 20, options: QueryOptions = {}): Promise<PlaybookRun[]> {
  try {
    const data = await apiFetchJson<ListResponse<Record<string, unknown>>>(endpoints.defenseIncidents(limit));
    const rows = Array.isArray(data) ? data : (data.items ?? []);
    return rows.map((r) => toPlaybookRun(asRecord(r))).filter((r) => r.id !== "");
  } catch (err) {
    if (options.strict || !(err instanceof ApiError) || err.status >= 500 || err.status === 401 || err.status === 403) {
      throw err;
    }
    return [];
  }
}

export async function createIncidentRun(
  incidentKey: string,
  severity: "critical" | "high" | "medium" | "low",
  metadata: Record<string, unknown> = {},
): Promise<PlaybookRun> {
  const raw = await apiPostJson(endpoints.defenseIncidentsCreate(), {
    incident_key: incidentKey,
    severity,
    metadata,
  });
  return toPlaybookRun(asRecord(raw));
}

export async function fetchDefenseActionCatalog(options: QueryOptions = {}): Promise<DefenseActionDefinition[]> {
  try {
    const data = await apiFetchJson<ListResponse<Record<string, unknown>>>(endpoints.defenseActionCatalog());
    const rows = Array.isArray(data) ? data : (data.items ?? []);
    const parsed = rows.map((row) => toActionDefinition(asRecord(row))).filter((row) => row.key !== "");
    return parsed.length > 0 ? parsed : DEFAULT_DEFENSE_ACTIONS;
  } catch (err) {
    if (options.strict || !(err instanceof ApiError) || err.status >= 500 || err.status === 401 || err.status === 403) {
      throw err;
    }
    return DEFAULT_DEFENSE_ACTIONS;
  }
}

export async function executeContainmentAction(
  runId: string,
  actionType: string,
  target: string,
  details: Record<string, unknown> = {},
): Promise<IncidentActionExecutionResult> {
  return apiPostJson(`/v1/defense/incidents/runs/${encodeURIComponent(runId)}/actions`, {
    actions: [
      {
        action_type: actionType,
        target,
        details,
      },
    ],
  });
}

export async function fetchWebhooks(options: { sectionCode?: string; strict?: boolean } = {}): Promise<WebhookRecord[]> {
  try {
    const data = await apiFetchJson<ListResponse<Record<string, unknown>>>(endpoints.defenseWebhooks(options.sectionCode));
    const rows = Array.isArray(data) ? data : (data.items ?? []);
    return rows.map((r) => toWebhook(asRecord(r))).filter((r) => r.id !== "");
  } catch (err) {
    if (options.strict || !(err instanceof ApiError) || err.status >= 500 || err.status === 401 || err.status === 403) {
      throw err;
    }
    return [];
  }
}

export async function fetchWebhookDeliveries(
  limit = 50,
  options: { sectionCode?: string; status?: string; strict?: boolean } = {},
): Promise<WebhookDeliveryRecord[]> {
  try {
    const data = await apiFetchJson<ListResponse<Record<string, unknown>>>(
      endpoints.defenseWebhookDeliveries(limit, 0, options.sectionCode, options.status),
    );
    const rows = Array.isArray(data) ? data : (data.items ?? []);
    return rows.map((r) => toDelivery(asRecord(r))).filter((r) => r.id !== "");
  } catch (err) {
    if (options.strict || !(err instanceof ApiError) || err.status >= 500 || err.status === 401 || err.status === 403) {
      throw err;
    }
    return [];
  }
}

export async function fetchBackupAttestations(limit = 20, sectionCode?: string): Promise<BackupAttestationRecord[]> {
  try {
    const data = await apiFetchJson<ListResponse<Record<string, unknown>>>(
      endpoints.defenseBackupAttestList(limit, 0, sectionCode),
    );
    const rows = Array.isArray(data) ? data : (data.items ?? []);
    return rows.map((r) => toBackup(asRecord(r))).filter((r) => r.id !== "");
  } catch (_err) {
    return [];
  }
}

export async function upsertBackupAttestation(payload: {
  asset_id: string;
  backup_id: string;
  immutable: boolean;
  backup_hash?: string;
  storage_tier?: string;
  status: string;
  rpo_hours?: number;
  evidence?: Record<string, unknown>;
}): Promise<BackupAttestationRecord> {
  const raw = await apiPostJson(endpoints.defenseBackupAttestCreate(), payload);
  return toBackup(asRecord(raw));
}

export async function fetchRestoreDrills(limit = 20, sectionCode?: string): Promise<RestoreDrillRecord[]> {
  try {
    const data = await apiFetchJson<ListResponse<Record<string, unknown>>>(
      endpoints.defenseRestoreDrillsList(limit, 0, sectionCode),
    );
    const rows = Array.isArray(data) ? data : (data.items ?? []);
    return rows.map((r) => toRestoreDrill(asRecord(r))).filter((r) => r.id !== "");
  } catch (_err) {
    return [];
  }
}

export async function createRestoreDrill(payload: {
  asset_id: string;
  backup_id: string;
  success: boolean;
  rto_target_minutes: number;
  rto_actual_minutes?: number;
  notes?: string;
  evidence?: Record<string, unknown>;
}): Promise<RestoreDrillRecord> {
  const raw = await apiPostJson(endpoints.defenseRestoreDrillsCreate(), payload);
  return toRestoreDrill(asRecord(raw));
}

export async function fetchVulnerabilities(limit = 20, status?: string): Promise<VulnFinding[]> {
  try {
    const data = await apiFetchJson<ListResponse<VulnFinding>>(endpoints.defenseVulnerabilities(limit, status));
    const rows = Array.isArray(data) ? data : (data.items ?? []);
    return rows;
  } catch (_err) {
    return [];
  }
}
