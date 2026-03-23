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

type DdosIndicatorsResponse = {
  service_id?: string;
  endpoint?: string;
  series?: Array<{
    ts?: string;
    events?: number;
    unique_ips?: number;
    convergence?: number;
  }>;
  classification?: {
    stage?: string;
    risk?: number;
  };
  indicators?: {
    spike_z?: number;
    unique_ip_growth_z?: number;
    convergence?: number;
  };
};

type InfraClustersResponse = {
  items?: Array<Record<string, unknown>>;
};

type InfraClusterDetailResponse = {
  members?: Array<{ entity_key?: string }>;
  why_linked?: Array<{
    reason_code?: string;
    event_hashes?: string[];
    details?: Record<string, unknown>;
  }>;
  cluster?: {
    window_start?: string;
    window_end?: string;
    summary?: Record<string, unknown>;
  };
};

type CasePacketApiResponse = {
  case_id?: string;
  campaign?: {
    id?: string;
    score?: number;
  };
  summary?: {
    stage?: string | null;
  };
  entities?: Array<{
    entity_key?: string;
  }>;
  evidence?: Array<{
    event_hash?: string;
  }>;
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
    const eventHash = asString(item.event_hash, "event-unknown");
    const occurredAt = asString(item.occurred_at, "");
    const receivedAt = asString(item.received_at, occurredAt);
    const summary = buildEventSummary(eventType, payload, anchors);

    return {
      event_hash: eventHash,
      type: eventType,
      source,
      classification: classificationTag(eventType, item.classification),
      confidence: 75,
      occurred_at: toClock(occurredAt),
      received_at: toClock(receivedAt),
      service_id: serviceId,
      endpoint,
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

const mapCampaigns = (items: Array<Record<string, unknown>>): Campaign[] => {
  return items.map((c, idx) => {
    const score = clamp(asNumber(c.score, 0));
    const confidence = Math.round(score * 100);
    const status = asString(c.status, "active");
    const primaryKey = asString(c.primary_key, "campaign");
    const firstSeen = asString(c.first_seen, "");
    const lastSeen = asString(c.last_seen, "");
    const eventCount = asNumber(c.event_count, 0);
    const stats = (c.stats as Record<string, unknown> | undefined) ?? {};

    return {
      id: asString(c.campaign_id, `campaign-${idx}`),
      name: asString(stats.name, `${asString(c.type, "Campaign")} ${primaryKey}`),
      type: asString(c.type, "Campaign"),
      confidence,
      status,
      severity: severityFromScore(score),
      first_seen: toClock(firstSeen),
      last_seen: toClock(lastSeen),
      confidence_history: [Math.max(10, confidence - 35), Math.max(20, confidence - 20), Math.max(30, confidence - 10), confidence],
      top_entities: [
        { label: primaryKey, role: "primary_key" },
        { label: `events:${eventCount}`, role: "activity" },
      ],
      factors: [
        `Event count ${eventCount}`,
        `Campaign score ${score.toFixed(2)}`,
      ],
    };
  });
};

const mapIndicatorsFromSeries = (input: DdosIndicatorsResponse): ServiceIndicator | null => {
  const serviceId = asString(input.service_id, "");
  if (!serviceId) return null;
  const endpoint = asString(input.endpoint, "n/a");
  const series = input.series ?? [];
  if (series.length === 0) return null;

  const window = series.map((s) => toClock(s.ts ?? ""));
  const reqRate = series.map((s) => asNumber(s.events, 0));
  const uniqueIps = series.map((s) => asNumber(s.unique_ips, 0));
  const endpointConvergence = series.map((s) => Math.round(asNumber(s.convergence, 0) * 100));
  const stage = asString(input.classification?.stage, "emerging").toLowerCase();
  const ddosRisk = series.map((_, i) => {
    if (i === series.length - 1) return clamp(asNumber(input.classification?.risk, 0));
    const ratio = (i + 1) / Math.max(1, series.length);
    return clamp(asNumber(input.classification?.risk, 0) * ratio);
  });
  const anomalyScore = ddosRisk.map((v) => clamp(v * 0.9));

  return {
    serviceId,
    endpoint,
    window,
    reqRate,
    uniqueIps,
    asnConcentration: endpointConvergence.map((v) => Math.round(v * 0.8)),
    endpointConvergence,
    anomalyScore,
    ddosRisk,
    stage,
    factors: [
      `Stage ${stage}`,
      `Risk ${asNumber(input.classification?.risk, 0).toFixed(2)}`,
      `Spike Z ${asNumber(input.indicators?.spike_z, 0).toFixed(2)}`,
      `IP growth Z ${asNumber(input.indicators?.unique_ip_growth_z, 0).toFixed(2)}`,
    ],
  };
};

type CampaignEvidenceResponse = {
  evidence?: Array<{
    event_hash?: string;
    entities?: Record<string, unknown>;
  }>;
};

const mapInfraCluster = (
  base: Record<string, unknown>,
  detail?: InfraClusterDetailResponse,
): InfraCluster => {
  const clusterId = asString(base.cluster_id, "cluster");
  const confidenceRaw = asNumber(base.confidence, 0);
  const confidence = confidenceRaw <= 1 ? Math.round(confidenceRaw * 100) : Math.round(confidenceRaw);
  const summary = (base.summary as Record<string, unknown> | undefined) ?? {};
  const clusterWindowStart = asString(base.window_start, "");
  const clusterWindowEnd = asString(base.window_end, "");

  const members = (detail?.members ?? [])
    .map((m) => asString(m.entity_key, ""))
    .filter((k) => k !== "")
    .map((k) => (k.startsWith("ip:") ? k.slice(3) : k))
    .slice(0, 20);

  const reasons = Array.from(
    new Set((detail?.why_linked ?? []).map((w) => asString(w.reason_code, "")).filter((r) => r !== "")),
  ).slice(0, 6);

  const evidence = (detail?.why_linked ?? []).slice(0, 10).flatMap((w) => {
    const hashes = Array.isArray(w.event_hashes) ? w.event_hashes : [];
    const reason = asString(w.reason_code, "linked");
    return hashes.slice(0, 2).map((h) => ({
      event_hash: h,
      source: "infra" as SourceType,
      detail: reason,
    }));
  });

  const rotation = members.slice(0, 5).map((ip) => ({
    ip,
    window: `${toClock(detail?.cluster?.window_start ?? clusterWindowStart)}-${toClock(detail?.cluster?.window_end ?? clusterWindowEnd)}`,
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
      first_seen: evs[evs.length - 1]?.occurred_at ?? "-",
      last_seen: evs[0]?.occurred_at ?? "-",
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
  const edges = new Map<
    string,
    {
      source: string;
      target: string;
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
  ) => {
    const prev = edges.get(id);
    if (!prev) {
      edges.set(id, {
        source,
        target,
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
    const serviceNodeId = canonicalServiceKey(event.service_id);
    const endpointNodeId = canonicalEndpointKey(
      event.service_id && event.endpoint ? `${event.service_id}:${event.endpoint}` : event.endpoint,
    );
    upsertNode(serviceNodeId, event.service_id, "Service");
    upsertNode(endpointNodeId, event.endpoint, "Endpoint");

    const edgeId = `edge:service-endpoint:${event.service_id}:${event.endpoint}`;
    upsertEdge(
      edgeId,
      serviceNodeId,
      endpointNodeId,
      event.source,
      event.occurred_at,
      event.received_at,
      {
        event_hash: event.event_hash,
        source: event.source,
        detail: event.summary,
      },
    );
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
      );
    }
  }

  for (const campaign of campaigns) {
    const campaignNodeId = `campaign:${campaign.id}`;
    upsertNode(campaignNodeId, campaign.id, "Campaign");
    for (const entity of campaign.top_entities) {
      const label = entity.label.trim();
      if (!label || label.startsWith("events:")) continue;
      const linkedService = events.find((item) => item.service_id.toLowerCase() === label.toLowerCase());
      const targetNodeId = isCanonicalEntityKey(label)
        ? label
        : linkedService
          ? canonicalServiceKey(linkedService.service_id)
          : `campaign-entity:${campaign.id}:${label}`;
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
          detail: `${entity.role}:${label}`,
        },
      );
    }
  }

  const grouped = new Map<string, MutableGraphNode[]>();
  for (const node of nodes.values()) {
    const list = grouped.get(node.community) ?? [];
    list.push(node);
    grouped.set(node.community, list);
  }

  const columnX: Record<string, number> = {
    target: 130,
    infra: 360,
    campaign: 590,
    support: 640,
  };

  const graphNodes = Array.from(nodes.values()).map((node) => {
    const group = grouped.get(node.community) ?? [node];
    const index = group.findIndex((item) => item.id === node.id);
    const step = Math.max(42, Math.floor(320 / Math.max(1, group.length)));
    const y = 70 + Math.min(index, 7) * step;
    return {
      id: node.id,
      label: node.label,
      type: node.type,
      x: columnX[node.community] ?? 680,
      y,
      community: node.community,
    };
  });

  const graphEdges = Array.from(edges.entries()).map(([id, edge]) => ({
    id,
    source: edge.source,
    target: edge.target,
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
  const ready = await apiFetchJson<ReadyResponse>(endpoints.ready());
  const warnings: string[] = [];

  const now = new Date();
  const start = new Date(now.getTime() - 60 * 60 * 1000);

  const [eventsRes, timelineRes, campaignsRes, ddosAlertsRes, infraRes, threatSummaryRes] = await Promise.allSettled([
    apiFetchJson<EventsSearchResponse>(endpoints.eventsSearch(120)),
    apiFetchJson<EventsTimelineResponse>(endpoints.eventsTimeline(start.toISOString(), now.toISOString(), "5m")),
    apiFetchJson<CampaignsResponse>(endpoints.campaigns(25, 0)),
    apiFetchJson<DdosAlertsResponse>(endpoints.ddosAlerts(20, 0)),
    apiFetchJson<InfraClustersResponse>(endpoints.infraClusters(10, 0)),
    apiFetchJson<ThreatSummary>(endpoints.aiIndicatorsSummary(7)),
  ]);

  const unwrap = <T>(result: PromiseSettledResult<T>, label: string, fallback: T): T => {
    if (result.status === "fulfilled") return result.value;
    warnings.push(`${label}_unavailable`);
    return fallback;
  };

  const events = mapEvents(unwrap(eventsRes, "events", { items: [] }).items ?? []);
  const timelineCounts = mapTimeline(unwrap(timelineRes, "timeline", { points: [] }));
  const campaigns = mapCampaigns(unwrap(campaignsRes, "campaigns", { items: [] }).items ?? []);
  const ddosAlerts = unwrap(ddosAlertsRes, "ddos_alerts", { items: [] }).items ?? [];

  const uniquePairs = Array.from(
    new Set(
      ddosAlerts.map((a) => {
        const serviceId = asString(a.service_id, "");
        const endpoint = asString(a.endpoint, "");
        return serviceId ? `${serviceId}||${endpoint}` : "";
      }),
    ),
  )
    .filter((x) => x !== "")
    .slice(0, 3);

  const indicatorResponses = await Promise.allSettled(
    uniquePairs.map(async (key) => {
      const [serviceId, endpoint] = key.split("||");
      return apiFetchJson<DdosIndicatorsResponse>(endpoints.ddosIndicators(serviceId, endpoint || undefined, 60));
    }),
  );
  const indicators = indicatorResponses
    .filter((result): result is PromiseFulfilledResult<DdosIndicatorsResponse> => {
      if (result.status === "fulfilled") return true;
      warnings.push("ddos_indicators_unavailable");
      return false;
    })
    .map((x) => mapIndicatorsFromSeries(x.value))
    .filter((x): x is ServiceIndicator => x !== null);

  const infraItems = unwrap(infraRes, "infra_clusters", { items: [] }).items ?? [];
  const detailTargets = infraItems.slice(0, 5);
  const details = await Promise.allSettled(
    detailTargets.map(async (c) => {
      const id = asString(c.cluster_id, "");
      if (!id) return null;
      const detail = await apiFetchJson<InfraClusterDetailResponse>(endpoints.infraClusterById(id));
      return { id, detail };
    }),
  );
  const detailMap = new Map(
    details
      .flatMap((result) => {
        if (result.status === "fulfilled") return result.value ? [result.value] : [];
        warnings.push("infra_cluster_details_unavailable");
        return [];
      })
      .map((d) => [d.id, d.detail]),
  );
  const infraClusters = infraItems.map((item) => {
    const id = asString(item.cluster_id, "");
    return mapInfraCluster(item, detailMap.get(id));
  });

  const entities = deriveEntities(events, indicators);
  const graph = buildGraphFromSnapshot(events, campaigns, infraClusters);
  const mode: BackendSnapshot["mode"] = ready.status === "ok" && warnings.length === 0 ? "live" : "degraded";
  const connectionLabel =
    mode === "live"
      ? "Backend connected"
      : `Backend degraded (${Object.entries(ready.components ?? {}).map(([k, v]) => `${k}:${v}`).join(", ")})`;

  const threatSummary: ThreatSummary =
    threatSummaryRes.status === "fulfilled" ? threatSummaryRes.value : emptyThreatSummary;

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
    threatSummary,
  };
}

export async function createCasePacketFromCampaign(campaignId: string): Promise<CasePacket> {
  const res = await apiFetchJson<CasePacketApiResponse>(endpoints.caseFromCampaign(campaignId), { method: "POST" });
  const affected = (res.entities ?? []).map((e) => asString(e.entity_key, "")).filter((x) => x !== "");
  const evidencePaths = (res.evidence ?? []).map((e) => asString(e.event_hash, "")).filter((x) => x !== "");
  const score = clamp(asNumber(res.campaign?.score, 0));
  const confidence = Math.round(score * 100);
  const severity = severityFromScore(score);

  return {
    id: asString(res.case_id, `CASE-${campaignId}`),
    campaignId: asString(res.campaign?.id, campaignId),
    summary: `Case generated from campaign ${campaignId}`,
    confidence,
    severity,
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
