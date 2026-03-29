/**
 * LiveFeed — S1: National Live Feed
 *
 * Real-time threat events via SSE stream (/v1/stream/events).
 * Falls back to historical events from backend sync.
 *
 * UX goal:
 *   show what changed now,
 *   what needs review first,
 *   and which services are currently carrying pressure.
 */
import { useEffect, useMemo, useState } from "react";
import type { EventRecord, SourceType } from "../types/domain";
import type { OperationsSnapshot } from "../types/operations";
import { BarChart } from "../components/Charts";
import DetailPanel from "../components/DetailPanel";
import { useEventStream } from "../hooks/useEventStream";
import { fetchEventFeed } from "../api/backend";
import { shortHash } from "../utils/formatters";

const SOURCE_LABEL: Record<SourceType, string> = {
  telco: "TELCO",
  bank: "BANK",
  gov: "GOV",
  osint: "OSINT",
  infra: "INFRA",
};

const PRIORITY_EVENT_TYPES = new Set([
  "DDOS_SIGNAL_EVENT",
  "WEB_ATTACK_EVENT",
  "DFIR_FINDING_EVENT",
  "PHISHING_MESSAGE_EVENT",
  "FILE_INTEGRITY_EVENT",
  "VULNERABILITY_EVENT",
]);

type FeedSeverity = "critical" | "warning" | "info";
type FeedLane = "needs_review" | "watch" | "background";

type LiveFeedProps = {
  events: EventRecord[];
  operationsData?: OperationsSnapshot;
  timeline: { label: string; value: number }[];
  activeSources: Record<SourceType, boolean>;
  isSyncing?: boolean;
  onSelectEvent: (event: EventRecord) => void;
  onShowGraph: (event: EventRecord) => void;
  onShowTimeline: (event: EventRecord) => void;
  onShowEvidence: (title: string, event: EventRecord) => void;
};

