export interface FederationPartner {
  partner_id: string;
  partner_name: string;
  sector: string;
  status: "online" | "stale" | "offline" | "never_connected";
  is_active: boolean;
  last_seen_at: string | null;
  last_seen_sec_ago?: number | null;
  pattern_count?: number;
  correlation_hits?: number;
  total_patterns?: number;
  registered_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface FederationPattern {
  id: string;
  partner_id: string;
  entity_key_hash: string;
  pattern_type: string;
  confidence: number;
  event_count?: number;
  source_count?: number;
  risk_flags: string[];
  window_start: string;
  window_end: string;
  fraud_family?: string | null;
  chain_score?: number | null;
  created_at: string;
}

export interface FederationCorrelation {
  entity_key_hash: string;
  entity_type?: string;
  partner_count: number;
  partner_ids: string[];
  max_confidence: number;
  avg_confidence?: number;
  risk_level: string;
  fraud_families?: string[];
  all_risk_flags?: string[];
  max_chain_score?: number;
  total_signals?: number;
  first_seen: string;
  last_seen: string;
}
