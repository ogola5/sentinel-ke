import type {
  Campaign,
  CasePacket,
  EvidenceItem,
  EntityProfile,
  EventRecord,
  GraphData,
  InfraCluster,
  ServiceIndicator,
  SourceType,
  TimelinePoint,
  ThreatSummary,
} from "../types/domain";
import { emptyThreatSummary } from "../types/domain";
import { apiFetchJson } from "./client";
import { endpoints } from "./endpoints";
import {
  canonicalEndpointKey,
  canonicalServiceKey,
  displayEntityLabel,
  isCanonicalEntityKey,
} from "../utils/entityKeys";

type ReadyResponse = {
  status: "ok" | "degraded";
  components?: Record<string, string>;
};

type EventsSearchResponse = {
  items?: Array<Record<string, unknown>>;
};

type EventsTimelineResponse =
  | { points?: Array<{ t?: string; count?: number }> }
  | Array<{ timestamp?: string; count?: number }>;

type CampaignsResponse = {
  items?: Array<Record<string, unknown>>;
};

type DdosAlertsResponse = {
  items?: Array<Record<string, unknown>>;
};

type InfraClustersResponse = {
  items?: Array<Record<string, unknown>>;
};

type CasePacketApiResponse = {
  case_id?: string;
  generated_at?: string;
  campaign?: {
    id?: string;
    type?: string;
    primary_key?: string;
    status?: string;
    score?: number;
  };
  summary?: {
    stage?: string | null;
    event_count?: number;
    distinct_entities?: number;
  };
  entities?: Array<{
    entity_key?: string;
    type?: string;
    role?: string;
  }>;
  evidence?: Array<{
    event_hash?: string;
    occurred_at?: string;
  }>;
  graph?: {
    nodes?: unknown[];
    edges?: unknown[];
  };
  integrity?: {
    hash?: string;
  };
};

export type BackendSnapshot = {
  mode: "live" | "degraded";
  connectionLabel: string;
  warnings: string[];
  events: EventRecord[];
  timelineCounts: TimelinePoint[];
  indicators: ServiceIndicator[];
  campaigns: Campaign[];
  infraClusters: InfraCluster[];
  entities: EntityProfile[];
  graph: GraphData;
  threatSummary: ThreatSummary;
};

const sourceSet = new Set<SourceType>(["telco", "bank", "gov", "osint", "infra"]);

const clamp = (value: number, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, value));

const withTimeout = <T>(promise: Promise<T>, label: string, ms = 12_000): Promise<T> =>
  new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(`${label}_timeout`)), ms);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });

const toSourceType = (raw: unknown): SourceType => {
  if (typeof raw === "string" && sourceSet.has(raw as SourceType)) {
    return raw as SourceType;
  }
  const s = String(raw ?? "").toLowerCase();
  if (s.includes("telco")) return "telco";
  if (s.includes("bank")) return "bank";
  if (s.includes("gov") || s.includes("kra") || s.includes("kpa")) return "gov";
  if (s.includes("osint")) return "osint";
  return "infra";
};

