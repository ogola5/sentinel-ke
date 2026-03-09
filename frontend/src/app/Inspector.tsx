import { X } from "lucide-react";

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
          <h3>Entity Profile</h3>
          <span className="muted" style={{ fontSize: "0.73rem" }}>
            {selectedEntity ? selectedEntity.type : "—"}
          </span>
        </div>
        {!selectedEntity ? (
          <p className="muted" style={{ fontSize: "0.82rem" }}>Select an entity from any screen to inspect it here.</p>
        ) : (
          <div className="profile">
            <h4>{selectedEntity.label}</h4>
            <div className="detail-grid">
              <div>
                <p className="label">Risk</p>
                <p
                  className="stat"
                  style={{
                    color:
                      selectedEntity.risk === "high"
                        ? "var(--danger)"
                        : selectedEntity.risk === "medium"
                          ? "var(--warning)"
                          : "var(--accent)",
                  }}
                >
                  {selectedEntity.risk}
                </p>
              </div>
              <div>
                <p className="label">First seen</p>
                <p className="stat">{selectedEntity.first_seen}</p>
              </div>
              <div>
                <p className="label">Last seen</p>
                <p className="stat">{selectedEntity.last_seen}</p>
              </div>
              <div>
                <p className="label">Sources</p>
                <p className="stat">{selectedEntity.sources.map(sourceLabel).join(" / ")}</p>
              </div>
            </div>
            {selectedEntity.notes.length > 0 && (
              <div className="panel-subsection">
                <h4>Notes</h4>
                <ul>{selectedEntity.notes.map((note) => <li key={note}>{note}</li>)}</ul>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Active Campaign</h3>
          <span className="muted">{selectedCampaign?.id?.slice(0, 8) ?? "—"}</span>
        </div>
        {selectedCampaign ? (
          <>
            <p className="label">{selectedCampaign.name}</p>
            <p className="muted" style={{ fontSize: "0.8rem" }}>
              {selectedCampaign.type} · {selectedCampaign.status}
            </p>
            <button className="ghost" type="button" style={{ marginTop: 8 }} onClick={() => onNavigate("campaigns")}>
              View campaign →
            </button>
          </>
        ) : (
          <p className="muted" style={{ fontSize: "0.82rem" }}>
            No active campaign selected.
          </p>
        )}
      </div>

      <div className="panel inspector-user-card">
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem" }}>
          <span className="muted">Agency</span>
          <span style={{ color: agencyColor(principal.section_code) }}>{principal.section_code ?? "CENTRAL"}</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem", marginTop: 6 }}>
          <span className="muted">Role</span>
          <span>{principal.role}</span>
        </div>
      </div>
    </aside>
  );
}