function parseTs(value: string): number {
  if (!value) return 0;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatRelativeTime(value: string): string {
  const ts = parseTs(value);
  if (!ts) return "time unavailable";
  const diff = Date.now() - ts;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function formatMoment(value: string): string {
  const ts = parseTs(value);
  if (!ts) return value || "—";
  return new Date(ts).toLocaleString("en-KE", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatClock(value: string): string {
  const ts = parseTs(value);
  if (!ts) return value || "—";
  return new Date(ts).toLocaleTimeString("en-KE", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function humanizeEventType(value: string): string {
  return value.replace(/_/g, " ").toLowerCase();
}

function hasUsableValue(value: string | undefined): boolean {
  const normalized = String(value ?? "").trim().toLowerCase();
  return normalized !== "" && !["unknown_service", "unknown", "n/a", "-", "na"].includes(normalized);
}

function confidencePct(value: number): number {
  const normalized = value > 1 ? value / 100 : value;
  return Math.round(Math.max(0, Math.min(normalized, 1)) * 100);
}

function eventSeverity(event: EventRecord): FeedSeverity {
  const classification = String(event.classification ?? "").toLowerCase();
  if (classification.includes("critical") || classification.includes("secret")) return "critical";
  if (
    classification.includes("warning")
    || classification.includes("restricted")
    || classification.includes("confidential")
    || PRIORITY_EVENT_TYPES.has(event.type)
  ) {
    return "warning";
  }
  return "info";
}

function severityLabel(value: FeedSeverity): string {
  if (value === "critical") return "Critical";
  if (value === "warning") return "Review";
  return "Background";
}

function laneLabel(value: FeedLane): string {
  if (value === "needs_review") return "Needs review";
  if (value === "watch") return "Watch";
  return "Background";
}

function eventTargetLabel(event: EventRecord): string {
  const service = hasUsableValue(event.service_id) ? event.service_id : "";
  const endpoint = hasUsableValue(event.endpoint) ? event.endpoint : "";
  const ip = hasUsableValue(event.ip) ? event.ip : "";

  if (service && endpoint) return `${service} ${endpoint}`;
  if (service) return service;
  if (endpoint) return endpoint;
  if (ip) return ip;
  return humanizeEventType(event.type);
}

function eventOperatorSummary(event: EventRecord): string {
  const target = eventTargetLabel(event);
  if (event.summary?.trim()) return event.summary;
  return `${humanizeEventType(event.type)} touching ${target}`;
}

function eventWhyItMatters(event: EventRecord): string {
  const severity = eventSeverity(event);
  if (severity === "critical") {
    return "This event belongs in the immediate review lane because it looks like service-impacting or operator-relevant activity.";
  }
  if (severity === "warning") {
    return "This event should be correlated against nearby activity before deciding whether it is isolated noise or part of an active pattern.";
  }
  return "This event is best used as supporting context unless it begins clustering around the same service, endpoint, or infrastructure.";
}

function eventNextMove(event: EventRecord): string {
  const severity = eventSeverity(event);
  if (severity === "critical") {
    return "Open graph or timeline next to confirm whether the same infrastructure or campaign is touching this target.";
  }
  if (severity === "warning") {
    return "Review the affected service and compare nearby events before escalating.";
  }
  return "Keep this in the watch queue and look for repeated pressure on the same target.";
}

function eventLane(event: EventRecord, isNew: boolean): FeedLane {
  if (isNew) return "needs_review";
  const severity = eventSeverity(event);
  if (severity !== "info") return "needs_review";
  if (hasUsableValue(event.service_id) || hasUsableValue(event.endpoint)) return "watch";
  return "background";
}

export default function LiveFeed({
  events: historicalEvents,
  operationsData,
  timeline,
  activeSources,
  isSyncing = false,
  onSelectEvent,
  onShowGraph,
  onShowTimeline,
  onShowEvidence,
}: LiveFeedProps) {
  const [typeFilter, setTypeFilter] = useState("all");
  const [selected, setSelected] = useState<EventRecord | null>(null);
  const [fallbackEvents, setFallbackEvents] = useState<EventRecord[]>([]);
  const [fallbackLoading, setFallbackLoading] = useState(false);

  const { liveEvents, streamStatus } = useEventStream();

  useEffect(() => {
    if (historicalEvents.length > 0) {
      setFallbackEvents([]);
      return;
    }
    let cancelled = false;
    setFallbackLoading(true);
    void fetchEventFeed(80)
      .then((items) => {
        if (!cancelled) {
          setFallbackEvents(items);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFallbackEvents([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setFallbackLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [historicalEvents]);

  const anomalyFallbackEvents = useMemo(() => {
    const items = operationsData?.anomalies ?? [];
    const nowIso = new Date().toISOString();
    return items.map((item) => {
      const score = Math.max(0, Math.min(item.score, 1));
      const summary = item.reasonCodes.length > 0
        ? `Backend anomaly on ${item.serviceId}${item.endpoint && item.endpoint !== "n/a" ? ` ${item.endpoint}` : ""}: ${item.reasonCodes.join(", ")}`
        : `Backend anomaly on ${item.serviceId}${item.endpoint && item.endpoint !== "n/a" ? ` ${item.endpoint}` : ""}`;
      return {
        event_hash: item.id || `${item.serviceId}:${item.endpoint}:${item.windowEnd}`,
        type: "ANOMALY_ALERT",
        source: "infra" as const,
        classification: score >= 0.8 ? "critical" : "warning",
        confidence: score,
        occurred_at: nowIso,
        received_at: nowIso,
        service_id: item.serviceId || "unknown_service",
        endpoint: item.endpoint || "n/a",
        summary,
        evidence: [
          {
            event_hash: item.id || `${item.serviceId}:${item.endpoint}:${item.windowEnd}`,
            source: "infra" as const,
            detail: summary,
          },
        ],
      } satisfies EventRecord;
    });
  }, [operationsData?.anomalies]);

  const baseEvents = historicalEvents.length > 0
    ? historicalEvents
    : fallbackEvents.length > 0
      ? fallbackEvents
      : anomalyFallbackEvents;

  const liveEventHashes = useMemo(
    () => new Set(liveEvents.map((event) => event.event_hash)),
    [liveEvents],
  );

  const merged = useMemo(() => {
    const seen = new Set<string>();
    const out: EventRecord[] = [];
    for (const event of [...liveEvents, ...baseEvents]) {
      if (!seen.has(event.event_hash)) {
        seen.add(event.event_hash);
        out.push(event);
      }
    }
    return out.sort((left, right) => {
      const leftTs = parseTs(left.occurred_at) || parseTs(left.received_at);
      const rightTs = parseTs(right.occurred_at) || parseTs(right.received_at);
      return rightTs - leftTs;
    });
  }, [baseEvents, liveEvents]);

  const availableTypes = useMemo(
    () => Array.from(new Set(merged.map((event) => event.type))).sort(),
    [merged],
  );

  const filtered = useMemo(
    () => merged.filter(
      (event) => activeSources[event.source] && (typeFilter === "all" || event.type === typeFilter),
    ),
    [merged, activeSources, typeFilter],
  );

  const feedSections = useMemo(() => {
    const lanes: Record<FeedLane, EventRecord[]> = {
      needs_review: [],
      watch: [],
      background: [],
    };
    for (const event of filtered) {
      lanes[eventLane(event, liveEventHashes.has(event.event_hash))].push(event);
    }
    return lanes;
  }, [filtered, liveEventHashes]);

  const activeSourceCount = useMemo(
    () => new Set(filtered.map((event) => event.source)).size,
    [filtered],
  );

  const liveSessionCount = useMemo(
    () => filtered.filter((event) => liveEventHashes.has(event.event_hash)).length,
    [filtered, liveEventHashes],
  );

  const distinctTargetCount = useMemo(
    () => new Set(filtered.map((event) => eventTargetLabel(event))).size,
    [filtered],
  );

  const avgConfidence = useMemo(() => {
    if (filtered.length === 0) return 0;
    const total = filtered.reduce((sum, event) => sum + confidencePct(event.confidence), 0);
    return Math.round(total / filtered.length);
  }, [filtered]);

  const servicePressure = useMemo(() => {
    const grouped = new Map<string, {
      label: string;
      total: number;
      priority: number;
      fresh: number;
      lastSeen: string;
      sources: Set<SourceType>;
    }>();

    for (const event of filtered) {
      const label = hasUsableValue(event.service_id)
        ? event.service_id
        : hasUsableValue(event.endpoint)
          ? event.endpoint
          : "";
      if (!label) continue;

      const lane = eventLane(event, liveEventHashes.has(event.event_hash));
      const row = grouped.get(label) ?? {
        label,
        total: 0,
        priority: 0,
        fresh: 0,
        lastSeen: event.occurred_at || event.received_at,
        sources: new Set<SourceType>(),
      };

      row.total += 1;
      if (lane === "needs_review") row.priority += 1;
      if (liveEventHashes.has(event.event_hash)) row.fresh += 1;
      if ((parseTs(event.occurred_at) || parseTs(event.received_at)) > parseTs(row.lastSeen)) {
        row.lastSeen = event.occurred_at || event.received_at;
      }
      row.sources.add(event.source);
      grouped.set(label, row);
    }

    return Array.from(grouped.values())
      .sort((left, right) => {
        if (right.priority !== left.priority) return right.priority - left.priority;
        if (right.fresh !== left.fresh) return right.fresh - left.fresh;
        if (right.total !== left.total) return right.total - left.total;
        return parseTs(right.lastSeen) - parseTs(left.lastSeen);
      })
      .slice(0, 6);
  }, [filtered, liveEventHashes]);

  const isLive = streamStatus === "live";

  const openDetail = (event: EventRecord) => {
    setSelected(event);
    onSelectEvent(event);
  };

  const selectedSeverity = selected ? eventSeverity(selected) : "info";
  const selectedLane = selected ? eventLane(selected, liveEventHashes.has(selected.event_hash)) : "background";

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S1</p>
          <h2>National Live Feed</h2>
          <p className="subtle">
            Watch what changed now, open the highest-priority events first, and follow pressure building on services and endpoints.
          </p>
        </div>
        <div className="lf-header-right">
          <span className={`stream-badge ${isLive ? "stream-live" : "stream-poll"}`}>
            <span className={isLive ? "pulse" : ""} />
            {isLive ? "LIVE" : streamStatus === "connecting" ? "CONNECTING…" : "POLL"}
          </span>
          <span className="lf-counts muted">
            {activeSourceCount} sources · {filtered.length} events
          </span>
        </div>
      </div>

      <div className="lf-top-grid">
        <article className="panel lf-kpi-card">
          <p className="workflow-stage-kicker">Immediate queue</p>
          <strong className="lf-kpi-value">{feedSections.needs_review.length}</strong>
          <p className="muted">events that need a human look first</p>
        </article>
        <article className="panel lf-kpi-card">
          <p className="workflow-stage-kicker">New this session</p>
          <strong className="lf-kpi-value">{liveSessionCount}</strong>
          <p className="muted">fresh events received since the stream opened</p>
        </article>
        <article className="panel lf-kpi-card">
          <p className="workflow-stage-kicker">Targets touched</p>
          <strong className="lf-kpi-value">{distinctTargetCount}</strong>
          <p className="muted">services or endpoints currently appearing in view</p>
        </article>
        <article className="panel lf-kpi-card">
          <p className="workflow-stage-kicker">Average confidence</p>
          <strong className="lf-kpi-value">{avgConfidence}%</strong>
          <p className="muted">signal confidence across the filtered feed</p>
        </article>
      </div>

      <div className="grid-two lf-layout">
        <div className="panel panel-col">
          <div className="panel-header">
            <div>
              <h3>Operator queue</h3>
              <p className="muted lf-queue-caption">
                Read from top to bottom: immediate review first, then watch-list activity, then background context.
              </p>
            </div>
            <div className="select-inline">
              <label htmlFor="lf-type">Type</label>
              <select
                id="lf-type"
                value={typeFilter}
                onChange={(event) => setTypeFilter(event.target.value)}
              >
                <option value="all">All</option>
                {availableTypes.map((type) => (
                  <option key={type} value={type}>{type}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="event-card-list lf-queue-list">
            {filtered.length === 0 && (
              <p className="muted ec-empty">
                {(isSyncing && merged.length === 0) || fallbackLoading
                  ? "Syncing events from the backend…"
                  : streamStatus === "connecting"
                    ? "Connecting to stream…"
                    : "No events match the current filter."}
              </p>
            )}

            {[
              {
                key: "needs_review" as const,
                title: "Needs review now",
                subtitle: "Open these first. They are new, higher-risk, or more likely to affect an operator decision.",
              },
              {
                key: "watch" as const,
                title: "Watch / corroborate",
                subtitle: "These are useful for pattern building even if they do not demand immediate escalation.",
              },
              {
                key: "background" as const,
                title: "Background context",
                subtitle: "Keep these as supporting evidence unless they start clustering around the same target or infrastructure.",
              },
            ].map((section) => (
              feedSections[section.key].length > 0 ? (
                <div key={section.key} className="lf-section">
                  <div className="lf-section-header">
                    <div>
                      <h4>{section.title}</h4>
                      <p className="muted">{section.subtitle}</p>
                    </div>
                    <span className="chip">{feedSections[section.key].length}</span>
                  </div>

                  {feedSections[section.key].map((event) => {
                    const isNew = liveEventHashes.has(event.event_hash);
                    const severity = eventSeverity(event);
                    return (
                      <button
                        key={event.event_hash}
                        type="button"
                        className={`event-card event-card-${severity}${isNew ? " event-card-new" : ""}`}
                        onClick={() => openDetail(event)}
                      >
                        <div className="ec-body">
                          <div className="ec-topline">
                            <span className={`ec-lane-badge ec-lane-${section.key.replace("_", "-")}`}>
                              {laneLabel(section.key)}
                            </span>
                            <span className={`ec-severity ec-severity-${severity}`}>
                              {severityLabel(severity)}
                            </span>
                            <span className="chip ec-source">{SOURCE_LABEL[event.source] ?? event.source}</span>
                            {isNew && <span className="chip ec-live-chip">New</span>}
                          </div>

                          <div className="ec-title-row">
                            <strong className="ec-title">{eventTargetLabel(event)}</strong>
                            <span className="ec-time muted">{formatRelativeTime(event.occurred_at || event.received_at)}</span>
                          </div>

                          <p className="ec-summary">{eventOperatorSummary(event)}</p>

                          <div className="ec-meta-row">
                            <span className="muted">{formatClock(event.occurred_at || event.received_at)}</span>
                            <span className="muted">{confidencePct(event.confidence)}% confidence</span>
                            <span className="muted">{event.evidence.length} evidence ref{event.evidence.length === 1 ? "" : "s"}</span>
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              ) : null
            ))}
          </div>
        </div>

        <div className="panel panel-col">
          <div className="panel-header">
            <h3>Operator context</h3>
            <span className="muted lf-interval-label">make sense of the queue</span>
          </div>

          <div className="lf-guide-grid">
            <div className="lf-guide-card">
              <p className="workflow-stage-kicker">How to read this feed</p>
              <ul className="lf-guide-list">
                <li>`Needs review` means new or operator-relevant events that should be opened first.</li>
                <li>`Watch` means useful corroboration activity around a service or endpoint.</li>
                <li>`Background` means low-priority context until it clusters into a clearer pattern.</li>
              </ul>
            </div>

            <div className="lf-guide-card">
              <p className="workflow-stage-kicker">What to do next</p>
              <ul className="lf-guide-list">
                <li>Open the event detail first to understand the target and the operator meaning.</li>
                <li>Use `Show in Graph` when you want to see who is touching the same service or infrastructure.</li>
                <li>Use `Timeline Context` when the question is whether pressure is rising or isolated.</li>
              </ul>
            </div>
          </div>

          <div className="lf-service-panel">
            <div className="panel-header">
              <h3>Services under pressure</h3>
              <span className="muted">{servicePressure.length} active targets</span>
            </div>
            {servicePressure.length === 0 ? (
              <p className="muted">No service or endpoint concentration is visible in the current filter.</p>
            ) : (
              <div className="lf-service-list">
                {servicePressure.map((row) => (
                  <div key={row.label} className="lf-service-item">
                    <div>
                      <strong>{row.label}</strong>
                      <p className="muted">
                        {row.priority} immediate · {row.total} total · {row.fresh} new
                      </p>
                    </div>
                    <div className="lf-service-meta">
                      <span className="chip">{row.sources.size} source{row.sources.size === 1 ? "" : "s"}</span>
                      <span className="muted">{formatRelativeTime(row.lastSeen)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="lf-timeline-panel">
            <div className="panel-header">
              <h3>Events over time</h3>
              <span className="muted lf-interval-label">last 30 min</span>
            </div>
            <BarChart data={timeline.map((point) => point.value)} />
            <div className="timeline-labels">
              {timeline.map((point) => <span key={point.label}>{point.label}</span>)}
            </div>
            {timeline.length === 0 && <p className="muted">No timeline data yet.</p>}
            <p className="muted lf-timeline-copy">
              Use the chart to decide whether the queue is a short burst, a sustained wave, or normal background traffic.
            </p>
          </div>
        </div>
      </div>

      <DetailPanel
        open={!!selected}
        title={selected ? eventTargetLabel(selected) : ""}
        subtitle={selected ? humanizeEventType(selected.type) : undefined}
        onClose={() => setSelected(null)}
      >
        {selected && (
          <div className="dp-event-detail">
            <div className={`lf-detail-brief lf-detail-${selectedSeverity}`}>
              <p className="label">Operator readout</p>
              <p>
                {eventOperatorSummary(selected)} {eventWhyItMatters(selected)} {eventNextMove(selected)}
              </p>
            </div>

            <div className="dp-field-grid">
              <div>
                <p className="label">Event hash</p>
                <p className="mono">{shortHash(selected.event_hash)}</p>
              </div>
              <div>
                <p className="label">Queue lane</p>
                <p className={`lf-inline-severity lf-inline-${selectedSeverity}`}>{laneLabel(selectedLane)}</p>
              </div>
              <div>
                <p className="label">Severity</p>
                <p className={`lf-inline-severity lf-inline-${selectedSeverity}`}>{severityLabel(selectedSeverity)}</p>
              </div>
              <div>
                <p className="label">Confidence</p>
                <p>{confidencePct(selected.confidence)}%</p>
              </div>
              <div>
                <p className="label">Source</p>
                <p>{SOURCE_LABEL[selected.source] ?? selected.source}</p>
              </div>
              <div>
                <p className="label">Evidence refs</p>
                <p>{selected.evidence.length}</p>
              </div>
              <div>
                <p className="label">Occurred</p>
                <p className="mono">{formatMoment(selected.occurred_at)}</p>
              </div>
              <div>
                <p className="label">Received</p>
                <p className="mono">{formatMoment(selected.received_at)}</p>
              </div>
              {hasUsableValue(selected.service_id) && (
                <div>
                  <p className="label">Service</p>
                  <p>{selected.service_id}</p>
                </div>
              )}
              {hasUsableValue(selected.endpoint) && (
                <div>
                  <p className="label">Endpoint</p>
                  <p className="mono">{selected.endpoint}</p>
                </div>
              )}
              {hasUsableValue(selected.ip) && (
                <div>
                  <p className="label">Observed IP</p>
                  <p className="mono">{selected.ip}</p>
                </div>
              )}
            </div>

            <div className="dp-summary-row">
              <p className="label">What this event means</p>
              <p>{eventWhyItMatters(selected)}</p>
            </div>

            <div className="dp-summary-row">
              <p className="label">Suggested next move</p>
              <p>{eventNextMove(selected)}</p>
            </div>

            {selected.summary && (
              <div className="dp-summary-row">
                <p className="label">Raw summary</p>
                <p>{selected.summary}</p>
              </div>
            )}

            {selected.evidence.length > 0 && (
              <details className="panel panel-details dp-evidence-row">
                <summary>
                  <span>Evidence</span>
                  <span className="muted">{selected.evidence.length} related event hash{selected.evidence.length !== 1 ? "es" : ""}</span>
                </summary>
                <div className="list" style={{ marginTop: 12 }}>
                  {selected.evidence.map((evidence) => (
                    <div key={evidence.event_hash} className="list-item">
                      <span className="mono">{shortHash(evidence.event_hash)}</span>
                      <span className="muted">{evidence.detail}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}

            <div className="dp-actions">
              <button
                className="ghost"
                type="button"
                onClick={() => {
                  onShowGraph(selected);
                  setSelected(null);
                }}
              >
                Show in Graph
              </button>
              <button
                className="ghost"
                type="button"
                onClick={() => {
                  onShowTimeline(selected);
                  setSelected(null);
                }}
              >
                Timeline Context
              </button>
              <button
                className="ghost"
                type="button"
                onClick={() => {
                  onShowEvidence(`Evidence — ${shortHash(selected.event_hash)}`, selected);
                  setSelected(null);
                }}
              >
                Full Evidence
              </button>
            </div>
          </div>
        )}
      </DetailPanel>
    </section>
  );
}
