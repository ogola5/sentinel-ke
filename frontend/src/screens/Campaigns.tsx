import type { Campaign } from "../types/domain";
import { Sparkline } from "../components/Charts";
import { formatConfidence } from "../utils/formatters";

type CampaignsProps = {
  campaigns: Campaign[];
  selectedId: string;
  onSelect: (campaignId: string) => void;
  onOpenGraph: () => void;
  onGenerateCase: () => void;
  onOpenInfra: () => void;
  onOpenEvidence: () => void;
};

const severityClass = (severity: string) => {
  if (severity === "high") return "banner banner-high";
  if (severity === "medium") return "banner banner-medium";
  if (severity === "low") return "banner banner-low";
  return "banner";
};

export default function Campaigns({
  campaigns,
  selectedId,
  onSelect,
  onOpenGraph,
  onGenerateCase,
  onOpenInfra,
  onOpenEvidence,
}: CampaignsProps) {
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

  const selected = campaigns.find((campaign) => campaign.id === selectedId) ?? campaigns[0];

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S4</p>
          <h2>Campaign Console</h2>
          <p className="subtle">Coordinated operations with confidence growth.</p>
        </div>
        <div className="chip-row">
          <button className="ghost" type="button" onClick={onOpenGraph}>
            Open in Graph
          </button>
        </div>
      </div>

      <div className="panel" style={{ background: "rgba(var(--warning-rgb), 0.08)", borderColor: "rgba(var(--warning-rgb), 0.26)" }}>
        <div className="panel-header">
          <h3>How to use this page</h3>
          <span className="muted">Campaigns are for coordinated activity, not single alerts</span>
        </div>
        <div className="detail-grid">
          <div>
            <p className="label">Step 1</p>
            <p>Choose one campaign from the left and read its confidence and severity first.</p>
          </div>
          <div>
            <p className="label">Step 2</p>
            <p>Review top entities, factors, and history before deciding to escalate.</p>
          </div>
          <div>
            <p className="label">Step 3</p>
            <p>Open graph or evidence for deeper review, then generate a case only when justified.</p>
          </div>
        </div>
      </div>

      <div className={severityClass(selected.severity)}>
        <strong>{selected.severity.toUpperCase()} severity</strong>
        <span>{selected.name} / {selected.type} / {selected.status}</span>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>1. Choose Campaign</h3>
            <span className="muted">Operational objects</span>
          </div>
          <div className="campaign-list">
            {campaigns.map((campaign) => (
              <button
                key={campaign.id}
                className={
                  campaign.id === selected.id ? "campaign-card active" : "campaign-card"
                }
                type="button"
                onClick={() => onSelect(campaign.id)}
              >
                <div>
                  <p className="label">{campaign.name}</p>
                  <p className="muted">{campaign.type} / {campaign.status}</p>
                </div>
                <div className="stat">{formatConfidence(campaign.confidence)}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>2. Review Campaign</h3>
            <span className="muted">{selected.id}</span>
          </div>
          <div className="list-item" style={{ marginBottom: 12 }}>
            <strong>{selected.name}</strong>
            <p className="muted" style={{ marginTop: 4 }}>
              Read this summary first, then use the sections below to decide whether this campaign is ready for graph pivoting or case generation.
            </p>
          </div>
          <div className="detail-grid">
            <div>
              <p className="label">Confidence</p>
              <p className="stat">{formatConfidence(selected.confidence)}</p>
            </div>
            <div>
              <p className="label">Status</p>
              <p className="stat">{selected.status}</p>
            </div>
            <div>
              <p className="label">Window</p>
              <p className="stat">{selected.first_seen} - {selected.last_seen}</p>
            </div>
            <div>
              <p className="label">Severity</p>
              <p className="stat">{selected.severity}</p>
            </div>
          </div>
          <div className="panel-subsection">
            <h4>Confidence history</h4>
            <Sparkline data={selected.confidence_history} stroke="var(--accent)" />
          </div>
          <div className="panel-subsection">
            <h4>Top entities & roles</h4>
            <div className="entity-roles">
              {selected.top_entities.map((entity) => (
                <div key={entity.label} className="entity-role">
                  <span>{entity.label}</span>
                  <span className="muted">{entity.role}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="panel-subsection">
            <h4>AI confidence drivers</h4>
            <div className="factors">
              {selected.factors.map((factor) => (
                <span key={factor} className="factor">
                  {factor}
                </span>
              ))}
            </div>
          </div>
          <div className="chip-row">
            <button className="ghost" type="button" onClick={onOpenInfra}>
              View Infra Clusters
            </button>
            <button className="ghost" type="button" onClick={onOpenEvidence}>
              Evidence references
            </button>
            <button className="ghost" type="button" onClick={onGenerateCase}>
              3. Generate Case Packet
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
