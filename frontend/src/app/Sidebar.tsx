import { ChevronLeft, ChevronRight, LogOut, RefreshCw, Settings } from "lucide-react";

import { agencyColor, agencyName, type Principal } from "../types/auth";
import type { BackendStatus } from "./useDashboardSync";
import type { WorkspaceId, WorkspaceItem } from "./navigation";

export default function Sidebar({
  principal,
  activeWorkspace,
  workspaces,
  collapsed,
  backendStatus,
  backendLabel,
  isSyncing,
  syncError,
  actionStatus,
  healthGnnLoaded,
  onSelectWorkspace,
  onToggleCollapse,
  onToggleConnectionPanel,
  onTriggerSync,
  onLogout,
}: {
  principal: Principal;
  activeWorkspace: WorkspaceId;
  workspaces: WorkspaceItem[];
  collapsed: boolean;
  backendStatus: BackendStatus;
  backendLabel: string;
  isSyncing: boolean;
  syncError: string;
  actionStatus: string;
  healthGnnLoaded: boolean;
  onSelectWorkspace: (workspaceId: WorkspaceId) => void;
  onToggleCollapse: () => void;
  onToggleConnectionPanel: () => void;
  onTriggerSync: () => void;
  onLogout: () => void;
}) {
  const statusDotClass = backendStatus === "connected" ? "live" : backendStatus === "degraded" ? "degraded" : "offline";
  const agencyTint = agencyColor(principal.section_code);

  return (
    <aside className={collapsed ? "nav nav-collapsed" : "nav"}>
      <button
        className="nav-collapse-btn"
        type="button"
        onClick={onToggleCollapse}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
      </button>

      {!collapsed && (
        <div className="nav-header">
          <p className="nav-wordmark">Sentinel-KE</p>
          <h1 className="nav-title">Mission Control</h1>

          <div
            className="nav-agency-badge"
            style={{ border: `1px solid ${agencyTint}40`, background: `${agencyTint}12` }}
          >
            <span className="nav-agency-code" style={{ color: agencyTint }}>{principal.section_code ?? "CENTRAL"}</span>
            <span className="nav-agency-sep">·</span>
            <span className="nav-agency-name">{principal.display_name ?? principal.username}</span>
          </div>

          <div className="nav-status-row">
            <span className={`status-dot ${statusDotClass}`} />
            <p className="nav-status-label">{isSyncing ? "Syncing…" : backendLabel}</p>
          </div>

          {syncError && <p className="nav-sync-error">{syncError}</p>}
          {actionStatus && <p className="nav-action-status">{actionStatus}</p>}

          <div className="nav-badges">
            <span className="status-badge status-badge-sm">
              {backendStatus === "connected" ? "Live" : backendStatus === "degraded" ? "Degraded" : "Offline"}
            </span>
            {healthGnnLoaded && (
              <span className="status-badge status-badge-sm status-badge-gnn">AI Ready</span>
            )}
          </div>
        </div>
      )}

      {!collapsed && <p className="nav-section-label">Workspaces</p>}

      <nav className="workspace-list" aria-label="Primary workspaces">
        {workspaces.map((workspace) => {
          const isActive = workspace.id === activeWorkspace;
          const { Icon } = workspace;
          return (
            <button
              key={workspace.id}
              type="button"
              className={`workspace-item${isActive ? " active" : ""}${collapsed ? " workspace-item-collapsed" : ""}`}
              onClick={() => onSelectWorkspace(workspace.id)}
              title={`${workspace.label} · ${workspace.description}`}
            >
              <span className="workspace-icon-wrap" style={{ color: isActive ? workspace.color : undefined }}>
                <Icon size={16} />
              </span>
              {!collapsed && (
                <span className="workspace-copy">
                  <span className="workspace-label">{workspace.label}</span>
                  <span className="workspace-desc">{workspace.description}</span>
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="nav-footer">
        {!collapsed && (
          <>
            <div className="nav-footer-actions">
              <button className="nav-footer-btn" type="button" onClick={onToggleConnectionPanel} title="Credentials">
                <Settings size={11} />
                <span>Creds</span>
              </button>
              <button className="nav-footer-btn" type="button" onClick={onTriggerSync} title="Resync data">
                <RefreshCw size={11} />
                <span>Resync</span>
              </button>
              <button className="nav-footer-btn nav-footer-btn-danger" type="button" onClick={onLogout} title="Sign out">
                <LogOut size={11} />
                <span>Logout</span>
              </button>
            </div>
            <p className="nav-agency-full">{agencyName(principal.section_code)}</p>
          </>
        )}

        {collapsed && (
          <div className="nav-footer-icons">
            <button className="nav-footer-btn" type="button" onClick={onToggleConnectionPanel} title="Credentials">
              <Settings size={13} />
            </button>
            <button className="nav-footer-btn" type="button" onClick={onTriggerSync} title="Resync data">
              <RefreshCw size={13} />
            </button>
            <button className="nav-footer-btn nav-footer-btn-danger" type="button" onClick={onLogout} title="Sign out">
              <LogOut size={13} />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