const toClock = (iso: unknown): string => {
  if (typeof iso !== "string" || iso.trim() === "") return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

const classificationTag = (eventType: string, classification: unknown): string => {
  const cls = String(classification ?? "").toLowerCase();
  if (cls.includes("critical")) return "critical";
  if (cls.includes("warning")) return "warning";
  if (cls.includes("restricted") || cls.includes("internal")) return "warning";
  if (eventType === "DDOS_SIGNAL_EVENT") return "critical";
  return "info";
};

const severityFromScore = (score: number): "high" | "medium" | "low" => {
  if (score >= 0.8) return "high";
  if (score >= 0.5) return "medium";
  return "low";
};

const asString = (value: unknown, fallback = ""): string => {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return fallback;
  return String(value);
};

const asNumber = (value: unknown, fallback = 0): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const SERVICE_PLACEHOLDERS = new Set(["", "unknown_service", "unknown", "n/a", "-", "na"]);
const ENDPOINT_PLACEHOLDERS = new Set(["", "n/a", "unknown", "unknown_endpoint", "-", "na"]);

const hasUsableService = (value: string): boolean => !SERVICE_PLACEHOLDERS.has(value.trim().toLowerCase());
const hasUsableEndpoint = (value: string): boolean => !ENDPOINT_PLACEHOLDERS.has(value.trim().toLowerCase());

const isIpAddress = (value: string): boolean => {
  const trimmed = value.trim();
  return /^(\d{1,3}\.){3}\d{1,3}$/.test(trimmed) || trimmed.includes(":");
};

const isSyntheticCampaignKey = (value: string): boolean => {
  const normalized = value.trim().toLowerCase();
  return (
    normalized === "" ||
    normalized.startsWith("gnn_component:") ||
    normalized.startsWith("gnn-component:") ||
    normalized.startsWith("gnn_component") ||
    normalized.startsWith("gnn-component")
  );
};

const humanizeCampaignName = (
  campaignId: string,
  type: string,
  primaryKey: string,
  eventCount: number,
  stats: Record<string, unknown>,
): string => {
  const explicitName = asString(stats.name, "").trim();
  if (explicitName && explicitName.toLowerCase() !== "campaign") return explicitName;
  if (isCanonicalEntityKey(primaryKey)) {
    return `${type.replaceAll("_", " ")} · ${displayEntityLabel(primaryKey)}`;
  }
  if (type === "GNN_COMPONENT") {
    const shortId = campaignId.slice(0, 4);
    return eventCount > 0
      ? `AI campaign group ${shortId} · ${eventCount} linked events`
      : `AI campaign group ${shortId}`;
  }
  if (primaryKey && !isSyntheticCampaignKey(primaryKey)) {
    return `${type.replaceAll("_", " ")} · ${primaryKey}`;
  }
  return `${type.replaceAll("_", " ")} · ${campaignId.slice(0, 4)}`;
};

const buildEventSummary = (eventType: string, payload: Record<string, unknown>, anchors: Record<string, unknown>): string => {
  const endpoint = asString(anchors.endpoint || payload.endpoint, "");
  const service = asString(anchors.service_id || payload.service_id, "");
  if (eventType === "DDOS_SIGNAL_EVENT") {
    const reqRate = payload.req_rate ?? payload.reqRate;
    if (reqRate !== undefined) return `DDoS signal on ${service}${endpoint ? ` ${endpoint}` : ""}, req rate ${reqRate}`;
    return `DDoS signal on ${service}${endpoint ? ` ${endpoint}` : ""}`;
  }
  if (eventType === "SERVICE_HEALTH_EVENT") {
    const status = asString(payload.status, "unknown");
    return `Service health ${status}${service ? ` for ${service}` : ""}`;
  }
  return `${eventType}${service ? ` for ${service}` : ""}`;
};

const mapEvents = (items: Array<Record<string, unknown>>): EventRecord[] => {
  return items.map((item) => {
    const anchors = (item.anchors as Record<string, unknown> | undefined) ?? {};
    const payload = (item.payload as Record<string, unknown> | undefined) ?? {};
    const eventType = asString(item.event_type, "UNKNOWN_EVENT");
    const source = toSourceType(item.source_type ?? item.source_id);
    const serviceId = asString(anchors.service_id ?? payload.service_id, "unknown_service");
    const endpoint = asString(anchors.endpoint ?? payload.endpoint, "n/a");
    const ip = asString(anchors.ip ?? payload.ip ?? payload.src_ip, "");
    const eventHash = asString(item.event_hash, "event-unknown");
    const occurredAt = asString(item.occurred_at, "");
    const receivedAt = asString(item.received_at, occurredAt);
    const summary = buildEventSummary(eventType, payload, anchors);

    return {
      event_hash: eventHash,
      type: eventType,
      source,
      classification: classificationTag(eventType, item.classification),
      confidence: clamp(asNumber(payload.confidence ?? item.confidence, 0.75)),
      occurred_at: occurredAt,
      received_at: receivedAt,
      service_id: serviceId,
      endpoint,
      ip: isIpAddress(ip) ? ip : undefined,
      summary,
      evidence: [
        {
          event_hash: eventHash,
          source,
          detail: summary,
        },
      ],
    };
  });
};

const mapTimeline = (timeline: EventsTimelineResponse): TimelinePoint[] => {
  const pointsRaw =
    Array.isArray(timeline)
      ? timeline.map((p) => ({ t: p.timestamp, count: p.count }))
      : timeline.points ?? [];
  return pointsRaw.map((p) => ({
    label: toClock(p.t ?? ""),
    value: asNumber(p.count, 0),
  }));
};

export const mapCampaigns = (items: Array<Record<string, unknown>>): Campaign[] => {
  return items.map((c, idx) => {
    const score = clamp(asNumber(c.score, 0));
    const confidence = Math.round(score * 100);
    const status = asString(c.status, "active");
    const campaignId = asString(c.campaign_id, `campaign-${idx}`);
    const primaryKey = asString(c.primary_key, "");
    const firstSeen = asString(c.first_seen, "");
    const lastSeen = asString(c.last_seen, "");
    const eventCount = asNumber(c.event_count, 0);
    const stats = (c.stats as Record<string, unknown> | undefined) ?? {};
    const discovery = asString(stats.discovery, "");

    return {
      id: campaignId,
      name: humanizeCampaignName(campaignId, asString(c.type, "Campaign"), primaryKey, eventCount, stats),
      type: asString(c.type, "Campaign"),
      primaryKey,
      discovery,
      eventCount,
      confidence,
      status,
      severity: severityFromScore(score),
      first_seen: toClock(firstSeen),
      last_seen: toClock(lastSeen),
      confidence_history: [Math.max(10, confidence - 35), Math.max(20, confidence - 20), Math.max(30, confidence - 10), confidence],
      top_entities: primaryKey
        ? [
            { label: primaryKey, role: "primary_key" },
            { label: `events:${eventCount}`, role: "activity" },
          ]
        : [{ label: `events:${eventCount}`, role: "activity" }],
      factors: [
        `Event count ${eventCount}`,
        `Campaign score ${score.toFixed(2)}`,
      ],
    };
  });
};

const mapIndicatorsFromAlerts = (items: Array<Record<string, unknown>>): ServiceIndicator[] => {
  const latestByPair = new Map<string, Record<string, unknown>>();
  for (const item of items) {
    const serviceId = asString(item.service_id, "");
    if (!serviceId) continue;
    const endpoint = asString(item.endpoint, "n/a");
    const key = `${serviceId}||${endpoint}`;
    const prior = latestByPair.get(key);
    const currentTs = new Date(asString(item.window_end, "")).getTime() || 0;
    const priorTs = prior ? (new Date(asString(prior.window_end, "")).getTime() || 0) : 0;
    if (!prior || currentTs >= priorTs) {
      latestByPair.set(key, item);
    }
  }

  return Array.from(latestByPair.values()).map((item) => {
    const serviceId = asString(item.service_id, "");
    const endpoint = asString(item.endpoint, "n/a");
    const risk = clamp(asNumber(item.risk, 0) / 100);
    const convergence = clamp(asNumber(item.convergence, 0));
    const uniqueGrowth = asNumber(item.unique_ip_growth_z, 0);
    const stage = asString(item.stage, "normal").toLowerCase();
    const label = toClock(asString(item.window_end, asString(item.window_start, "")));

    return {
      serviceId,
      endpoint,
      window: [label],
      reqRate: [Math.max(0, Math.round(asNumber(item.spike_z, 0) * 10))],
      uniqueIps: [Math.max(0, Math.round(Math.abs(uniqueGrowth) * 10))],
      asnConcentration: [Math.round(convergence * 80)],
      endpointConvergence: [Math.round(convergence * 100)],
      anomalyScore: [risk],
      ddosRisk: [risk],
      stage,
      factors: [
        `Stage ${stage}`,
        `Risk ${risk.toFixed(2)}`,
        `Spike Z ${asNumber(item.spike_z, 0).toFixed(2)}`,
        `IP growth Z ${uniqueGrowth.toFixed(2)}`,
      ],
    };
  });
};

type CampaignEvidenceResponse = {
  evidence?: Array<{
    event_hash?: string;
    entities?: Record<string, unknown>;
  }>;
};

const mapInfraCluster = (base: Record<string, unknown>): InfraCluster => {
  const clusterId = asString(base.cluster_id, "cluster");
  const confidenceRaw = asNumber(base.confidence, 0);
  const confidence = confidenceRaw <= 1 ? Math.round(confidenceRaw * 100) : Math.round(confidenceRaw);
  const summary = (base.summary as Record<string, unknown> | undefined) ?? {};
  const clusterWindowStart = asString(base.window_start, "");
  const clusterWindowEnd = asString(base.window_end, "");

  const members = Array.isArray(base.members)
    ? base.members
      .map((member) => asString(member, ""))
      .filter((member) => member !== "")
      .slice(0, 20)
    : [];

  const reasons = Array.from(
    new Set(
      Array.isArray(summary.reason_codes)
        ? summary.reason_codes.map((value) => asString(value, "")).filter((value) => value !== "")
        : [],
    ),
  ).slice(0, 6);

  const evidenceHashes = Array.isArray(summary.event_hashes)
    ? summary.event_hashes.map((value) => asString(value, "")).filter((value) => value !== "")
    : [];
  const evidence = evidenceHashes.slice(0, 10).map((eventHash) => ({
    event_hash: eventHash,
    source: "infra" as SourceType,
    detail: reasons[0] ?? "linked",
  }));

  const rotation = members.slice(0, 5).map((ip) => ({
    ip,
    window: `${toClock(clusterWindowStart)}-${toClock(clusterWindowEnd)}`,
    provider: asString((summary.providers as string[] | undefined)?.[0], "unknown"),
  }));

  return {
    id: clusterId,
    type: asString(base.kind, "infra"),
    confidence,
    provider: asString((summary.providers as string[] | undefined)?.[0], "unknown"),
    asn: asString((summary.top_providers as string[] | undefined)?.[0], "n/a"),
    members,
    reasons: reasons.length > 0 ? reasons : ["correlated_by_activity_window"],
    rotation,
    evidence,
  };
};

const deriveEntities = (events: EventRecord[], indicators: ServiceIndicator[]): EntityProfile[] => {
  const byService = new Map<string, EventRecord[]>();
  events.forEach((ev) => {
    const arr = byService.get(ev.service_id) ?? [];
    arr.push(ev);
    byService.set(ev.service_id, arr);
  });

  return Array.from(byService.entries()).map(([serviceId, evs]) => {
    const indicator = indicators.find((i) => i.serviceId === serviceId);
    const risk = indicator
      ? indicator.ddosRisk[indicator.ddosRisk.length - 1] >= 0.8
        ? "high"
        : indicator.ddosRisk[indicator.ddosRisk.length - 1] >= 0.5
          ? "medium"
          : "low"
      : "low";

    return {
      id: canonicalServiceKey(serviceId),
      label: serviceId,
      type: "Service",
      risk,
      first_seen: toClock(evs[evs.length - 1]?.occurred_at ?? "-"),
      last_seen: toClock(evs[0]?.occurred_at ?? "-"),
      sources: Array.from(new Set(evs.map((e) => e.source))),
      notes: [
        `Entity key ${canonicalServiceKey(serviceId)}`,
        `${evs.length} events observed`,
        `Top endpoint ${evs[0]?.endpoint ?? "n/a"}`,
      ],
    };
  });
};

const toGraphCommunity = (type: string): string => {
  const raw = type.toLowerCase();
  if (raw === "campaign") return "campaign";
  if (raw === "service" || raw === "endpoint") return "target";
  if (raw === "cluster" || raw === "ip" || raw === "provider" || raw === "asn") return "infra";
  return "support";
};

type MutableGraphNode = {
  id: string;
  label: string;
  type: string;
  community: string;
};

const buildGraphFromSnapshot = (
  events: EventRecord[],
  campaigns: Campaign[],
  infraClusters: InfraCluster[],
): GraphData => {
  const nodes = new Map<string, MutableGraphNode>();
  const servicesByIp = new Map<string, Set<string>>();
  const edges = new Map<
    string,
    {
      source: string;
      target: string;
      kind?: string;
      summary?: string;
      first_seen: string;
      last_seen: string;
      count: number;
      sources: Set<SourceType>;
      evidence: EvidenceItem[];
    }
  >();

  const upsertNode = (id: string, label: string, type: string) => {
    if (!nodes.has(id)) {
      nodes.set(id, { id, label, type, community: toGraphCommunity(type) });
    }
  };

  const upsertEdge = (
    id: string,
    source: string,
    target: string,
    sourceType: SourceType,
    firstSeen: string,
    lastSeen: string,
    evidence: EvidenceItem,
    kind?: string,
    summary?: string,
  ) => {
    const prev = edges.get(id);
    if (!prev) {
      edges.set(id, {
        source,
        target,
        kind,
        summary,
        first_seen: firstSeen,
        last_seen: lastSeen,
        count: 1,
        sources: new Set([sourceType]),
        evidence: [evidence],
      });
      return;
    }
    prev.count += 1;
    prev.sources.add(sourceType);
    if (prev.evidence.length < 6 && !prev.evidence.find((item) => item.event_hash === evidence.event_hash)) {
      prev.evidence.push(evidence);
    }
  };

  for (const event of events) {
    const serviceId = hasUsableService(event.service_id) ? event.service_id.trim() : "";
    const endpoint = hasUsableEndpoint(event.endpoint) ? event.endpoint.trim() : "";
    const ip = event.ip && isIpAddress(event.ip) ? event.ip.trim() : "";

    const serviceNodeId = serviceId ? canonicalServiceKey(serviceId) : "";
    const endpointNodeId = endpoint
      ? canonicalEndpointKey(serviceId ? `${serviceId}:${endpoint}` : endpoint)
      : "";

    if (serviceNodeId) {
      upsertNode(serviceNodeId, serviceId, "Service");
    }
    if (endpointNodeId) {
      upsertNode(endpointNodeId, serviceId ? `${serviceId} ${endpoint}` : endpoint, "Endpoint");
    }
    if (ip) {
      upsertNode(`ip:${ip}`, ip, "IP");
      if (serviceNodeId) {
        const linkedServices = servicesByIp.get(ip) ?? new Set<string>();
        linkedServices.add(serviceNodeId);
        servicesByIp.set(ip, linkedServices);
      }
    }

    if (serviceNodeId && endpointNodeId) {
      upsertEdge(
        `edge:service-endpoint:${serviceId}:${endpoint}`,
        serviceNodeId,
        endpointNodeId,
        event.source,
        event.occurred_at,
        event.received_at,
        {
          event_hash: event.event_hash,
          source: event.source,
          detail: `Endpoint ${endpoint} belongs to service ${serviceId}`,
        },
        "service_endpoint",
        `${serviceId} exposes ${endpoint}`,
      );
    }

    const attackTargetNodeId = serviceNodeId || endpointNodeId;
    const attackTargetLabel = serviceId || endpoint;
    if (ip && attackTargetNodeId && attackTargetLabel) {
      const targetKind = serviceNodeId ? "service" : "endpoint";
      upsertEdge(
        `edge:attack:${ip}:${attackTargetNodeId}`,
        `ip:${ip}`,
        attackTargetNodeId,
        event.source,
        event.occurred_at,
        event.received_at,
        {
          event_hash: event.event_hash,
          source: event.source,
          detail: event.summary,
        },
        `attack_${targetKind}`,
        `${ip} was observed targeting ${attackTargetLabel}`,
      );
    }
  }

  for (const cluster of infraClusters) {
    const clusterNodeId = `cluster:${cluster.id}`;
    upsertNode(clusterNodeId, cluster.id, "Cluster");

    const provider = cluster.provider.trim();
    if (provider && provider !== "unknown") {
      const providerNodeId = `provider_id:${provider}`;
      upsertNode(providerNodeId, provider, "Provider");
      const detail = cluster.reasons[0] ?? "cluster_provider_link";
      const evidence = cluster.evidence[0] ?? {
        event_hash: `cluster-${cluster.id}`,
        source: "infra",
        detail,
      };
      upsertEdge(
        `edge:cluster-provider:${cluster.id}:${provider}`,
        clusterNodeId,
        providerNodeId,
        "infra",
        cluster.rotation[0]?.window ?? "-",
        cluster.rotation[cluster.rotation.length - 1]?.window ?? "-",
        evidence,
        "cluster_provider",
        `${cluster.id} is associated with provider ${provider}`,
      );
    }

    for (const member of cluster.members.slice(0, 12)) {
      const ipNodeId = `ip:${member}`;
      upsertNode(ipNodeId, member, "IP");
      const evidence = cluster.evidence[0] ?? {
        event_hash: `cluster-${cluster.id}-${member}`,
        source: "infra",
        detail: cluster.reasons[0] ?? "cluster_member_link",
      };
      upsertEdge(
        `edge:cluster-member:${cluster.id}:${member}`,
        clusterNodeId,
        ipNodeId,
        evidence.source,
        cluster.rotation[0]?.window ?? "-",
        cluster.rotation[cluster.rotation.length - 1]?.window ?? "-",
        evidence,
        "cluster_member",
        `${member} is a member of infra cluster ${cluster.id}`,
      );

      for (const serviceNodeId of servicesByIp.get(member) ?? []) {
        const serviceNode = nodes.get(serviceNodeId);
        if (!serviceNode) continue;
        upsertEdge(
          `edge:cluster-target:${cluster.id}:${serviceNodeId}`,
          clusterNodeId,
          serviceNodeId,
          "infra",
          cluster.rotation[0]?.window ?? "-",
          cluster.rotation[cluster.rotation.length - 1]?.window ?? "-",
          evidence,
          "cluster_target",
          `Infra cluster ${cluster.id} includes members observed against ${serviceNode.label}`,
        );
      }
    }
  }

  for (const campaign of campaigns.slice(0, 8)) {
    const campaignNodeId = `campaign:${campaign.id}`;
    upsertNode(campaignNodeId, campaign.name, "Campaign");
    const label = campaign.primaryKey?.trim() ?? "";
    if (!label || isSyntheticCampaignKey(label) || label.startsWith("events:")) continue;

    const linkedService = events.find((item) => item.service_id.toLowerCase() === label.toLowerCase());
    const targetNodeId = isCanonicalEntityKey(label)
      ? label
      : linkedService
        ? canonicalServiceKey(linkedService.service_id)
        : "";
    if (!targetNodeId) continue;
    if (!nodes.has(targetNodeId)) {
      upsertNode(
        targetNodeId,
        isCanonicalEntityKey(label) ? displayEntityLabel(label) : label,
        linkedService ? "Service" : "Entity",
      );
    }
    upsertEdge(
      `edge:campaign-entity:${campaign.id}:${targetNodeId}`,
      campaignNodeId,
      targetNodeId,
      "infra",
      campaign.first_seen,
      campaign.last_seen,
      {
        event_hash: `campaign-${campaign.id}`,
        source: "infra",
        detail: `${campaign.type} references ${displayEntityLabel(label)}`,
      },
      "campaign_link",
      `${campaign.name} is grouped around ${displayEntityLabel(label)}`,
    );
  }

  const degree = new Map<string, number>();
  for (const edge of edges.values()) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }

  const grouped = new Map<string, MutableGraphNode[]>();
  for (const node of nodes.values()) {
    const list = grouped.get(node.community) ?? [];
    list.push(node);
    grouped.set(node.community, list);
  }

  const nodeTypeOrder: Record<string, number> = {
    Service: 0,
    Endpoint: 1,
    Cluster: 0,
    Provider: 1,
    IP: 2,
    Campaign: 0,
    Entity: 3,
  };

  for (const list of grouped.values()) {
    list.sort((a, b) => {
      const degreeDelta = (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0);
      if (degreeDelta !== 0) return degreeDelta;
      const typeDelta = (nodeTypeOrder[a.type] ?? 99) - (nodeTypeOrder[b.type] ?? 99);
      if (typeDelta !== 0) return typeDelta;
      return a.label.localeCompare(b.label);
    });
  }

  const columnXByType: Record<string, number> = {
    Service: 94,
    Endpoint: 174,
    Cluster: 320,
    Provider: 360,
    IP: 408,
    Campaign: 590,
    Entity: 670,
  };

  const graphNodes = Array.from(nodes.values()).map((node) => {
    const group = grouped.get(node.community) ?? [node];
    const index = group.findIndex((item) => item.id === node.id);
    const step = Math.max(30, Math.floor(332 / Math.max(1, group.length)));
    const y = 70 + Math.min(index, 9) * step;
    return {
      id: node.id,
      label: node.label,
      type: node.type,
      x: columnXByType[node.type] ?? 680,
      y,
      community: node.community,
    };
  });

  const graphEdges = Array.from(edges.entries()).map(([id, edge]) => ({
    id,
    source: edge.source,
    target: edge.target,
    kind: edge.kind,
    summary: edge.summary,
    evidence: edge.evidence,
    first_seen: edge.first_seen,
    last_seen: edge.last_seen,
    count: edge.count,
    sources: Array.from(edge.sources),
  }));

  return {
    nodes: graphNodes,
    edges: graphEdges,
  };
};

