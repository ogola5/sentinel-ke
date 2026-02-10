import { useMemo, useState } from "react";
import type { EventRecord, SourceType } from "../types/domain";
import { BarChart } from "../components/Charts";
import { shortHash } from "../utils/formatters";

const eventTypes = [
  "DDOS_SIGNAL_EVENT",
  "SERVICE_HEALTH_EVENT",
  "DNS_RESOLUTION_EVENT",
  "OSINT_PROVIDER_EVENT",
];

const sourceLabel = (source: SourceType) => source.toUpperCase();

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
  events,
  timeline,
  activeSources,
  onSelectEvent,
  onShowGraph,
  onShowTimeline,
  onShowEvidence,
}: LiveFeedProps) {
  const [typeFilter, setTypeFilter] = useState("all");

  const filtered = useMemo(() => {
    return events.filter((event) => {
      if (!activeSources[event.source]) {
        return false;
      }
      if (typeFilter !== "all" && event.type !== typeFilter) {
        return false;
      }
      return true;
    });
  }, [events, activeSources, typeFilter]);

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S1</p>
          <h2>National Live Feed</h2>
          <p className="subtle">Multi-agency signal ingestion with provenance and hashes.</p>
        </div>
        <div className="live-indicator">
          <span className="pulse" />
          <span>Ingesting 4 sources</span>
        </div>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>Incoming events</h3>
            <div className="select-inline">
              <label htmlFor="event-type">Type</label>
              <select
                id="event-type"
                value={typeFilter}
                onChange={(event) => setTypeFilter(event.target.value)}
              >
                <option value="all">All</option>
                {eventTypes.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="table">
            <div className="table-row table-header">
              <span>Type</span>
              <span>Source</span>
              <span>Classification</span>
              <span>Event hash</span>
              <span>Occurred / Received</span>
              <span>Actions</span>
            </div>
            {filtered.map((event) => (
              <div
                key={event.event_hash}
                className="table-row table-button"
                role="button"
                tabIndex={0}
                onClick={() => onSelectEvent(event)}
                onKeyDown={(evt) => {
                  if (evt.key === "Enter" || evt.key === " ") {
                    evt.preventDefault();
                    onSelectEvent(event);
                  }
                }}
              >
                <span className={`tag tag-${event.classification}`}>{event.type}</span>
                <span className="chip">{sourceLabel(event.source)}</span>
                <span>{event.classification}</span>
                <span className="mono">{shortHash(event.event_hash)}</span>
                <span>
                  <div>{event.occurred_at}</div>
                  <div className="muted">{event.received_at}</div>
                </span>
                <span className="actions">
                  <button
                    className="ghost"
                    type="button"
                    onClick={(evt) => {
                      evt.stopPropagation();
                      onShowGraph(event);
                    }}
                  >
                    Show in Graph
                  </button>
                  <button
                    className="ghost"
                    type="button"
                    onClick={(evt) => {
                      evt.stopPropagation();
                      onShowTimeline(event);
                    }}
                  >
                    Timeline Context
                  </button>
                  <button
                    className="ghost"
                    type="button"
                    onClick={(evt) => {
                      evt.stopPropagation();
                      onShowEvidence(`Evidence for ${event.event_hash}`, event);
                    }}
                  >
                    Evidence
                  </button>
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Events per minute</h3>
            <span className="muted">Counts per minute (GET /v1/events/timeline)</span>
          </div>
          <BarChart data={timeline.map((item) => item.value)} />
          <div className="timeline-labels">
            {timeline.map((item) => (
              <span key={item.label}>{item.label}</span>
            ))}
          </div>
          <div className="insight-row">
            <div>
              <p className="label">Provenance coverage</p>
              <p className="stat">4 agencies + infra sensors</p>
            </div>
            <div>
              <p className="label">Audit trail</p>
              <p className="stat">event_hash anchored per signal</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
