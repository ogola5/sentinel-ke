import { apiFetchJson } from "./client";
import { endpoints } from "./endpoints";
import type { FederationCorrelation, FederationPartner, FederationPattern } from "../types/federation";

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

export async function fetchFederationPartners(): Promise<FederationPartner[]> {
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
      };
    });
  } catch (_err) {
    return [];
  }
}

export async function fetchFederationPatterns(limit = 50): Promise<FederationPattern[]> {
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
  } catch (_err) {
    return [];
  }
}

export async function fetchFederationCorrelations(limit = 20): Promise<FederationCorrelation[]> {
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
  } catch (_err) {
    return [];
  }
}
