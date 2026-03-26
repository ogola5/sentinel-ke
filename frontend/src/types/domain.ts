export type SourceType = "telco" | "bank" | "gov" | "osint" | "infra";

export type EventRecord = {
  event_hash: string;
  type: string;
  source: SourceType;
  classification: string;
  confidence: number;
  occurred_at: string;
  received_at: string;
  service_id: string;
  endpoint: string;
  ip?: string;
  summary: string;
  evidence: EvidenceItem[];
};

export type EvidenceItem = {
  event_hash: string;
  source: SourceType;
  detail: string;
};

export type TimelinePoint = {
  label: string;
  value: number;
};

export type ServiceIndicator = {
  serviceId: string;
  endpoint: string;
  window: string[];
  reqRate: number[];
  uniqueIps: number[];
  asnConcentration: number[];
  endpointConvergence: number[];
  anomalyScore: number[];
  ddosRisk: number[];
  stage: string;
  factors: string[];
};

export type Campaign = {
  id: string;
  name: string;
  type: string;
  primaryKey?: string;
  discovery?: string;
  eventCount?: number;
  confidence: number;
  status: string;
  severity: string;
  first_seen: string;
  last_seen: string;
  confidence_history: number[];
  top_entities: {
    label: string;
    role: string;
  }[];
  factors: string[];
};

export type InfraCluster = {
  id: string;
  type: string;
  confidence: number;
  provider: string;
  asn: string;
  members: string[];
  reasons: string[];
  rotation: {
    ip: string;
    window: string;
    provider: string;
  }[];
  evidence: EvidenceItem[];
};

export type EntityProfile = {
  id: string;
  label: string;
  type: string;
  risk: string;
  first_seen: string;
  last_seen: string;
  sources: SourceType[];
  notes: string[];
};

export type GraphNode = {
  id: string;
  label: string;
  type: string;
  x: number;
  y: number;
  community: string;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  kind?: string;
  summary?: string;
  evidence: EvidenceItem[];
  first_seen: string;
  last_seen: string;
  count: number;
  sources: SourceType[];
};

export type GraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

// ── ThreatSummary — powers S2 Timeline / Indicators screen ──────────────────
export type ThreatVolumeSeries = {
  date: string;
  fraud: number;
  ddos: number;
  network: number;
  vulnerability: number;
  phishing: number;
  other: number;
  total: number;
};

export type GNNRiskSeries = {
  date: string;
  prediction_count: number;
  avg_score: number;
  max_score: number;
  p90_score: number;
};

export type ThreatEntity = {
  entity_key: string;
  entity_type: string;
  score: number;
  kill_chain_stage: string | null;
  reason_codes: string[];
  severity: string;
};

export type ThreatSummary = {
  generated_at: string;
  window_days: number;
  event_volume_series: ThreatVolumeSeries[];
  gnn_risk_series: GNNRiskSeries[];
  campaign_risk: { critical: number; high: number; medium: number; low: number; total: number };
  top_threats: ThreatEntity[];
  kill_chain_distribution: Record<string, number>;
  event_totals: { fraud: number; ddos: number; network: number; vulnerability: number; phishing: number; total: number };
  forecast: { trend: "rising" | "falling" | "stable"; forecast_score: number | null; confidence: number };
};

export const emptyThreatSummary: ThreatSummary = {
  generated_at: "",
  window_days: 7,
  event_volume_series: [],
  gnn_risk_series: [],
  campaign_risk: { critical: 0, high: 0, medium: 0, low: 0, total: 0 },
  top_threats: [],
  kill_chain_distribution: {},
  event_totals: { fraud: 0, ddos: 0, network: 0, vulnerability: 0, phishing: 0, total: 0 },
  forecast: { trend: "stable", forecast_score: null, confidence: 0 },
};

export type CasePacket = {
  id: string;
  campaignId: string;
  summary: string;
  confidence: number;
  severity: string;
  affected_entities: string[];
  evidence_paths: string[];
  recommended_actions: {
    stakeholder: string;
    actions: string[];
  }[];
  ai_rationale: string[];
};
