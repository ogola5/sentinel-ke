import { LogOut, RefreshCw, Settings } from "lucide-react";

import { agencyColor, agencyName, type Principal } from "../types/auth";
import {
  NAV_ANALYZE,
  NAV_ATTRIBUTE,
  NAV_COMMAND,
  NAV_GOVERN,
  NAV_RESPOND,
  NAV_SENSE,
  NavGroup,
  TIME_WINDOWS,
  type ScreenId,
} from "./navigation";
import type { BackendStatus } from "./useDashboardSync";

export default function Sidebar({
  principal,
  activeScreen,
  auditorOnly,
  central,
  execute,
  timeWindow,
  backendStatus,
  backendLabel,
  isSyncing,
  syncError,
  actionStatus,
  healthGnnLoaded,
  onNavigate,
  onSelectTimeWindow,
  onToggleConnectionPanel,
  onTriggerSync,
  onLogout,
}: {
  principal: Principal;
  activeScreen: ScreenId;
  auditorOnly: boolean;
  central: boolean;
  execute: boolean;
  timeWindow: string;
  backendStatus: BackendStatus;
  backendLabel: string;
  isSyncing: boolean;
  syncError: string;
  actionStatus: string;
  healthGnnLoaded: boolean;
  onNavigate: (id: ScreenId) => void;
  onSelectTimeWindow: (windowId: string) => void;
  onToggleConnectionPanel: () => void;
  onTriggerSync: () => void;
  onLogout: () => void;
}) {
  const statusDotClass = backendStatus === "connected" ? "live" : backendStatus === "degraded" ? "degraded" : "offline";

  return (
    <aside className="nav">
      <div className="nav-header">
        <div>
          <p style={{ fontSize: "0.62rem", letterSpacing: "0.16em", opacity: 0.45, textTransform: "uppercase", margin: 0 }}>
            Sentinel-KE
          </p>
          <h1 style={{ fontSize: "1.05rem", marginTop: 2 }}>National SOC</h1>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              marginTop: 6,
              padding: "2px 8px",
              borderRadius: 4,
              border: `1px solid ${agencyColor(principal.section_code)}40`,
              background: `${agencyColor(principal.section_code)}12`,
              fontSize: "0.68rem",
            }}
          >
            <span style={{ color: agencyColor(principal.section_code), fontFamily: "JetBrains Mono, monospace", fontWeight: 700 }}>
              {principal.section_code ?? "CENTRAL"}
            </span>
            <span style={{ opacity: 0.55 }}>·</span>
            <span style={{ opacity: 0.7 }}>{principal.display_name ?? principal.username}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8 }}>
            <span className={`status-dot ${statusDotClass}`} />
            <p className="muted" style={{ fontSize: "0.73rem" }}>
              {isSyncing ? "Syncing…" : backendLabel}
            </p>
          </div>
          {syncError && <p style={{ fontSize: "0.7rem", color: "var(--danger)", margin: "2px 0 0" }}>{syncError}</p>}
          {actionStatus && (
            <p className="muted" style={{ fontSize: "0.68rem", margin: "2px 0 0", opacity: 0.55 }}>
              {actionStatus}
            </p>
          )}
        </div>
        <div style={{ display: "flex", gap: 5, marginTop: 6, flexWrap: "wrap" }}>
          <span className="status-badge" style={{ fontSize: "0.63rem" }}>
            {backendStatus === "connected" ? "● Live" : backendStatus === "degraded" ? "◐ Degraded" : "○ Offline"}
          </span>
          {healthGnnLoaded && (
            <span className="status-badge" style={{ background: "rgba(49,255,144,.12)", color: "var(--accent)", fontSize: "0.63rem" }}>
              GNN ✓
            </span>
          )}
          <span
            className="status-badge"
            style={{
              background: `${agencyColor(principal.section_code)}18`,
              color: agencyColor(principal.section_code),
              fontSize: "0.63rem",
              border: `1px solid ${agencyColor(principal.section_code)}30`,
            }}
          >
            {principal.role}
          </span>
        </div>
      </div>

      <nav className="nav-list" style={{ gap: 2 }}>
        {!auditorOnly && (
          <NavGroup label="SENSE" color="var(--info)" items={NAV_SENSE} active={activeScreen} onSelect={(id) => onNavigate(id as ScreenId)} />
        )}
        {!auditorOnly && (
          <NavGroup
            label="ANALYZE"
            color="var(--accent)"
            items={NAV_ANALYZE}
            active={activeScreen}
            onSelect={(id) => onNavigate(id as ScreenId)}
          />
        )}
        {!auditorOnly && (
          <NavGroup
            label="ATTRIBUTE"
            color="var(--warning)"
            items={NAV_ATTRIBUTE}
            active={activeScreen}
            onSelect={(id) => onNavigate(id as ScreenId)}
          />
        )}
        {!auditorOnly && execute && (
          <NavGroup
            label="RESPOND"
            color="var(--risk-critical)"
            items={NAV_RESPOND}
            active={activeScreen}
            onSelect={(id) => onNavigate(id as ScreenId)}
          />
        )}
        {!auditorOnly && !execute && (
          <NavGroup
            label="RESPOND"
            color="var(--risk-critical)"
            items={[NAV_RESPOND[0]]}
            active={activeScreen}
            onSelect={(id) => onNavigate(id as ScreenId)}
          />
        )}
        <NavGroup
          label="GOVERN"
          color="var(--risk-low)"
          items={NAV_GOVERN}
          active={activeScreen}
          onSelect={(id) => onNavigate(id as ScreenId)}
        />
        {central && (
          <NavGroup
            label="COMMAND"
            color="var(--command)"
            items={NAV_COMMAND}
            active={activeScreen}
            onSelect={(id) => onNavigate(id as ScreenId)}
          />
        )}
      </nav>

      <div className="nav-footer">
        <p className="label" style={{ fontSize: "0.65rem" }}>
          Time window
        </p>
        <div className="chip-row">
          {TIME_WINDOWS.map((window) => (
            <button
              key={window.id}
              className={timeWindow === window.id ? "chip active" : "chip ghost"}
              type="button"
              onClick={() => onSelectTimeWindow(window.id)}
            >
              {window.label}
            </button>
          ))}
        </div>
        <div className="chip-row" style={{ marginTop: 8 }}>
          <button
            className="ghost"
            type="button"
            style={{ fontSize: "0.73rem", display: "flex", alignItems: "center", gap: 4 }}
            onClick={onToggleConnectionPanel}
          >
            <Settings size={11} /> Creds
          </button>
          <button
            className="ghost"
            type="button"
            style={{ fontSize: "0.73rem", display: "flex", alignItems: "center", gap: 4 }}
            onClick={onTriggerSync}
          >
            <RefreshCw size={11} /> Resync
          </button>
          <button
            className="ghost"
            type="button"
            style={{ fontSize: "0.73rem", display: "flex", alignItems: "center", gap: 4, color: "var(--danger)" }}
            onClick={onLogout}
          >
            <LogOut size={11} /> Logout
          </button>
        </div>
        <div style={{ marginTop: 8, fontSize: "0.65rem", opacity: 0.4, lineHeight: 1.5 }}>{agencyName(principal.section_code)}</div>
      </div>
    </aside>
  );
}
