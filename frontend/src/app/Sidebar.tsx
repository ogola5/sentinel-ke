import { useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, LogOut, RefreshCw, Settings } from "lucide-react";

import { agencyColor, agencyName, type Principal } from "../types/auth";
import {
  NAV_ADMIN,
  NAV_ANALYZE,
  NAV_ATTRIBUTE,
  NAV_COMMAND,
  NAV_GOVERN,
  NAV_RESPOND,
  NAV_SENSE,
  NavGroup,
  type ScreenId,
} from "./navigation";
import type { BackendStatus } from "./useDashboardSync";

export default function Sidebar({
  principal,
  activeScreen,
  auditorOnly,
  central,
  execute,
  manageUsers,
  collapsed,
  backendStatus,
  backendLabel,
  isSyncing,
  syncError,
  actionStatus,
  healthGnnLoaded,
  onNavigate,
  onToggleCollapse,
  onToggleConnectionPanel,
  onTriggerSync,
  onLogout,
}: {
  principal: Principal;
  activeScreen: ScreenId;
  auditorOnly: boolean;
  central: boolean;
  execute: boolean;
  manageUsers: boolean;
  collapsed: boolean;
  backendStatus: BackendStatus;
  backendLabel: string;
  isSyncing: boolean;
  syncError: string;
  actionStatus: string;
  healthGnnLoaded: boolean;
  onNavigate: (id: ScreenId) => void;
  onToggleCollapse: () => void;
  onToggleConnectionPanel: () => void;
  onTriggerSync: () => void;
  onLogout: () => void;
}) {
  const [adminOpen, setAdminOpen] = useState(false);
  const statusDotClass = backendStatus === "connected" ? "live" : backendStatus === "degraded" ? "degraded" : "offline";
  const color = agencyColor(principal.section_code);

  // Filter admin items by role so unauthorised entries don't appear
  const adminItems = NAV_ADMIN.filter((item) => {
    if (item.id === "exec" || item.id === "onboard" || item.id === "users") return central || manageUsers;
    return true;
  });

  return (
    <aside className={collapsed ? "nav nav-collapsed" : "nav"}>
      {/* Collapse toggle */}
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
          <h1 className="nav-title">National SOC</h1>

          {/* Agency badge — dynamic border/bg from agencyColor */}
          <div
            className="nav-agency-badge"
            style={{ border: `1px solid ${color}40`, background: `${color}12` }}
          >
            <span className="nav-agency-code" style={{ color }}>{principal.section_code ?? "CENTRAL"}</span>
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
              {backendStatus === "connected" ? "● Live" : backendStatus === "degraded" ? "◐ Degraded" : "○ Offline"}
            </span>
            {healthGnnLoaded && (
              <span className="status-badge status-badge-sm status-badge-gnn">GNN ✓</span>
            )}
            <span
              className="status-badge status-badge-sm"
              style={{ background: `${color}18`, color, border: `1px solid ${color}30` }}
            >
              {principal.role}
            </span>
          </div>
        </div>
      )}

      <nav className="nav-list">
        {!auditorOnly && (
          <NavGroup label="SENSE" color="var(--info)" items={NAV_SENSE} active={activeScreen}
            collapsed={collapsed} onSelect={(id) => onNavigate(id as ScreenId)} />
        )}
        {!auditorOnly && (
          <NavGroup label="ANALYZE" color="var(--accent)" items={NAV_ANALYZE} active={activeScreen}
            collapsed={collapsed} onSelect={(id) => onNavigate(id as ScreenId)} />
        )}
        {!auditorOnly && (
          <NavGroup label="ATTRIBUTE" color="var(--warning)" items={NAV_ATTRIBUTE} active={activeScreen}
            collapsed={collapsed} onSelect={(id) => onNavigate(id as ScreenId)} />
        )}
        {!auditorOnly && execute && (
          <NavGroup label="RESPOND" color="var(--risk-critical)" items={NAV_RESPOND} active={activeScreen}
            collapsed={collapsed} onSelect={(id) => onNavigate(id as ScreenId)} />
        )}
        {!auditorOnly && !execute && (
          <NavGroup label="RESPOND" color="var(--risk-critical)" items={[NAV_RESPOND[0]]} active={activeScreen}
            collapsed={collapsed} onSelect={(id) => onNavigate(id as ScreenId)} />
        )}
        <NavGroup label="GOVERN" color="var(--risk-low)" items={NAV_GOVERN} active={activeScreen}
          collapsed={collapsed} onSelect={(id) => onNavigate(id as ScreenId)} />
        {central && (
          <NavGroup label="COMMAND" color="var(--command)" items={NAV_COMMAND} active={activeScreen}
            collapsed={collapsed} onSelect={(id) => onNavigate(id as ScreenId)} />
        )}

        {/* ── System drawer ─────────────────────────────────────────────── */}
        <div className="nav-group">
          <button
            className="nav-admin-toggle"
            type="button"
            onClick={() => setAdminOpen((o) => !o)}
            title="System tools"
          >
            <Settings size={12} style={{ opacity: 0.5 }} />
            {!collapsed && (
              <>
                <span className="nav-group-label nav-group-label-grow">SYSTEM</span>
                {adminOpen ? <ChevronUp size={10} style={{ opacity: 0.4 }} /> : <ChevronDown size={10} style={{ opacity: 0.4 }} />}
              </>
            )}
          </button>
          {adminOpen && (
            <NavGroup label="" color="var(--muted)" items={adminItems} active={activeScreen}
              collapsed={collapsed} onSelect={(id) => onNavigate(id as ScreenId)} />
          )}
        </div>
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
