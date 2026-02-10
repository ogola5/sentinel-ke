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