export async function fetchBackendSnapshot(): Promise<BackendSnapshot> {
  const warnings: string[] = [];

  const now = new Date();
  const start = new Date(now.getTime() - 60 * 60 * 1000);

  const [readyRes, eventsRes, timelineRes, campaignsRes, ddosAlertsRes, infraRes] = await Promise.allSettled([
    withTimeout(apiFetchJson<ReadyResponse>(endpoints.ready()), "ready"),
    withTimeout(apiFetchJson<EventsSearchResponse>(endpoints.eventsSearch(80)), "events"),
    withTimeout(
      apiFetchJson<EventsTimelineResponse>(endpoints.eventsTimeline(start.toISOString(), now.toISOString(), "5m")),
      "timeline",
    ),
    withTimeout(apiFetchJson<CampaignsResponse>(endpoints.campaigns(15, 0)), "campaigns"),
    withTimeout(apiFetchJson<DdosAlertsResponse>(endpoints.ddosAlerts(20, 0)), "ddos_alerts"),
    withTimeout(apiFetchJson<InfraClustersResponse>(endpoints.infraClusters(10, 0)), "infra_clusters"),
  ]);

  const unwrap = <T>(result: PromiseSettledResult<T>, label: string, fallback: T): T => {
    if (result.status === "fulfilled") return result.value;
    warnings.push(`${label}_unavailable`);
    return fallback;
  };

  const ready = unwrap(readyRes, "ready", { status: "degraded", components: {} });
  const events = mapEvents(unwrap(eventsRes, "events", { items: [] }).items ?? []);
  const timelineCounts = mapTimeline(unwrap(timelineRes, "timeline", { points: [] }));
  const campaigns = mapCampaigns(unwrap(campaignsRes, "campaigns", { items: [] }).items ?? []);
  const ddosAlerts = unwrap(ddosAlertsRes, "ddos_alerts", { items: [] }).items ?? [];

  const indicators = mapIndicatorsFromAlerts(ddosAlerts);

  const infraItems = unwrap(infraRes, "infra_clusters", { items: [] }).items ?? [];
  const infraClusters = infraItems.map((item) => mapInfraCluster(item));

  const entities = deriveEntities(events, indicators);
  const graph = buildGraphFromSnapshot(events, campaigns, infraClusters);
  const mode: BackendSnapshot["mode"] = ready.status === "ok" && warnings.length === 0 ? "live" : "degraded";
  const connectionLabel =
    mode === "live"
      ? "Backend connected"
      : `Backend degraded (${Object.entries(ready.components ?? {}).map(([k, v]) => `${k}:${v}`).join(", ")})`;

  return {
    mode,
    connectionLabel,
    warnings,
    events,
    timelineCounts,
    indicators,
    campaigns,
    infraClusters,
    entities,
    graph,
    threatSummary: emptyThreatSummary,
  };
}

