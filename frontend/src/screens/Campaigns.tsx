import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader, RefreshCw } from "lucide-react";

import { Sparkline } from "../components/Charts";
import { apiFetchJson } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { Campaign } from "../types/domain";
import { formatConfidence } from "../utils/formatters";
import { displayEntityLabel, isCanonicalEntityKey } from "../utils/entityKeys";

type CampaignDetailResponse = {
  campaign_id?: string;
  type?: string;
  primary_key?: string;
  status?: string;
  score?: number;
  event_count?: number;
  first_seen?: string;
  last_seen?: string;
  stats?: Record<string, unknown>;
  entity_counts?: Record<string, number>;
  entities?: Array<{
    type?: string;
    key?: string;
    last_seen?: string;
  }>;
};

type CampaignRiskResponse = {
  items?: Array<{
    entity_key?: string;
    entity_type?: string;
    score?: number;
    reason_codes?: string[];
  }>;
};

type CampaignEventsResponse = {
  items?: Array<{
    event_hash?: string;
    occurred_at?: string;
  }>;
};

type CampaignEvidenceResponse = {
  count?: number;
  evidence?: Array<{
    event_hash?: string;
    occurred_at?: string;
  }>;
};

type CampaignDetailState = {
  detail: CampaignDetailResponse | null;
  riskItems: Array<{ entity_key: string; entity_type: string; score: number; reason_codes: string[] }>;
  events: Array<{ event_hash: string; occurred_at: string }>;
  evidence: Array<{ event_hash: string; occurred_at: string }>;
  evidenceCount: number;
};

type CampaignsProps = {
  campaigns: Campaign[];
  selectedId: string;
  onSelect: (campaignId: string) => void;
  onOpenGraph: () => void;
  onGenerateCase: () => void;
  onOpenInfra: () => void;
  onOpenEvidence: () => void;
};

