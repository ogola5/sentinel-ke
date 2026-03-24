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
          <p className="subtle">Choose one campaign, review it, then act.</p>
        </div>
        <div className="chip-row">
          <button className="ghost" type="button" onClick={onOpenGraph}>
            Open in Graph
          </button>
        </div>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>Campaigns</h3>
            <span className="muted">{campaigns.length} active</span>
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
            <h3>{selected.name}</h3>
            <span className={`risk-badge ${selected.severity.toLowerCase()}`}>{selected.severity}</span>
          </div>
          <div className="chip-row" style={{ marginBottom: 12 }}>
            <span className="chip">{selected.type}</span>
            <span className="chip">{selected.status}</span>
            <span className="chip mono">{selected.id}</span>
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
          <div className="chip-row">
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
          <details className="panel-subsection collapsible-panel">
            <summary>
              <span>Confidence history</span>
              <span className="muted">Open trend</span>
            </summary>
            <Sparkline data={selected.confidence_history} stroke="var(--accent)" />
          </details>
          <details className="panel-subsection collapsible-panel">
            <summary>
              <span>Entities and drivers</span>
              <span className="muted">Open detail</span>
            </summary>
            <div className="entity-roles">
              {selected.top_entities.map((entity) => (
                <div key={entity.label} className="entity-role">
                  <span>{entity.label}</span>
                  <span className="muted">{entity.role}</span>
                </div>
              ))}
            </div>
            <div className="factors" style={{ marginTop: 12 }}>
              {selected.factors.map((factor) => (
                <span key={factor} className="factor">
                  {factor}
                </span>
              ))}
            </div>
          </details>
        </div>
      </div>
    </section>
  );
}
