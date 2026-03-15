import { Flag, Search, ShieldCheck, X } from "lucide-react";

import { agencyColor } from "../types/auth";
import type { Principal } from "../types/auth";
import type { Campaign, EntityProfile } from "../types/domain";
import { sourceLabel } from "./navigation";
import type { ScreenId } from "./navigation";

export default function Inspector({
  principal,
  selectedEntity,
  selectedCampaign,
  onNavigate,
  onClose,
}: {
  principal: Principal;
  selectedEntity: EntityProfile | null;
  selectedCampaign?: Campaign;
  onNavigate: (id: ScreenId) => void;
  onClose: () => void;
}) {
  const sourcePreview = selectedEntity?.sources.slice(0, 3).map(sourceLabel).join(" · ");

  return (
    <aside className="inspector">
      <div className="inspector-close-row">
        <span className="label" style={{ fontSize: "0.68rem" }}>Inspector</span>
        <button className="ghost icon-btn" type="button" onClick={onClose} title="Close inspector">
          <X size={13} />
        </button>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Quick context</h3>
          <span className="muted" style={{ fontSize: "0.73rem" }}>Secondary surface</span>
        </div>
        {!selectedEntity ? (
          <div className="inspector-callout">
            <p className="workflow-stage-kicker">How to use this panel</p>
            <p className="workflow-stage-copy">
              Keep this panel for quick context only. When an entity matters, move to the full investigation screen for
              evidence, reports, and action.
            </p>
            <div className="panel-subsection">
              <strong>Best flow</strong>
              <ul className="inspector-compact-list">
                <li>Select one entity from any screen.</li>
                <li>Check the quick risk and linked campaign.</li>
                <li>Open the full investigation when you need to decide or export.</li>
              </ul>
            </div>
          </div>
        ) : (
          <div className="profile">
            <div className="inspector-entity-head">
              <div>
                <p className="workflow-stage-kicker">Selected entity</p>
                <h4>{selectedEntity.label}</h4>
                <p className="muted" style={{ fontSize: "0.8rem" }}>
                  {selectedEntity.type} · {selectedEntity.sources.length} source
                  {selectedEntity.sources.length === 1 ? "" : "s"}
                </p>
              </div>
              <span className={`risk-badge ${selectedEntity.risk}`}>{selectedEntity.risk}</span>
            </div>
            <div className="detail-grid">
              <div>
                <p className="label">First seen</p>
                <p className="stat">{selectedEntity.first_seen}</p>
              </div>
              <div>
                <p className="label">Last seen</p>
                <p className="stat">{selectedEntity.last_seen}</p>
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <p className="label">Source coverage</p>
                <p className="stat">{sourcePreview || "—"}</p>
              </div>
            </div>
            {selectedEntity.notes.length > 0 && (
              <details className="collapsible-panel" open={selectedEntity.notes.length <= 2}>
                <summary>
                  Why it stands out
                  <span className="muted">{selectedEntity.notes.length} note{selectedEntity.notes.length === 1 ? "" : "s"}</span>
                </summary>
                <ul className="inspector-compact-list">
                  {selectedEntity.notes.map((note) => <li key={note}>{note}</li>)}
                </ul>
              </details>
            )}
            <div className="inspector-actions">
              <button className="ghost" type="button" onClick={() => onNavigate("investigate")}>
                <Search size={14} />
                Open full investigation
              </button>
              {selectedCampaign && (
                <button className="ghost" type="button" onClick={() => onNavigate("campaigns")}>
                  <Flag size={14} />
                  Open linked campaign
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Linked campaign</h3>
          <span className="muted">{selectedCampaign?.id?.slice(0, 8) ?? "None"}</span>
        </div>
        {selectedCampaign ? (
          <>
            <p style={{ fontWeight: 600 }}>{selectedCampaign.name}</p>
            <p className="muted" style={{ fontSize: "0.8rem", marginTop: 4 }}>
              {selectedCampaign.type} · {selectedCampaign.status}
            </p>
            <p className="workflow-stage-copy" style={{ marginTop: 10 }}>
              Use the campaign workspace when you need the full network story, entity roster, and case packet.
            </p>
            <button className="ghost" type="button" style={{ marginTop: 10 }} onClick={() => onNavigate("campaigns")}>
              <Flag size={14} />
              View campaign
            </button>
          </>
        ) : (
          <p className="muted" style={{ fontSize: "0.82rem" }}>
            No linked campaign is selected yet. Investigation will still show entity-level evidence and reasoning.
          </p>
        )}
      </div>

      <div className="panel inspector-user-card">
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <ShieldCheck size={14} color="var(--accent)" />
          <strong style={{ fontSize: "0.82rem" }}>Current operator</strong>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem" }}>
          <span className="muted">Agency</span>
          <span style={{ color: agencyColor(principal.section_code) }}>{principal.section_code ?? "CENTRAL"}</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem", marginTop: 6 }}>
          <span className="muted">Role</span>
          <span>{principal.role}</span>
        </div>
        <p className="muted" style={{ marginTop: 10, fontSize: "0.76rem", lineHeight: 1.5 }}>
          This panel is for orientation only. Use the main workspace to investigate, label, respond, or export.
        </p>
      </div>
    </aside>
  );
}
