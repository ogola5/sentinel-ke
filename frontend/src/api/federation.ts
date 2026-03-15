import { ApiError, apiFetchJson } from "./client";
import { endpoints } from "./endpoints";
import type {
  FederationCorrelation,
  FederationEdgeSyncStatus,
  FederationPartner,
  FederationPattern,
} from "../types/federation";

export interface PartnerRegistrationPayload {
  partner_id: string;
  partner_name: string;
  partner_type: string;
  webhook_url?: string;
  metadata?: Record<string, unknown>;
}

export interface PartnerRegistrationResult {
  partner_id: string;
  partner_name: string;
  partner_type: string;
  api_key: string;
  correlation_salt: string;
  warning: string;
  edge_agent_env: Record<string, string>;
}

interface QueryOptions {
  strict?: boolean;
}

export async function registerFederationPartner(
  payload: PartnerRegistrationPayload,
): Promise<PartnerRegistrationResult> {
  return apiFetchJson<PartnerRegistrationResult>(endpoints.federationRegister(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchEdgeSyncStatus(): Promise<FederationEdgeSyncStatus> {
  try {
    const data = await apiFetchJson<Record<string, unknown>>(endpoints.federationEdgeStatus());
    const r = asRecord(data);
    return {
      is_edge_node: asBoolean(r.is_edge_node),
      partner_id: asString(r.partner_id),
      hub_url: asString(r.hub_url),
      status: asString(r.status),
      last_synced_at: (r.last_synced_at as string | null) ?? null,
      age_seconds: r.age_seconds != null ? asNumber(r.age_seconds) : null,
      total_pushed: asNumber(r.total_pushed, 0),
      last_error: (r.last_error as string | null) ?? null,
      message: asString(r.message),
    };
  } catch (_err) {
    return { is_edge_node: false, status: "unreachable" };
  }
}

interface ListResponse<T> {
  total?: number;
  items: T[];
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

const asString = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;

const asNumber = (value: unknown, fallback = 0): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const asBoolean = (value: unknown): boolean => value === true;

const asStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.map((v) => String(v)) : [];

const toIsoFromAgo = (secondsAgo: number | null | undefined): string | null => {
  if (secondsAgo == null || !Number.isFinite(secondsAgo)) return null;
  return new Date(Date.now() - secondsAgo * 1000).toISOString();
};

export async function fetchFederationPartners(options: QueryOptions = {}): Promise<FederationPartner[]> {
  try {
    const data = await apiFetchJson<ListResponse<Record<string, unknown>> | Array<Record<string, unknown>>>(
      endpoints.federationPartners(),
    );
    const rows = Array.isArray(data) ? data : (data.items ?? []);
    return rows.map((row) => {
      const r = asRecord(row);
      const secAgo = r.last_seen_sec_ago != null ? asNumber(r.last_seen_sec_ago) : null;
      return {
        partner_id: asString(r.partner_id),
        partner_name: asString(r.partner_name, asString(r.partner_id)),
        sector: asString(r.partner_type, "other"),
        status: (asString(r.status, "offline") as FederationPartner["status"]),
        is_active: asBoolean(r.is_active),
        last_seen_at: (r.last_pattern_at as string | null) ?? toIsoFromAgo(secAgo),
        last_seen_sec_ago: secAgo,
        total_patterns: asNumber(r.total_patterns, 0),
        registered_at: (r.registered_at as string | null) ?? null,
        metadata: asRecord(r.metadata),
        last_heartbeat_at: (r.last_heartbeat_at as string | null) ?? null,
        agent_version: (r.agent_version as string | null) ?? null,
        model_version: (r.model_version as string | null) ?? null,
        data_source: (r.data_source as string | null) ?? null,
        hub_reachable: r.hub_reachable == null ? null : asBoolean(r.hub_reachable),
        capabilities: asStringArray(r.capabilities),
        last_run_status: (r.last_run_status as string | null) ?? null,
        last_publish_status: (r.last_publish_status as string | null) ?? null,
        run_count: r.run_count != null ? asNumber(r.run_count) : null,
      };
    });
  } catch (err) {
    if (options.strict || !(err instanceof ApiError) || err.status >= 500 || err.status === 401 || err.status === 403) {
      throw err;
    }
    return [];
  }
}

export async function fetchFederationPatterns(limit = 50, options: QueryOptions = {}): Promise<FederationPattern[]> {
  try {
    const data = await apiFetchJson<ListResponse<Record<string, unknown>> | Array<Record<string, unknown>>>(
      endpoints.federationPatterns(limit),
    );
    const rows = Array.isArray(data) ? data : (data.items ?? []);
    return rows.map((row) => {
      const r = asRecord(row);
      return {
        id: asString(r.id),
        partner_id: asString(r.partner_id),
        entity_key_hash: asString(r.entity_key_hash),
        pattern_type: asString(r.entity_type, "entity"),
        confidence: asNumber(r.risk_score, 0),
        risk_flags: asStringArray(r.risk_flags),
        window_start: asString(r.window_start, ""),
        window_end: asString(r.window_end, ""),
        fraud_family: (r.fraud_family as string | null) ?? null,
        chain_score: r.chain_score != null ? asNumber(r.chain_score) : null,
        created_at: asString(r.received_at, asString(r.window_end, "")),
      };
    });
  } catch (err) {
    if (options.strict || !(err instanceof ApiError) || err.status >= 500 || err.status === 401 || err.status === 403) {
      throw err;
    }
    return [];
  }
}

export async function fetchFederationCorrelations(limit = 20, options: QueryOptions = {}): Promise<FederationCorrelation[]> {
  try {
    const data = await apiFetchJson<
      | ListResponse<Record<string, unknown>>
      | Array<Record<string, unknown>>
      | { correlations?: Array<Record<string, unknown>> }
    >(
      endpoints.federationCorrelations(limit),
    );
    let rows: Array<Record<string, unknown>> = [];
    if (Array.isArray(data)) {
      rows = data;
    } else {
      const obj = asRecord(data);
      if (Array.isArray(obj.correlations)) {
        rows = obj.correlations as Array<Record<string, unknown>>;
      } else if (Array.isArray(obj.items)) {
        rows = obj.items as Array<Record<string, unknown>>;
      }
    }

    return rows.map((row) => {
      const r = asRecord(row);
      return {
        entity_key_hash: asString(r.entity_key_hash),
        entity_type: asString(r.entity_type, "entity"),
        partner_count: asNumber(r.partner_count, 0),
        partner_ids: asStringArray(r.seen_in_partners),
        max_confidence: asNumber(r.max_risk, 0),
        avg_confidence: asNumber(r.avg_risk, 0),
        risk_level: asString(r.threat_level, "medium"),
        fraud_families: asStringArray(r.fraud_families),
        all_risk_flags: asStringArray(r.all_risk_flags),
        max_chain_score: asNumber(r.max_chain_score, 0),
        total_signals: asNumber(r.total_signals, 0),
        first_seen: asString(r.last_seen, ""),
        last_seen: asString(r.last_seen, ""),
      };
    });
  } catch (err) {
    if (options.strict || !(err instanceof ApiError) || err.status >= 500 || err.status === 401 || err.status === 403) {
      throw err;
    }
    return [];
  }
}
