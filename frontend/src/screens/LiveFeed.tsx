/**
 * LiveFeed — S1: National Live Feed
 *
 * Real-time threat events via SSE stream (/v1/stream/events).
 * Falls back to historical events from 30-second backend sync.
 *
 * UX: compact event cards in a scrollable column.
 *     Click any card → DetailPanel slides in with full event details.
 */
import { useMemo, useState } from "react";
import type { EventRecord, SourceType } from "../types/domain";
import { BarChart } from "../components/Charts";
import DetailPanel from "../components/DetailPanel";
import { useEventStream } from "../hooks/useEventStream";
import { shortHash } from "../utils/formatters";

const SOURCE_LABEL: Record<SourceType, string> = {
  telco: "TELCO",
  bank:  "BANK",
  gov:   "GOV",
  osint: "OSINT",
  infra: "INFRA",
};

function relativeTime(iso: string): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000)    return `${Math.round(diff / 1_000)}s ago`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  return `${Math.round(diff / 3_600_000)}h ago`;
}

type LiveFeedProps = {
  events: EventRecord[];
  timeline: { label: string; value: number }[];
  activeSources: Record<SourceType, boolean>;
  onSelectEvent: (event: EventRecord) => void;
  onShowGraph: (event: EventRecord) => void;
  onShowTimeline: (event: EventRecord) => void;
  onShowEvidence: (title: string, event: EventRecord) => void;
};

export default function LiveFeed({
  events: historicalEvents,
  timeline,
  activeSources,
  onSelectEvent,
  onShowGraph,
  onShowTimeline,
  onShowEvidence,
}: LiveFeedProps) {
  const [typeFilter, setTypeFilter] = useState("all");
  const [selected,   setSelected]   = useState<EventRecord | null>(null);

  const { liveEvents, streamStatus } = useEventStream();

  const merged = useMemo(() => {
    const seen = new Set<string>();
    const out: EventRecord[] = [];
    for (const e of [...liveEvents, ...historicalEvents]) {
      if (!seen.has(e.event_hash)) { seen.add(e.event_hash); out.push(e); }
    }
    return out;
  }, [liveEvents, historicalEvents]);

  const availableTypes = useMemo(
    () => Array.from(new Set(merged.map((e) => e.type))).sort(),
    [merged],
  );

  const filtered = useMemo(
    () => merged.filter(
      (e) => activeSources[e.source] && (typeFilter === "all" || e.type === typeFilter),
    ),
    [merged, activeSources, typeFilter],
  );

  const activeSourceCount = useMemo(
    () => new Set(filtered.map((e) => e.source)).size,
    [filtered],
  );

  const isLive = streamStatus === "live";

  const openDetail = (event: EventRecord) => {
    setSelected(event);
    onSelectEvent(event);
  };

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S1</p>
          <h2>National Live Feed</h2>
          <p className="subtle">Incoming events, live status, and quick evidence review.</p>
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

      <div className="grid-two">
        {/* ── Event card list ─────────────────────────────────────────────── */}
        <div className="panel panel-col">
          <div className="panel-header">
            <h3>Incoming events</h3>
            <div className="select-inline">
              <label htmlFor="lf-type">Type</label>
              <select
                id="lf-type"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
              >
                <option value="all">All</option>
                {availableTypes.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="event-card-list">
            {filtered.length === 0 && (
              <p className="muted ec-empty">
                {streamStatus === "connecting" ? "Connecting to stream…" : "No events match current filters."}
              </p>
            )}
            {filtered.map((event, idx) => {
              const isNew = idx < liveEvents.length && liveEvents.includes(event);
              return (
                <button
                  key={event.event_hash}
                  type="button"
                  className={`event-card${isNew ? " event-card-new" : ""}`}
                  onClick={() => openDetail(event)}
                >
                  <div className="ec-left">
                    <span className={`ec-type-badge ec-cls-${event.classification.toLowerCase()}`}>
                      {event.type.replace(/_/g, " ")}
                    </span>
                    <span className="ec-summary">{event.summary || event.type}</span>
                  </div>
                  <div className="ec-right">
                    <span className="chip ec-source">{SOURCE_LABEL[event.source] ?? event.source}</span>
                    <span className="ec-time muted">{relativeTime(event.occurred_at)}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* ── Timeline bar chart ────────────────────────────────────────── */}
        <div className="panel">
          <div className="panel-header">
            <h3>Events over time</h3>
            <span className="muted lf-interval-label">last 30 min</span>
          </div>
          <BarChart data={timeline.map((p) => p.value)} />
          <div className="timeline-labels">
            {timeline.map((p) => <span key={p.label}>{p.label}</span>)}
          </div>
          {timeline.length === 0 && <p className="muted">No timeline data yet.</p>}

          <p className="muted" style={{ marginTop: 12 }}>
            {liveEvents.length} new this session · {merged.length} event hashes in view
          </p>
        </div>
      </div>

      {/* ── Event detail panel ────────────────────────────────────────────── */}
      <DetailPanel
        open={!!selected}
        title={selected ? selected.type.replace(/_/g, " ") : ""}
        subtitle={selected?.service_id || undefined}
        onClose={() => setSelected(null)}
      >
        {selected && (
          <div className="dp-event-detail">
            <div className="dp-field-grid">
              <div>
                <p className="label">Event hash</p>
                <p className="mono">{shortHash(selected.event_hash)}</p>
              </div>
              <div>
                <p className="label">Source</p>
                <p>{SOURCE_LABEL[selected.source] ?? selected.source}</p>
              </div>
              <div>
                <p className="label">Classification</p>
                <p className={`dp-cls dp-cls-${selected.classification.toLowerCase()}`}>
                  {selected.classification}
                </p>
              </div>
              <div>
                <p className="label">Confidence</p>
                <p>{(selected.confidence * 100).toFixed(0)}%</p>
              </div>
              <div>
                <p className="label">Occurred</p>
                <p className="mono">{selected.occurred_at}</p>
              </div>
              <div>
                <p className="label">Received</p>
                <p className="mono">{selected.received_at}</p>
              </div>
              {selected.service_id && (
                <div>
                  <p className="label">Service</p>
                  <p>{selected.service_id}</p>
                </div>
              )}
              {selected.endpoint && (
                <div>
                  <p className="label">Endpoint</p>
                  <p className="mono">{selected.endpoint}</p>
                </div>
              )}
            </div>

            {selected.summary && (
              <div className="dp-summary-row">
                <p className="label">Summary</p>
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
                  {selected.evidence.map((ev) => (
                    <div key={ev.event_hash} className="list-item">
                      <span className="mono">{shortHash(ev.event_hash)}</span>
                      <span className="muted">{ev.detail}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}

            <div className="dp-actions">
              <button className="ghost" type="button"
                onClick={() => { onShowGraph(selected); setSelected(null); }}>
                Show in Graph
              </button>
              <button className="ghost" type="button"
                onClick={() => { onShowTimeline(selected); setSelected(null); }}>
                Timeline Context
              </button>
              <button className="ghost" type="button"
                onClick={() => { onShowEvidence(`Evidence — ${shortHash(selected.event_hash)}`, selected); setSelected(null); }}>
                Full Evidence
              </button>
            </div>
          </div>
        )}
      </DetailPanel>
    </section>
  );
}