export async function fetchCampaignList(limit = 15, offset = 0): Promise<Campaign[]> {
  const response = await withTimeout(apiFetchJson<CampaignsResponse>(endpoints.campaigns(limit, offset)), "campaigns");
  return mapCampaigns(response.items ?? []);
}

export async function fetchEventFeed(limit = 80): Promise<EventRecord[]> {
  const response = await withTimeout(apiFetchJson<EventsSearchResponse>(endpoints.eventsSearch(limit)), "events");
  return mapEvents(response.items ?? []);
}

export async function createCasePacketFromCampaign(campaignId: string): Promise<CasePacket> {
  const res = await apiFetchJson<CasePacketApiResponse>(endpoints.caseFromCampaign(campaignId), { method: "POST" });
  const affected = (res.entities ?? []).map((e) => asString(e.entity_key, "")).filter((x) => x !== "");
  const evidencePaths = (res.evidence ?? []).map((e) => asString(e.event_hash, "")).filter((x) => x !== "");
  const entityDetails = (res.entities ?? []).flatMap((entity) => {
    const entityKey = asString(entity.entity_key, "");
    if (!entityKey) return [];
    const type = asString(entity.type, "");
    const role = asString(entity.role, "");
    return [
      {
        entity_key: entityKey,
        ...(type ? { type } : {}),
        ...(role ? { role } : {}),
      },
    ];
  });
  const evidenceTimeline = (res.evidence ?? []).flatMap((item) => {
    const eventHash = asString(item.event_hash, "");
    if (!eventHash) return [];
    const occurredAt = asString(item.occurred_at, "");
    return [
      {
        event_hash: eventHash,
        ...(occurredAt ? { occurred_at: occurredAt } : {}),
      },
    ];
  });
  const score = clamp(asNumber(res.campaign?.score, 0));
  const confidence = Math.round(score * 100);
  const severity = severityFromScore(score);
  const campaignType = asString(res.campaign?.type, "campaign");
  const eventCount = asNumber(res.summary?.event_count, evidencePaths.length);
  const entityCount = asNumber(res.summary?.distinct_entities, affected.length);
  const stage = asString(res.summary?.stage, "");
  const stageLabel = stage || "unclassified";
  const evidenceState = evidencePaths.length > 0 ? `${evidencePaths.length} evidence references attached` : "evidence detail still thin";
  const structuralState = Array.isArray(res.graph?.nodes) && res.graph.nodes.length > 0
    ? `${res.graph.nodes.length} graph nodes included`
    : "graph structure is minimal";

  return {
    id: asString(res.case_id, `CASE-${campaignId}`),
    campaignId: asString(res.campaign?.id, campaignId),
    summary: `${campaignType} case touching ${entityCount} entities across ${eventCount} events; stage ${stageLabel}; ${evidenceState}; ${structuralState}.`,
    confidence,
    severity,
    generated_at: asString(res.generated_at, ""),
    campaign_type: campaignType,
    campaign_primary_key: asString(res.campaign?.primary_key, ""),
    campaign_status: asString(res.campaign?.status, ""),
    event_count: eventCount,
    distinct_entities: entityCount,
    stage: (res.summary?.stage as string | null) ?? null,
    integrity_hash: asString(res.integrity?.hash, ""),
    graph_summary: {
      node_count: Array.isArray(res.graph?.nodes) ? res.graph?.nodes.length : 0,
      edge_count: Array.isArray(res.graph?.edges) ? res.graph?.edges.length : 0,
    },
    entity_details: entityDetails,
    evidence_timeline: evidenceTimeline,
    affected_entities: affected,
    evidence_paths: evidencePaths,
    recommended_actions: [
      { stakeholder: "SOC", actions: ["Validate alerts", "Confirm IOC activity", "Escalate priority response"] },
      { stakeholder: "Audit", actions: ["Preserve evidence", "Review access and change logs"] },
    ],
    ai_rationale: [
      `Campaign score ${score.toFixed(2)}`,
      `Stage ${asString(res.summary?.stage, "unknown")}`,
    ],
  };
}

