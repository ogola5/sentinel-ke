import { useEffect, useMemo, useState } from "react";
import { Download, FileJson, Network, RefreshCw, ShieldCheck } from "lucide-react";

import type { CasePacket } from "../types/domain";
import { formatConfidence, shortHash } from "../utils/formatters";
import { fetchRecentCases } from "../api/graph";
import { displayEntityLabel, isCanonicalEntityKey } from "../utils/entityKeys";

type RecentCase = {
  campaign_id: string;
  type: string;
  primary_key: string;
  status: string;
  score: number;
  event_count: number;
  last_seen: string | null;
};

type CasePacketsProps = {
  packet?: CasePacket;
  onExportJson: () => void;
  onExportStix: () => void;
  onGenerateCaseForId: (id: string) => void;
};

function fmtTs(value?: string | null): string {
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

function timeAgo(value?: string | null): string {
  if (!value) return "unknown";
  const ts = new Date(value).getTime();
  if (!Number.isFinite(ts)) return value;
  const diff = Date.now() - ts;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function humanEntity(value: string): string {
  return isCanonicalEntityKey(value) ? displayEntityLabel(value) : value;
}

export default function CasePackets({ packet, onExportJson, onExportStix, onGenerateCaseForId }: CasePacketsProps) {
  const [recentCases, setRecentCases] = useState<RecentCase[]>([]);
  const [loadingRecent, setLoadingRecent] = useState(false);
  const [generatingId, setGeneratingId] = useState<string | null>(null);

  useEffect(() => {
    if (!packet) {
      setLoadingRecent(true);
      fetchRecentCases(20)
        .then((items) => setRecentCases(items as RecentCase[]))
        .catch(() => setRecentCases([]))
        .finally(() => setLoadingRecent(false));
    }
  }, [packet]);

  const handleGenerate = (id: string) => {
    setGeneratingId(id);
    onGenerateCaseForId(id);
  };

  const strongestRecent = useMemo(
    () => recentCases.reduce<RecentCase | null>((best, item) => (!best || item.score > best.score ? item : best), null),
    [recentCases],
  );

  if (!packet) {
    return (
      <section className="screen">
        <div className="screen-header">
          <div>
            <p className="eyebrow">S5</p>
            <h2>Case Packet + STIX Export</h2>
            <p className="subtle">
              This screen should take a campaign from investigation state into export-ready handoff with evidence, structure, and integrity.
            </p>
          </div>
        </div>

        <div className="case-top-grid">
          <article className="panel case-kpi-card">
            <p className="workflow-stage-kicker">Case-ready campaigns</p>
            <strong className="case-kpi-value">{recentCases.length}</strong>
            <span className="muted">campaigns currently available for packet generation</span>
          </article>
          <article className="panel case-kpi-card">
            <p className="workflow-stage-kicker">Strongest current score</p>
            <strong className="case-kpi-value">{strongestRecent ? Math.round(strongestRecent.score * 100) : 0}</strong>
            <span className="muted">top campaign score in the current queue</span>
          </article>
          <article className="panel case-kpi-card">
            <p className="workflow-stage-kicker">Recent linked events</p>
            <strong className="case-kpi-value">{recentCases.reduce((sum, item) => sum + item.event_count, 0)}</strong>
            <span className="muted">event rows attached to recent campaigns</span>
          </article>
        </div>

        <div className="grid-two case-console-grid">
          <div className="panel workflow-guide-panel">
            <div className="panel-header">
              <h3>How this screen should be used</h3>
              <span className="muted">Generate, verify, export</span>
            </div>
            <div className="workflow-compact-grid">
              <div>
                <p className="workflow-stage-kicker">Step 1</p>
                <p className="workflow-stage-copy">Choose a recent campaign and generate the packet from backend evidence.</p>
              </div>
              <div>
                <p className="workflow-stage-kicker">Step 2</p>
                <p className="workflow-stage-copy">Verify affected entities, evidence rows, graph structure, and integrity marker.</p>
              </div>
              <div>
                <p className="workflow-stage-kicker">Step 3</p>
                <p className="workflow-stage-copy">Export JSON or STIX only after the packet reads clearly enough for external handoff.</p>
              </div>
              <div>
                <p className="workflow-stage-kicker">Meaning</p>
                <p className="workflow-stage-copy">S5 is not for triage. It is for handoff, briefing, and evidence preservation.</p>
              </div>
            </div>
          </div>

          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>Recent campaigns</h3>
              <span className="muted">{loadingRecent ? "Loading…" : `${recentCases.length} available`}</span>
            </div>
            {loadingRecent ? (
              <p className="muted" style={{ padding: "16px 0" }}>Loading campaigns…</p>
            ) : recentCases.length === 0 ? (
              <div className="case-state-banner">
                <strong>No recent campaigns available</strong>
                <p>Ingest events first, or generate a case from the Campaign Console so this screen has something to package.</p>
              </div>
            ) : (
              <div className="case-recent-list">
                {recentCases.map((c) => (
                  <div key={c.campaign_id} className="case-recent-row">
                    <div>
                      <strong>{c.primary_key || c.campaign_id}</strong>
                      <p className="muted">
                        {c.type} · score {Math.round(c.score * 100)} / 100 · {c.event_count} events · {c.status}
                      </p>
                      <p className="muted">{c.last_seen ? `${timeAgo(c.last_seen)} · ${fmtTs(c.last_seen)}` : "No last-seen time"}</p>
                    </div>
                    <button
                      className="ghost"
                      type="button"
                      disabled={generatingId === c.campaign_id}
                      onClick={() => handleGenerate(c.campaign_id)}
                    >
                      {generatingId === c.campaign_id ? "Generating…" : "Generate packet"}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    );
  }

  const graphNodes = packet.graph_summary?.node_count ?? packet.affected_entities.length;
  const graphEdges = packet.graph_summary?.edge_count ?? packet.evidence_paths.length;
  const evidenceRows = packet.evidence_timeline?.length ?? packet.evidence_paths.length;

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S5</p>
          <h2>Case Packet + STIX Export</h2>
          <p className="subtle">
            This is the handoff surface: it should show what happened, what is inside the packet, and whether export is defensible.
          </p>
        </div>
        <div className="chip-row">
          <button className="ghost" type="button" onClick={onExportJson}>
            <FileJson size={14} />&nbsp;Export JSON
          </button>
          <button className="ghost" type="button" onClick={onExportStix}>
            <Download size={14} />&nbsp;Export STIX 2.1
          </button>
        </div>
      </div>

      <div className="case-top-grid">
        <article className="panel case-kpi-card">
          <p className="workflow-stage-kicker">Confidence</p>
          <strong className="case-kpi-value">{formatConfidence(packet.confidence)}</strong>
          <span className="muted">current campaign confidence in this packet</span>
        </article>
        <article className="panel case-kpi-card">
          <p className="workflow-stage-kicker">Affected entities</p>
          <strong className="case-kpi-value">{packet.distinct_entities ?? packet.affected_entities.length}</strong>
          <span className="muted">entities included in the evidence bundle</span>
        </article>
        <article className="panel case-kpi-card">
          <p className="workflow-stage-kicker">Evidence rows</p>
          <strong className="case-kpi-value">{evidenceRows}</strong>
          <span className="muted">event rows currently captured in the packet</span>
        </article>
        <article className="panel case-kpi-card">
          <p className="workflow-stage-kicker">Graph structure</p>
          <strong className="case-kpi-value">{graphNodes}/{graphEdges}</strong>
          <span className="muted">graph nodes / graph edges in the packet snapshot</span>
        </article>
      </div>

      <div className="workflow-summary-banner">
        <div>
          <strong>Packet {packet.id}</strong>
          <span className="muted">
            Generated {fmtTs(packet.generated_at)} · {packet.campaign_type || "campaign"} · {packet.campaign_status || "unknown status"}
          </span>
        </div>
        <div>
          <strong>Integrity</strong>
          <span className="muted">{packet.integrity_hash ? `Hash present · ${shortHash(packet.integrity_hash)}` : "No integrity marker attached"}</span>
        </div>
        <div>
          <strong>Stage</strong>
          <span className="muted">{packet.stage ?? "not classified"}</span>
        </div>
      </div>

      <div className="grid-two case-console-grid">
        <div className="panel workflow-stage-panel">
          <div className="panel-header">
            <h3>Executive summary</h3>
            <span className="muted">{packet.campaignId}</span>
          </div>
          <p>{packet.summary}</p>
          <div className="detail-grid">
            <div>
              <p className="label">Campaign type</p>
              <p className="stat">{packet.campaign_type || "—"}</p>
            </div>
            <div>
              <p className="label">Primary key</p>
              <p className="mono">{packet.campaign_primary_key || packet.campaignId}</p>
            </div>
            <div>
              <p className="label">Event count</p>
              <p className="stat">{packet.event_count ?? packet.evidence_paths.length}</p>
            </div>
            <div>
              <p className="label">Severity</p>
              <p className="stat">{packet.severity}</p>
            </div>
          </div>

          <div className="panel-subsection">
            <p className="label">Included entities</p>
            <div className="case-chip-list">
              {(packet.entity_details ?? []).slice(0, 16).map((entity) => (
                <span key={`${entity.entity_key}:${entity.role ?? ""}`} className="chip mono">
                  {humanEntity(entity.entity_key)}
                  {entity.role ? ` · ${entity.role}` : ""}
                </span>
              ))}
              {packet.entity_details && packet.entity_details.length === 0 && (
                packet.affected_entities.map((entity) => (
                  <span key={entity} className="chip mono">{humanEntity(entity)}</span>
                ))
              )}
            </div>
          </div>
        </div>

        <div className="panel workflow-stage-panel">
          <div className="panel-header">
            <h3>Export readiness</h3>
            <span className="muted">Read before handoff</span>
          </div>
          <div className="case-readiness-list">
            <div className="case-readiness-item">
              <ShieldCheck size={16} color="var(--accent)" />
              <div>
                <strong>Integrity marker</strong>
                <p className="muted">{packet.integrity_hash ? "The packet already includes an integrity hash." : "No integrity marker attached yet."}</p>
              </div>
            </div>
            <div className="case-readiness-item">
              <Network size={16} color="var(--accent)" />
              <div>
                <strong>Graph coverage</strong>
                <p className="muted">{graphNodes > 0 ? `${graphNodes} nodes and ${graphEdges} edges are represented in the packet graph.` : "No graph structure is attached yet."}</p>
              </div>
            </div>
            <div className="case-readiness-item">
              <RefreshCw size={16} color="var(--warning)" />
              <div>
                <strong>Analyst caution</strong>
                <p className="muted">Export only after the evidence timeline and recommended actions read clearly enough for someone outside this UI.</p>
              </div>
            </div>
          </div>

          <div className="panel-subsection">
            <h4>Recommended actions</h4>
            <div className="action-grid">
              {packet.recommended_actions.map((group) => (
                <div key={group.stakeholder} className="action-card">
                  <h4>{group.stakeholder}</h4>
                  <ul>
                    {group.actions.map((action) => (
                      <li key={action}>{action}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="grid-two case-console-grid">
        <div className="panel workflow-stage-panel">
          <div className="panel-header">
            <h3>Evidence timeline</h3>
            <span className="muted">{evidenceRows} evidence rows</span>
          </div>
          {(packet.evidence_timeline ?? []).length === 0 ? (
            <div className="case-state-banner">
              <strong>No evidence timeline rows attached</strong>
              <p>The packet still has hash references, but the detailed timeline rows are thin. That is a backend evidence-materialization issue, not an export failure.</p>
            </div>
          ) : (
            <div className="case-recent-list">
              {(packet.evidence_timeline ?? []).map((item) => (
                <div key={item.event_hash} className="case-recent-row">
                  <div>
                    <strong className="mono">{shortHash(item.event_hash)}</strong>
                    <p className="muted">{fmtTs(item.occurred_at)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="panel-subsection">
            <h4>AI rationale</h4>
            <div className="factors">
              {packet.ai_rationale.map((item) => (
                <span key={item} className="factor">{item}</span>
              ))}
            </div>
          </div>
        </div>

        <div className="panel workflow-stage-panel">
          <div className="panel-header">
            <h3>Graph and evidence references</h3>
            <span className="muted">structural packet content</span>
          </div>
          <div className="detail-grid">
            <div>
              <p className="label">Graph nodes</p>
              <p className="stat">{graphNodes}</p>
            </div>
            <div>
              <p className="label">Graph edges</p>
              <p className="stat">{graphEdges}</p>
            </div>
          </div>
          <div className="list" style={{ marginTop: 12 }}>
            {packet.evidence_paths.slice(0, 12).map((path) => (
              <div key={path} className="list-item mono">
                {path}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
