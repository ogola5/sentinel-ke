import type { CasePacket } from "../types/domain";
import { formatConfidence } from "../utils/formatters";

type CasePacketsProps = {
  packet?: CasePacket;
  onExportJson: () => void;
  onExportStix: () => void;
};

export default function CasePackets({ packet, onExportJson, onExportStix }: CasePacketsProps) {
  if (!packet) {
    return (
      <section className="screen">
        <div className="screen-header">
          <div>
            <p className="eyebrow">S5</p>
            <h2>Case Packet + STIX Export</h2>
            <p className="subtle">Generate operational outputs from a campaign.</p>
          </div>
        </div>
        <div className="panel" style={{ background: "rgba(var(--accent-rgb), 0.08)", borderColor: "rgba(var(--accent-rgb), 0.24)" }}>
          <div className="panel-header">
            <h3>How to use this page</h3>
            <span className="muted">Cases are generated after campaign review</span>
          </div>
          <div className="detail-grid">
            <div>
              <p className="label">Step 1</p>
              <p>Open the Campaigns page first and confirm the campaign is worth escalation.</p>
            </div>
            <div>
              <p className="label">Step 2</p>
              <p>Generate the case packet from that campaign.</p>
            </div>
            <div>
              <p className="label">Step 3</p>
              <p>Return here to inspect evidence paths and export JSON or STIX.</p>
            </div>
          </div>
        </div>
        <div className="panel">
          <p className="muted">No case packet generated yet.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S5</p>
          <h2>Case Packet + STIX Export</h2>
          <p className="subtle">Operational readiness, ready for tomorrow.</p>
        </div>
        <div className="chip-row">
          <button className="ghost" type="button" onClick={onExportJson}>
            Export JSON case packet
          </button>
          <button className="ghost" type="button" onClick={onExportStix}>
            Export STIX 2.1
          </button>
        </div>
      </div>

      <div className="panel" style={{ background: "rgba(var(--accent-rgb), 0.08)", borderColor: "rgba(var(--accent-rgb), 0.24)" }}>
        <div className="panel-header">
          <h3>How to use this page</h3>
          <span className="muted">Read, verify, then export</span>
        </div>
        <div className="detail-grid">
          <div>
            <p className="label">Step 1</p>
            <p>Read the executive summary first so the case objective is clear.</p>
          </div>
          <div>
            <p className="label">Step 2</p>
            <p>Check evidence paths and AI rationale before export.</p>
          </div>
          <div>
            <p className="label">Step 3</p>
            <p>Use recommended actions and only then export JSON or STIX.</p>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>1. Executive summary</h3>
          <span className="muted">{packet.id}</span>
        </div>
        <p>{packet.summary}</p>
        <div className="detail-grid">
          <div>
            <p className="label">Confidence</p>
            <p className="stat">{formatConfidence(packet.confidence)}</p>
          </div>
          <div>
            <p className="label">Severity</p>
            <p className="stat">{packet.severity}</p>
          </div>
          <div>
            <p className="label">Campaign</p>
            <p className="stat">{packet.campaignId}</p>
          </div>
          <div>
            <p className="label">Affected entities</p>
            <p className="stat">{packet.affected_entities.length}</p>
          </div>
        </div>
        <div className="panel-subsection">
          <h4>Affected entities (hashed)</h4>
          <div className="chip-row">
            {packet.affected_entities.map((entity) => (
              <span key={entity} className="chip mono">
                {entity}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>2. Evidence paths</h3>
            <span className="muted">Explainable chain</span>
          </div>
          <div className="list">
            {packet.evidence_paths.map((path) => (
              <div key={path} className="list-item mono">
                {path}
              </div>
            ))}
          </div>
          <svg className="mini-graph" viewBox="0 0 240 120" role="img">
            <line x1="30" y1="60" x2="90" y2="30" />
            <line x1="90" y1="30" x2="160" y2="60" />
            <line x1="90" y1="30" x2="90" y2="90" />
            <circle cx="30" cy="60" r="10" />
            <circle cx="90" cy="30" r="10" />
            <circle cx="160" cy="60" r="10" />
            <circle cx="90" cy="90" r="10" />
            <text x="30" y="80">Svc</text>
            <text x="90" y="20">Endpoint</text>
            <text x="160" y="80">ASN</text>
            <text x="90" y="110">Provider</text>
          </svg>
          <div className="panel-subsection">
            <h4>AI rationale</h4>
            <div className="factors">
              {packet.ai_rationale.map((item) => (
                <span key={item} className="factor">
                  {item}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>3. Recommended actions and export</h3>
            <span className="muted">Stakeholder-specific</span>
          </div>
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
    </section>
  );
}