function downloadJsonDocument(filename: string, payload: unknown): string {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
  return filename;
}

export async function downloadCasePacketFromCampaign(campaignId: string): Promise<string> {
  const payload = await apiFetchJson<Record<string, unknown>>(endpoints.caseFromCampaign(campaignId), { method: "POST" });
  return downloadJsonDocument(`sentinel-case-${campaignId}.json`, payload);
}

export async function downloadStixBundleForCampaign(campaignId: string): Promise<string> {
  const payload = await apiFetchJson<Record<string, unknown>>(endpoints.stixCaseByCampaign(campaignId), { method: "GET" });
  return downloadJsonDocument(`sentinel-case-${campaignId}.stix.json`, payload);
}

export async function fetchCampaignEvidenceForDrawer(campaignId: string): Promise<EvidenceItem[]> {
  const res = await apiFetchJson<CampaignEvidenceResponse>(endpoints.campaignEvidence(campaignId, 120));
  const rows = res.evidence ?? [];
  return rows
    .map((row) => {
      const eventHash = asString(row.event_hash, "");
      if (!eventHash) return null;
      const entityCount = row.entities ? Object.keys(row.entities).length : 0;
      return {
        event_hash: eventHash,
        source: "infra" as SourceType,
        detail: entityCount > 0 ? `campaign entity refs: ${entityCount}` : "campaign-linked event",
      };
    })
    .filter((item): item is EvidenceItem => item !== null);
}