function formatTs(value: string | undefined): string {
  if (!value) return "—";
  const ts = new Date(value).getTime();
  if (!Number.isFinite(ts)) return value;
  return new Date(ts).toLocaleString("en-KE", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function timeAgo(value: string | undefined): string {
  if (!value) return "unknown";
  const ts = new Date(value).getTime();
  if (!Number.isFinite(ts)) return value;
  const diff = Date.now() - ts;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function asString(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (value == null) return fallback;
  return String(value);
}

function asNumber(value: unknown, fallback = 0): number {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : fallback;
}

function toTitle(value: string): string {
  return value.replace(/_/g, " ").toLowerCase();
}

function humanEntityKey(value: string): string {
  return isCanonicalEntityKey(value) ? displayEntityLabel(value) : value;
}

function entityTypeLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized === "service_id") return "service";
  return normalized.replace(/_/g, " ");
}

function severityTone(value: string): "critical" | "high" | "medium" | "low" {
  const normalized = value.toLowerCase();
  if (normalized === "critical") return "critical";
  if (normalized === "high") return "high";
  if (normalized === "medium") return "medium";
  return "low";
}

function sumEntityCounts(entityCounts: Record<string, number>): number {
  return Object.values(entityCounts).reduce((sum, value) => sum + value, 0);
}

function topEntity(entries: Array<{ type?: string; key?: string; last_seen?: string }>, entityType: string): string | null {
  const match = entries.find((entry) => asString(entry.type).toLowerCase() === entityType && asString(entry.key));
  return match ? humanEntityKey(asString(match.key)) : null;
}

function buildCampaignStory(
  selected: Campaign,
  detail: CampaignDetailResponse | null,
  materialized: boolean,
): string {
  const entityCounts = detail?.entity_counts ?? {};
  const entities = detail?.entities ?? [];
  const service = topEntity(entities, "service_id");
  const endpoint = topEntity(entities, "endpoint");
  const ipCount = asNumber(entityCounts.ip, 0);
  const totalEntities = sumEntityCounts(entityCounts);
  const indicatorRatio = asNumber(detail?.stats?.indicator_ratio, 0);
  const discovery = asString(detail?.stats?.discovery, selected.discovery ?? "");
  const windowKey = asString(detail?.stats?.window_key, "");

  const targetLabel = service ?? endpoint ?? "multiple linked targets";
  const intro =
    selected.type === "GNN_COMPONENT"
      ? `This campaign is an AI-discovered campaign grouping around ${targetLabel}.`
      : `This campaign groups coordinated activity around ${targetLabel}.`;

  const footprint = totalEntities > 0
    ? `It currently spans ${totalEntities} linked entities, including ${ipCount} infrastructure nodes.`
    : `The structural footprint is still being materialized.`;

  const corroboration = indicatorRatio > 0
    ? `${Math.round(indicatorRatio * 100)}% of the component currently carries direct indicator coverage.`
    : "Direct indicator coverage is not yet explicitly reported for this campaign.";

  const readiness = materialized
    ? "Evidence and drill-down tables are populated, so you can review events, evidence, and blast radius here."
    : "This campaign exists structurally, but its event/risk materialization is still thin; graph and case packet views remain the stronger next steps.";

  const discoveryLine = discovery
    ? `Discovery path: ${toTitle(discovery)}${windowKey ? ` in ${windowKey}` : ""}.`
    : "";

  return [intro, footprint, corroboration, readiness, discoveryLine].filter(Boolean).join(" ");
}

export default function Campaigns({
  campaigns,
  selectedId,
  onSelect,
  onOpenGraph,
  onGenerateCase,
  onOpenInfra,
  onOpenEvidence,
}: CampaignsProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailState, setDetailState] = useState<CampaignDetailState>({
    detail: null,
    riskItems: [],
    events: [],
    evidence: [],
    evidenceCount: 0,
  });

  const selected = campaigns.find((campaign) => campaign.id === selectedId) ?? campaigns[0];

  const loadCampaignDetail = useCallback(async () => {
    if (!selected?.id) return;
    setLoading(true);
    setError(null);
    try {
      const [detailRes, riskRes, eventsRes, evidenceRes] = await Promise.all([
        apiFetchJson<CampaignDetailResponse>(endpoints.campaignById(selected.id), { method: "GET" }),
        apiFetchJson<CampaignRiskResponse>(endpoints.campaignRisk(selected.id, 12, 0), { method: "GET" }),
        apiFetchJson<CampaignEventsResponse>(endpoints.campaignEvents(selected.id, 12, 0), { method: "GET" }),
        apiFetchJson<CampaignEvidenceResponse>(endpoints.campaignEvidence(selected.id, 12), { method: "GET" }),
      ]);

      setDetailState({
        detail: detailRes,
        riskItems: (riskRes.items ?? []).map((item) => ({
          entity_key: asString(item.entity_key, ""),
          entity_type: asString(item.entity_type, ""),
          score: asNumber(item.score, 0),
          reason_codes: Array.isArray(item.reason_codes) ? item.reason_codes.map((value) => asString(value, "")).filter(Boolean) : [],
        })).filter((item) => item.entity_key !== ""),
        events: (eventsRes.items ?? []).map((item) => ({
          event_hash: asString(item.event_hash, ""),
          occurred_at: asString(item.occurred_at, ""),
        })).filter((item) => item.event_hash !== ""),
        evidence: (evidenceRes.evidence ?? []).map((item) => ({
          event_hash: asString(item.event_hash, ""),
          occurred_at: asString(item.occurred_at, ""),
        })).filter((item) => item.event_hash !== ""),
        evidenceCount: asNumber(evidenceRes.count, 0),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "request_failed");
      setDetailState({
        detail: null,
        riskItems: [],
        events: [],
        evidence: [],
        evidenceCount: 0,
      });
    } finally {
      setLoading(false);
    }
  }, [selected?.id]);

  useEffect(() => {
    void loadCampaignDetail();
    const timer = window.setInterval(() => {
      void loadCampaignDetail();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [loadCampaignDetail]);

  const entityCounts = detailState.detail?.entity_counts ?? {};
  const entityCountEntries = useMemo(
    () => Object.entries(entityCounts).sort((left, right) => right[1] - left[1]),
    [entityCounts],
  );

  const totalEntities = sumEntityCounts(entityCounts);
  const infraCount = (entityCounts.ip ?? 0) + (entityCounts.provider_id ?? 0) + (entityCounts.domain ?? 0) + (entityCounts.url ?? 0);
  const targetCount = (entityCounts.service_id ?? 0) + (entityCounts.endpoint ?? 0);
  const materialized = detailState.events.length > 0 || detailState.evidenceCount > 0 || detailState.riskItems.length > 0;
  const story = buildCampaignStory(selected, detailState.detail, materialized);
  const legalNotice = asString(detailState.detail?.stats?.legal_notice, "");
  const windowKey = asString(detailState.detail?.stats?.window_key, "");
  const componentSize = asNumber(detailState.detail?.stats?.component_size, totalEntities);
  const indicatorCount = asNumber(detailState.detail?.stats?.indicator_count, 0);

  if (campaigns.length === 0) {
    return (
      <section className="screen">
        <div className="screen-header">
          <div>
            <p className="eyebrow">S4</p>
            <h2>Campaign Console</h2>
            <p className="subtle">Coordinated operations with confidence growth.</p>
          </div>
        </div>
        <div className="panel">
          <p className="muted">No campaigns found in backend storage.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S4</p>
          <h2>Campaign Console</h2>
          <p className="subtle">
            This screen should answer: what operation is active, who and what it touches, and how much evidence is already attached.
          </p>
        </div>
        <div className="chip-row">
          <button className="ghost" type="button" onClick={() => void loadCampaignDetail()} disabled={loading}>
            {loading ? <Loader size={14} className="spin" /> : <RefreshCw size={14} />}
            &nbsp;Refresh
          </button>
          <button className="ghost" type="button" onClick={onOpenGraph}>
            Open in Graph
          </button>
        </div>
      </div>

      <div className="grid-two campaign-console-grid">
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>Active campaigns</h3>
              <p className="muted">Choose one campaign, then inspect its footprint and evidence state.</p>
            </div>
            <span className="muted">{campaigns.length} active</span>
          </div>
          <div className="campaign-list">
            {campaigns.map((campaign) => (
              <button
                key={campaign.id}
                className={campaign.id === selected.id ? "campaign-card active" : "campaign-card"}
                type="button"
                onClick={() => onSelect(campaign.id)}
              >
                <div className="campaign-card-main">
                  <p className="label">{campaign.name}</p>
                  <p className="muted">{campaign.type} · {campaign.status}</p>
                  <p className="campaign-card-meta">
                    {campaign.eventCount ?? 0} linked events
                    {campaign.discovery ? ` · ${toTitle(campaign.discovery)}` : ""}
                  </p>
                </div>
                <div className="campaign-card-side">
                  <div className="stat">{formatConfidence(campaign.confidence)}</div>
                  <span className={`risk-badge ${severityTone(campaign.severity)}`}>{campaign.severity}</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="panel campaign-detail-panel">
          <div className="panel-header">
            <div>
              <h3>{selected.name}</h3>
              <p className="muted">
                {selected.type} · {selected.status}
                {windowKey ? ` · ${windowKey}` : ""}
              </p>
            </div>
            <span className={`risk-badge ${severityTone(selected.severity)}`}>{selected.severity}</span>
          </div>

          {error && (
            <div className="campaign-state-banner campaign-state-warning">
              <strong>Campaign detail failed to load</strong>
              <p>{error}</p>
            </div>
          )}

          <div className="campaign-metric-grid">
            <article className="campaign-metric-card">
              <p className="workflow-stage-kicker">Confidence</p>
              <strong>{formatConfidence(selected.confidence)}</strong>
              <span className="muted">campaign-level confidence</span>
            </article>
            <article className="campaign-metric-card">
              <p className="workflow-stage-kicker">Entity footprint</p>
              <strong>{componentSize || totalEntities || "—"}</strong>
              <span className="muted">linked entities in this grouping</span>
            </article>
            <article className="campaign-metric-card">
              <p className="workflow-stage-kicker">Infrastructure</p>
              <strong>{infraCount}</strong>
              <span className="muted">infra-side nodes currently attached</span>
            </article>
            <article className="campaign-metric-card">
              <p className="workflow-stage-kicker">Targets</p>
              <strong>{targetCount}</strong>
              <span className="muted">service or endpoint targets in scope</span>
            </article>
          </div>

          <div className="campaign-story panel-subsection">
            <p className="label">What this campaign means</p>
            <p>{story}</p>
            {legalNotice && <p className="muted campaign-legal-note">{legalNotice}</p>}
          </div>

          <div className="detail-grid">
            <div>
              <p className="label">Window</p>
              <p className="stat">
                {formatTs(detailState.detail?.first_seen || selected.first_seen)} - {formatTs(detailState.detail?.last_seen || selected.last_seen)}
              </p>
            </div>
            <div>
              <p className="label">Indicator coverage</p>
              <p className="stat">{indicatorCount}</p>
            </div>
            <div>
              <p className="label">Primary key</p>
              <p className="mono">{detailState.detail?.primary_key ?? selected.primaryKey ?? "—"}</p>
            </div>
            <div>
              <p className="label">Materialized evidence</p>
              <p className="stat">{detailState.evidenceCount}</p>
            </div>
          </div>

          <div className="chip-row campaign-actions-bar">
            <button className="chip ghost" type="button" onClick={onOpenInfra}>
              View Infra Clusters
            </button>
            <button className="chip ghost" type="button" onClick={onOpenEvidence}>
              Evidence references
            </button>
            <button className="chip active" type="button" onClick={onGenerateCase}>
              Generate Case Packet
            </button>
          </div>

          <details className="panel-subsection collapsible-panel" open>
            <summary>
              <span>Footprint and entity mix</span>
              <span className="muted">
                {entityCountEntries.length > 0 ? `${entityCountEntries.length} entity types` : "No entity counts"}
              </span>
            </summary>
            {entityCountEntries.length === 0 ? (
              <p className="muted">This campaign has not published its entity mix yet.</p>
            ) : (
              <>
                <div className="campaign-entity-pills">
                  {entityCountEntries.map(([entityType, count]) => (
                    <span key={entityType} className="factor">
                      {entityTypeLabel(entityType)} · {count}
                    </span>
                  ))}
                </div>
                <div className="entity-roles" style={{ marginTop: 12 }}>
                  {(detailState.detail?.entities ?? []).slice(0, 8).map((entity) => (
                    <div key={`${entity.type}:${entity.key}`} className="entity-role">
                      <span>{humanEntityKey(asString(entity.key, "—"))}</span>
                      <span className="muted">
                        {entityTypeLabel(asString(entity.type, "entity"))} · {timeAgo(entity.last_seen)}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </details>

          <details className="panel-subsection collapsible-panel">
            <summary>
              <span>Recent linked activity</span>
              <span className="muted">{detailState.events.length} event rows</span>
            </summary>
            {detailState.events.length === 0 ? (
              <div className="campaign-state-banner">
                <strong>No materialized campaign event rows yet</strong>
                <p>
                  The structural campaign exists, but `campaign_event` rows have not been populated for this view. Use graph or case packet generation if you need the broader structure right now.
                </p>
              </div>
            ) : (
              <div className="campaign-inline-list">
                {detailState.events.map((event) => (
                  <div key={event.event_hash} className="campaign-inline-row">
                    <span className="mono">{event.event_hash.slice(0, 12)}…</span>
                    <span className="muted">{formatTs(event.occurred_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </details>

          <details className="panel-subsection collapsible-panel">
            <summary>
              <span>Blast radius and risk</span>
              <span className="muted">{detailState.riskItems.length} scored entities</span>
            </summary>
            {detailState.riskItems.length === 0 ? (
              <div className="campaign-state-banner">
                <strong>No campaign-specific blast radius rows yet</strong>
                <p>
                  This means the campaign exists as a grouping, but `campaign_risk` has not materialized a dedicated blast-radius list for this campaign yet.
                </p>
              </div>
            ) : (
              <div className="campaign-inline-list">
                {detailState.riskItems.slice(0, 8).map((item) => (
                  <div key={item.entity_key} className="campaign-inline-row campaign-inline-risk">
                    <div>
                      <strong>{humanEntityKey(item.entity_key)}</strong>
                      <p className="muted">{entityTypeLabel(item.entity_type)}</p>
                    </div>
                    <div className="campaign-risk-side">
                      <strong>{Math.round(item.score * 100)} / 100</strong>
                      <p className="muted">{item.reason_codes.slice(0, 2).join(" · ") || "no reason codes"}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </details>

          <details className="panel-subsection collapsible-panel">
            <summary>
              <span>Evidence state</span>
              <span className="muted">{detailState.evidenceCount} evidence rows</span>
            </summary>
            {detailState.evidence.length === 0 ? (
              <div className="campaign-state-banner">
                <strong>Evidence references are not yet materialized here</strong>
                <p>
                  The campaign itself is real, but this surface does not yet have attached evidence rows for drill-down. That is a backend state, not a frontend rendering failure.
                </p>
              </div>
            ) : (
              <div className="campaign-inline-list">
                {detailState.evidence.map((item) => (
                  <div key={item.event_hash} className="campaign-inline-row">
                    <span className="mono">{item.event_hash.slice(0, 12)}…</span>
                    <span className="muted">{formatTs(item.occurred_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </details>

          <details className="panel-subsection collapsible-panel">
            <summary>
              <span>Confidence history</span>
              <span className="muted">Open trend</span>
            </summary>
            <Sparkline data={selected.confidence_history} stroke="var(--accent)" />
          </details>
        </div>
      </div>
    </section>
  );
}
