import { LogOut } from "lucide-react";

import { agencyColor } from "../types/auth";
import type { Principal } from "../types/auth";
import type { Campaign, EntityProfile } from "../types/domain";
import { sourceLabel } from "./navigation";
import type { ScreenId } from "./navigation";

export default function Inspector({
  principal,
  central,
  selectedEntity,
  selectedCampaign,
  healthGnnLoaded,
  healthModelVersion,
  healthGnnMetrics,
  onNavigate,
  onLogout,
}: {
  principal: Principal;
  central: boolean;
  selectedEntity: EntityProfile | null;
  selectedCampaign?: Campaign;
  healthGnnLoaded: boolean;
  healthModelVersion: string | null;
  healthGnnMetrics: Record<string, unknown>;
  onNavigate: (id: ScreenId) => void;
  onLogout: () => void;
}) {
  return (
    <aside className="inspector">
      <div className="panel">
        <div className="panel-header">
          <h3>Entity Profile</h3>
          <span className="muted">Inspector</span>
        </div>
        {!selectedEntity ? (
          <p className="muted">No entity selected.</p>
        ) : (
          <div className="profile">
            <h4>{selectedEntity.label}</h4>
            <p className="muted">{selectedEntity.type}</p>
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
              View campaign
            </button>
          </>
        ) : (
          <p className="muted">No campaign selected.</p>
        )}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>GNN Status</h3>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 7, fontSize: "0.8rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="muted">Model loaded</span>
            <span style={{ color: healthGnnLoaded ? "var(--accent)" : "var(--danger)" }}>
              {healthGnnLoaded ? "✓ Yes" : "✗ No"}
            </span>
          </div>
          {healthModelVersion && (
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span className="muted">Version</span>
              <span className="mono" style={{ fontSize: "0.73rem" }}>
                {healthModelVersion}
              </span>
            </div>
          )}
          {healthGnnMetrics.auc != null && (
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span className="muted">AUC</span>
              <span style={{ color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>
                {Number(healthGnnMetrics.auc).toFixed(3)}
              </span>
            </div>
          )}
          <button className="ghost" type="button" style={{ marginTop: 4, fontSize: "0.73rem" }} onClick={() => onNavigate("gnn")}>
            GNN Intelligence →
          </button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Session</h3>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: "0.78rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="muted">User</span>
            <span className="mono" style={{ fontSize: "0.72rem" }}>
              {principal.username}
            </span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="muted">Agency</span>
            <span style={{ color: agencyColor(principal.section_code) }}>{principal.section_code ?? "CENTRAL"}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="muted">Role</span>
            <span>{principal.role}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="muted">Access</span>
            <span style={{ color: central ? "var(--accent)" : "var(--info)" }}>{principal.access_level}</span>
          </div>
          <button
            className="ghost"
            type="button"
            style={{ marginTop: 4, fontSize: "0.73rem", color: "var(--danger)", display: "flex", alignItems: "center", gap: 4 }}
            onClick={onLogout}
          >
            <LogOut size={11} /> Sign out
          </button>
        </div>
      </div>
    </aside>
  );
}
