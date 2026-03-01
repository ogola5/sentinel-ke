import { useEffect, useMemo, useState } from "react";
import "../App.css";

// ── Auth ──────────────────────────────────────────────────────────────────────
import LoginScreen from "../screens/auth/LoginScreen";
import { loadPrincipal, clearSession, getRefreshToken, apiLogout } from "../api/auth";
import { agencyName, agencyColor, canExecute, canManageUsers, isCentral, isAuditorOnly } from "../types/auth";
import type { Principal } from "../types/auth";

// ── Existing screens ──────────────────────────────────────────────────────────
import LiveFeed from "../screens/LiveFeed";
import Timeline from "../screens/Timeline";
import GraphExplorer from "../screens/GraphExplorer";
import Campaigns from "../screens/Campaigns";
import InfraCorrelation from "../screens/InfraCorrelation";
import CasePackets from "../screens/CasePackets";
import OperationsCenter from "../screens/OperationsCenter";

// ── New screens ───────────────────────────────────────────────────────────────
import GNNIntelligence from "../screens/analyze/GNNIntelligence";
import CryptoPosture from "../screens/analyze/CryptoPosture";
import DefenseCenter from "../screens/respond/DefenseCenter";
import FederationDashboard from "../screens/govern/FederationDashboard";
import CorruptionIntel from "../screens/govern/CorruptionIntel";
import AuditLog from "../screens/govern/AuditLog";
import CentralCommand from "../screens/command/CentralCommand";
import ExecBrief from "../screens/command/ExecBrief";
import UserManagement from "../screens/admin/UserManagement";
import AgencyOnboarding from "../screens/admin/AgencyOnboarding";

// ── API ───────────────────────────────────────────────────────────────────────
import {
  createCasePacketFromCampaign,
  fetchBackendSnapshot,
  fetchCampaignEvidenceForDrawer,
} from "../api/backend";
import { emptyOperationsSnapshot, fetchOperationsSnapshot, runLeakageDetection } from "../api/operations";
import { endpoints } from "../api/endpoints";
import {
  apiFetchJson,
  loadClientCredentials,
  saveClientCredentials,
  type ClientCredentials,
} from "../api/client";

// ── Types ─────────────────────────────────────────────────────────────────────
import type {
  Campaign, CasePacket, EntityProfile, EvidenceItem,
  EventRecord, GraphData, GraphEdge, GraphNode,
  InfraCluster, ServiceIndicator, SourceType, TimelinePoint,
} from "../types/domain";
import type { OperationsSnapshot } from "../types/operations";

// ── Icons ─────────────────────────────────────────────────────────────────────
import {
  Radio, Activity, Network, Flag, Server,
  FileText, BarChart2, Brain, Lock, Shield,
  Globe, Building2, BookOpen, RefreshCw, Settings,
  LogOut, Users, Cpu, Zap, AlertTriangle,
} from "lucide-react";

// ── Nav definition ────────────────────────────────────────────────────────────
const NAV_SENSE = [
  { id: "live",       label: "National Live Feed",  Icon: Radio,    tag: "S1" },
  { id: "timeline",   label: "Service Indicators",  Icon: Activity, tag: "S2" },
] as const;

const NAV_ANALYZE = [
  { id: "graph",  label: "Threat Graph",     Icon: Network, tag: "S3" },
  { id: "gnn",    label: "GNN Intelligence", Icon: Brain,   tag: "S8" },
  { id: "crypto", label: "Crypto Posture",   Icon: Lock,    tag: "S9" },
] as const;

const NAV_ATTRIBUTE = [
  { id: "campaigns", label: "Campaign Console",  Icon: Flag,   tag: "S4" },
  { id: "infra",     label: "Infra Correlation", Icon: Server, tag: "S5" },
] as const;

const NAV_RESPOND = [
  { id: "cases",   label: "Case Packets + STIX", Icon: FileText, tag: "S6" },
  { id: "defense", label: "Defense Center",      Icon: Shield,   tag: "S10" },
] as const;

const NAV_GOVERN = [
  { id: "ops",        label: "Operations Center",  Icon: BarChart2, tag: "S7"  },
  { id: "corruption", label: "Corruption Intel",   Icon: Building2, tag: "S11" },
  { id: "federation", label: "Federation Network", Icon: Globe,     tag: "S12" },
  { id: "audit",      label: "Audit Log",          Icon: BookOpen,  tag: "S13" },
] as const;

const NAV_COMMAND = [
  { id: "exec",      label: "Crisis Brief",        Icon: AlertTriangle, tag: "C0" },
  { id: "command",   label: "National Command",    Icon: Cpu,           tag: "C1" },
  { id: "onboard",   label: "Agency Onboarding",   Icon: Zap,           tag: "C2" },
  { id: "users",     label: "User Management",     Icon: Users,         tag: "C3" },
] as const;

type ScreenId =
  | (typeof NAV_SENSE)[number]["id"]
  | (typeof NAV_ANALYZE)[number]["id"]
  | (typeof NAV_ATTRIBUTE)[number]["id"]
  | (typeof NAV_RESPOND)[number]["id"]
  | (typeof NAV_GOVERN)[number]["id"]
  | (typeof NAV_COMMAND)[number]["id"]
  | "onboard";

const TIME_WINDOWS = [
  { id: "10m", label: "10m" },
  { id: "1h",  label: "1h"  },
  { id: "24h", label: "24h" },
  { id: "30d", label: "30d" },
] as const;

const SOURCE_OPTIONS: SourceType[] = ["telco", "bank", "gov", "osint", "infra"];
const sourceLabel = (s: SourceType) => s.toUpperCase();
const emptyGraph: GraphData = { nodes: [], edges: [] };
type EvidenceState = { open: boolean; title: string; items: EvidenceItem[] };

// ── Nav group renderer helper ─────────────────────────────────────────────────
type NavItem = { id: string; label: string; Icon: React.ComponentType<{ size: number; style?: React.CSSProperties; color?: string }>; tag: string };
function NavGroup({
  label, color, items, active, onSelect,
}: {
  label: string; color: string; items: readonly NavItem[];
  active: string; onSelect: (id: string) => void;
}) {
  return (
    <div className="nav-group">
      <div className="nav-group-label" style={{ color }}>{label}</div>
      {items.map((item) => {
        const { Icon } = item;
        const isActive = active === item.id;
        return (
          <button
            key={item.id}
            className={`nav-item ${isActive ? "active" : ""}`}
            type="button"
            onClick={() => onSelect(item.id)}
          >
            <Icon size={14} style={{ opacity: isActive ? 1 : 0.55 }} color={isActive ? color : undefined} />
            <span style={{ fontSize: "0.86rem" }}>{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  // ── Auth state ────────────────────────────────────────────────────────────
  const [principal, setPrincipal] = useState<Principal | null>(() => loadPrincipal());

  const handleLogin = (p: Principal) => {
    setPrincipal(p);
    // Default screen: central users → command, section users → live
    setActiveScreen(p.access_level === "central" ? "exec" : "live");
  };

  const handleLogout = async () => {
    const rt = getRefreshToken();
    if (rt) await apiLogout(rt).catch(() => undefined);
    clearSession();
    setPrincipal(null);
    setActiveScreen("live");
  };

  // If no principal, show login screen
  if (!principal) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  return <AuthenticatedApp principal={principal} onLogout={() => void handleLogout()} />;
}

// ── Authenticated shell ───────────────────────────────────────────────────────
function AuthenticatedApp({
  principal,
  onLogout,
}: {
  principal: Principal;
  onLogout: () => void;
}) {
  const central  = isCentral(principal);
  const execute  = canExecute(principal);
  const manageUs = canManageUsers(principal);
  const auditorOnly = isAuditorOnly(principal);

  // ── Connection state ────────────────────────────────────────────────────
  const [backendStatus, setBackendStatus] = useState<"connected" | "degraded" | "offline">("offline");
  const [backendLabel, setBackendLabel]   = useState("Waiting for sync…");
  const [syncError, setSyncError]         = useState("");
  const [actionStatus, setActionStatus]   = useState("");
  const [isSyncing, setIsSyncing]         = useState(false);
  const [syncNonce, setSyncNonce]         = useState(0);

  // ── GNN health ─────────────────────────────────────────────────────────
  const [healthGnnLoaded, setHealthGnnLoaded]       = useState(false);
  const [healthModelVersion, setHealthModelVersion] = useState<string | null>(null);
  const [healthGnnMetrics, setHealthGnnMetrics]     = useState<Record<string, unknown>>({});

  // ── Domain data ─────────────────────────────────────────────────────────
  const [eventsData, setEventsData]               = useState<EventRecord[]>([]);
  const [timelineData, setTimelineData]           = useState<TimelinePoint[]>([]);
  const [indicatorsData, setIndicatorsData]       = useState<ServiceIndicator[]>([]);
  const [campaignsData, setCampaignsData]         = useState<Campaign[]>([]);
  const [infraClustersData, setInfraClustersData] = useState<InfraCluster[]>([]);
  const [entitiesData, setEntitiesData]           = useState<EntityProfile[]>([]);
  const [graphData, setGraphData]                 = useState<GraphData>(emptyGraph);
  const [casesData, setCasesData]                 = useState<CasePacket[]>([]);
  const [operationsData, setOperationsData]       = useState<OperationsSnapshot>(emptyOperationsSnapshot);
  const [leakageActionLabel, setLeakageActionLabel] = useState("Run leakage detector");

  // ── UI state ────────────────────────────────────────────────────────────
  const defaultScreen: ScreenId = central ? "command" : "live";
  const [activeScreen, setActiveScreen]     = useState<ScreenId>(defaultScreen);
  const [timeWindow, setTimeWindow]         = useState("1h");
  const [sourceFilters, setSourceFilters]   = useState<Record<SourceType, boolean>>(() =>
    SOURCE_OPTIONS.reduce((acc, s) => { acc[s] = true; return acc; }, {} as Record<SourceType, boolean>),
  );
  const [selectedEntity, setSelectedEntity]         = useState<EntityProfile | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [selectedClusterId, setSelectedClusterId]   = useState("");
  const [selectedServiceId, setSelectedServiceId]   = useState("");
  const [selectedCaseId, setSelectedCaseId]         = useState("");
  const [evidence, setEvidence]                     = useState<EvidenceState>({ open: false, title: "", items: [] });
  const [entityQuery, setEntityQuery]               = useState("");
  const [connectionPanelOpen, setConnectionPanelOpen] = useState(false);
  const [credentials, setCredentials]               = useState<ClientCredentials>(() => loadClientCredentials());

  // ── 30-second backend sync ──────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    const sync = async () => {
      setIsSyncing(true);
      setSyncError("");
      try {
        const [snapshot, ops, health] = await Promise.all([
          fetchBackendSnapshot(),
          fetchOperationsSnapshot(),
          apiFetchJson<Record<string, unknown>>(endpoints.health()),
        ]);
        if (cancelled) return;
        setEventsData(snapshot.events);
        setTimelineData(snapshot.timelineCounts);
        setIndicatorsData(snapshot.indicators);
        setCampaignsData(snapshot.campaigns);
        setInfraClustersData(snapshot.infraClusters);
        setEntitiesData(snapshot.entities);
        setGraphData(snapshot.graph);
        setOperationsData(ops);
        setHealthGnnLoaded(Boolean(health.gnn_loaded));
        setHealthModelVersion(typeof health.gnn_model_version === "string" ? health.gnn_model_version : null);
        setHealthGnnMetrics(
          health.gnn_metrics != null && typeof health.gnn_metrics === "object"
            ? (health.gnn_metrics as Record<string, unknown>)
            : {},
        );
        setBackendStatus(snapshot.mode === "live" ? "connected" : "degraded");
        const w = snapshot.warnings.length > 0 ? ` · ${snapshot.warnings.join(", ")}` : "";
        setBackendLabel(`${snapshot.connectionLabel}${w}`);
      } catch (err) {
        if (cancelled) return;
        setBackendStatus("offline");
        setBackendLabel("Backend unavailable");
        setSyncError(err instanceof Error ? err.message : "backend_unreachable");
      } finally {
        if (!cancelled) setIsSyncing(false);
      }
    };
    void sync();
    const timer = window.setInterval(() => void sync(), 30_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [syncNonce]);

  // ── Auto-select defaults ────────────────────────────────────────────────
  useEffect(() => {
    if (campaignsData.length && !campaignsData.find((c) => c.id === selectedCampaignId))
      setSelectedCampaignId(campaignsData[0].id);
  }, [campaignsData, selectedCampaignId]);
  useEffect(() => {
    if (infraClustersData.length && !infraClustersData.find((c) => c.id === selectedClusterId))
      setSelectedClusterId(infraClustersData[0].id);
  }, [infraClustersData, selectedClusterId]);
  useEffect(() => {
    if (indicatorsData.length && !indicatorsData.find((i) => i.serviceId === selectedServiceId))
      setSelectedServiceId(indicatorsData[0].serviceId);
  }, [indicatorsData, selectedServiceId]);
  useEffect(() => {
    if (entitiesData.length && (!selectedEntity || !entitiesData.find((e) => e.id === selectedEntity?.id)))
      setSelectedEntity(entitiesData[0]);
  }, [entitiesData, selectedEntity]);
  useEffect(() => {
    if (casesData.length && !casesData.find((c) => c.id === selectedCaseId))
      setSelectedCaseId(casesData[0].id);
  }, [casesData, selectedCaseId]);

  // ── Derived ─────────────────────────────────────────────────────────────
  const activeCase       = casesData.find((c) => c.id === selectedCaseId);
  const selectedCampaign = campaignsData.find((c) => c.id === selectedCampaignId);
  const timelineEvidenceRefs = useMemo(() =>
    Array.from(new Set(
      eventsData.filter((e) => e.service_id === selectedServiceId).map((e) => e.event_hash),
    )).slice(0, 12),
  [eventsData, selectedServiceId]);

  // ── Handlers ────────────────────────────────────────────────────────────
  const toggleSource  = (s: SourceType) => setSourceFilters((p) => ({ ...p, [s]: !p[s] }));
  const openEvidence  = (title: string, items: EvidenceItem[]) => setEvidence({ open: true, title, items });
  const closeEvidence = () => setEvidence({ open: false, title: "", items: [] });

  const handleSelectEvent = (event: EventRecord) => {
    setSelectedServiceId(event.service_id);
    const entity = entitiesData.find((e) =>
      e.label.toLowerCase().includes(event.service_id.toLowerCase()) ||
      e.label.toLowerCase().includes(event.endpoint.toLowerCase()),
    );
    if (entity) setSelectedEntity(entity);
  };

  const triggerBackendAction = async (path: string, method: "POST" | "GET" = "POST") => {
    setActionStatus(`${method} ${path}`);
    try {
      await apiFetchJson<Record<string, unknown>>(path, { method });
      setActionStatus(`done ${path}`);
    } catch (err) {
      setActionStatus(`failed: ${err instanceof Error ? err.message : "request_failed"}`);
    }
  };

  const handleGenerateCase = async () => {
    if (!selectedCampaignId) return;
    try {
      const packet = await createCasePacketFromCampaign(selectedCampaignId);
      setCasesData((prev) => [packet, ...prev.filter((c) => c.id !== packet.id)]);
      setSelectedCaseId(packet.id);
      setActiveScreen("cases");
    } catch (err) {
      setActionStatus(`case failed: ${err instanceof Error ? err.message : "request_failed"}`);
    }
  };

  const handleRunLeakage = async () => {
    setLeakageActionLabel("Scanning…");
    try {
      const summary = await runLeakageDetection(30);
      setOperationsData((prev) => ({ ...prev, leakageSummary: summary }));
      setLeakageActionLabel(`Done (${summary.totalAlerts} alerts)`);
    } catch {
      setLeakageActionLabel("Scan failed");
    }
  };

  const saveCredentialsAndResync = () => {
    setCredentials(saveClientCredentials(credentials));
    setConnectionPanelOpen(false);
    setSyncNonce((n) => n + 1);
  };

  const statusDotClass = backendStatus === "connected" ? "live" : backendStatus === "degraded" ? "degraded" : "offline";
  const nav = (id: string) => setActiveScreen(id as ScreenId);

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="app">

      {/* ── Sidebar ───────────────────────────────────────────────────── */}
      <aside className="nav">
        <div className="nav-header">
          <div>
            <p style={{ fontSize: "0.62rem", letterSpacing: "0.16em", opacity: 0.45, textTransform: "uppercase", margin: 0 }}>
              Sentinel-KE
            </p>
            <h1 style={{ fontSize: "1.05rem", marginTop: 2 }}>National SOC</h1>

            {/* Agency badge */}
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
            {actionStatus && <p className="muted" style={{ fontSize: "0.68rem", margin: "2px 0 0", opacity: 0.55 }}>{actionStatus}</p>}
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

        {/* Nav — role-gated */}
        <nav className="nav-list" style={{ gap: 2 }}>
          {!auditorOnly && (
            <NavGroup label="SENSE"     color="var(--info)"          items={NAV_SENSE}     active={activeScreen} onSelect={nav} />
          )}
          {!auditorOnly && (
            <NavGroup label="ANALYZE"   color="var(--accent)"        items={NAV_ANALYZE}   active={activeScreen} onSelect={nav} />
          )}
          {!auditorOnly && (
            <NavGroup label="ATTRIBUTE" color="var(--warning)"       items={NAV_ATTRIBUTE} active={activeScreen} onSelect={nav} />
          )}
          {!auditorOnly && execute && (
            <NavGroup label="RESPOND"   color="var(--risk-critical)"  items={NAV_RESPOND}   active={activeScreen} onSelect={nav} />
          )}
          {!auditorOnly && !execute && (
            /* Analyst: show cases read-only, hide defense */
            <NavGroup
              label="RESPOND"
              color="var(--risk-critical)"
              items={[NAV_RESPOND[0]]}
              active={activeScreen}
              onSelect={nav}
            />
          )}
          <NavGroup label="GOVERN" color="var(--risk-low)" items={NAV_GOVERN} active={activeScreen} onSelect={nav} />
          {central && (
            <NavGroup label="COMMAND" color="#c084fc" items={NAV_COMMAND} active={activeScreen} onSelect={nav} />
          )}
        </nav>

        {/* Footer */}
        <div className="nav-footer">
          <p className="label" style={{ fontSize: "0.65rem" }}>Time window</p>
          <div className="chip-row">
            {TIME_WINDOWS.map((w) => (
              <button key={w.id} className={timeWindow === w.id ? "chip active" : "chip ghost"} type="button" onClick={() => setTimeWindow(w.id)}>
                {w.label}
              </button>
            ))}
          </div>
          <div className="chip-row" style={{ marginTop: 8 }}>
            <button className="ghost" type="button" style={{ fontSize: "0.73rem", display: "flex", alignItems: "center", gap: 4 }} onClick={() => setConnectionPanelOpen((p) => !p)}>
              <Settings size={11} /> Creds
            </button>
            <button className="ghost" type="button" style={{ fontSize: "0.73rem", display: "flex", alignItems: "center", gap: 4 }} onClick={() => setSyncNonce((n) => n + 1)}>
              <RefreshCw size={11} /> Resync
            </button>
            <button className="ghost" type="button" style={{ fontSize: "0.73rem", display: "flex", alignItems: "center", gap: 4, color: "var(--danger)" }} onClick={onLogout}>
              <LogOut size={11} /> Logout
            </button>
          </div>
          <div style={{ marginTop: 8, fontSize: "0.65rem", opacity: 0.4, lineHeight: 1.5 }}>
            {agencyName(principal.section_code)}
          </div>
        </div>
      </aside>

      {/* ── Main ──────────────────────────────────────────────────────── */}
      <div className="main">
        <header className="topbar">
          <div className="topbar-group">
            <p className="label" style={{ fontSize: "0.65rem" }}>Source filter</p>
            <div className="chip-row">
              {SOURCE_OPTIONS.map((s) => (
                <button key={s} className={sourceFilters[s] ? "chip active" : "chip ghost"} type="button" onClick={() => toggleSource(s)}>
                  {sourceLabel(s)}
                </button>
              ))}
            </div>
          </div>
          <div className="topbar-group">
            <p className="label" style={{ fontSize: "0.65rem" }}>Entity search</p>
            <input
              className="search"
              list="entity-options"
              placeholder="Search entities…"
              value={entityQuery}
              onChange={(e) => {
                setEntityQuery(e.target.value);
                const entity = entitiesData.find((en) => en.label === e.target.value);
                if (entity) setSelectedEntity(entity);
              }}
            />
            <datalist id="entity-options">
              {entitiesData.map((e) => <option key={e.label} value={e.label} />)}
            </datalist>
          </div>
          <div className="topbar-group align-right" />
        </header>

        {/* Credentials panel */}
        {connectionPanelOpen && (
          <div className="panel connection-panel">
            <div className="panel-header">
              <h3>Client Credentials</h3>
              <span className="muted">Stored in localStorage</span>
            </div>
            <div className="grid-two">
              {(["apiKey", "accessToken", "legalGrantToken", "legalTarget"] as const).map((key) => (
                <label key={key}>
                  <p className="label">{key}</p>
                  <input className="search" value={credentials[key]} onChange={(e) => setCredentials((p) => ({ ...p, [key]: e.target.value }))} />
                </label>
              ))}
            </div>
            <div className="chip-row">
              <button className="ghost" onClick={saveCredentialsAndResync}>Save & Resync</button>
              <button className="ghost" onClick={() => {
                setCredentials(saveClientCredentials({ apiKey: "", accessToken: "", legalGrantToken: "", legalTarget: "" }));
                setSyncNonce((n) => n + 1);
              }}>Clear</button>
            </div>
          </div>
        )}

        <div className="content">
          <main className="primary">
            {/* COMMAND (central only) */}
            {activeScreen === "exec"    && central && <ExecBrief principal={principal} />}
            {activeScreen === "command" && central && (
              <CentralCommand
                operationsData={operationsData}
                activeCampaignCount={campaignsData.length}
                activeEventCount={eventsData.length}
                healthGnnLoaded={healthGnnLoaded}
                healthModelVersion={healthModelVersion}
                onNavigate={nav}
              />
            )}
            {activeScreen === "onboard"  && manageUs && <AgencyOnboarding />}
            {activeScreen === "users"    && manageUs && <UserManagement />}

            {/* SENSE */}
            {activeScreen === "live" && (
              <LiveFeed
                events={eventsData}
                timeline={timelineData}
                activeSources={sourceFilters}
                onSelectEvent={handleSelectEvent}
                onShowGraph={(e) => { handleSelectEvent(e); setActiveScreen("graph"); }}
                onShowTimeline={(e) => { setSelectedServiceId(e.service_id); setActiveScreen("timeline"); }}
                onShowEvidence={(title, e) => openEvidence(title, e.evidence)}
              />
            )}
            {activeScreen === "timeline" && (
              <Timeline
                indicators={indicatorsData}
                selectedService={selectedServiceId}
                evidenceRefs={timelineEvidenceRefs}
                onSelectService={setSelectedServiceId}
                onOpenCampaign={() => { if (campaignsData.length) setSelectedCampaignId(campaignsData[0].id); setActiveScreen("campaigns"); }}
                onShowInfra={() => { if (infraClustersData.length) setSelectedClusterId(infraClustersData[0].id); setActiveScreen("infra"); }}
              />
            )}

            {/* ANALYZE */}
            {activeScreen === "graph" && (
              <GraphExplorer
                graph={graphData}
                onSelectNode={(node: GraphNode) => {
                  const entity = entitiesData.find((e) => e.label.toLowerCase().includes(node.label.toLowerCase()));
                  if (entity) setSelectedEntity(entity);
                }}
                onSelectEdge={(edge: GraphEdge) =>
                  setEvidence({ open: true, title: `Edge: ${edge.source} → ${edge.target}`, items: edge.evidence })
                }
              />
            )}
            {activeScreen === "gnn" && (
              <GNNIntelligence
                healthGnnLoaded={healthGnnLoaded}
                healthModelVersion={healthModelVersion}
                healthGnnMetrics={healthGnnMetrics}
              />
            )}
            {activeScreen === "crypto" && <CryptoPosture />}

            {/* ATTRIBUTE */}
            {activeScreen === "campaigns" && (
              <Campaigns
                campaigns={campaignsData}
                selectedId={selectedCampaignId}
                onSelect={setSelectedCampaignId}
                onOpenGraph={() => setActiveScreen("graph")}
                onGenerateCase={handleGenerateCase}
                onOpenInfra={() => setActiveScreen("infra")}
                onOpenEvidence={async () => {
                  if (!selectedCampaignId) return;
                  try {
                    const items = await fetchCampaignEvidenceForDrawer(selectedCampaignId);
                    openEvidence(`Campaign evidence (${selectedCampaignId})`, items);
                  } catch { openEvidence("Campaign evidence", []); }
                }}
              />
            )}
            {activeScreen === "infra" && (
              <InfraCorrelation
                clusters={infraClustersData}
                selectedId={selectedClusterId}
                onSelect={setSelectedClusterId}
                onOpenGraph={() => setActiveScreen("graph")}
                onOpenEvidence={(cluster) => openEvidence(`Evidence: ${cluster.id}`, cluster.evidence)}
              />
            )}

            {/* RESPOND */}
            {activeScreen === "cases" && (
              <CasePackets
                packet={activeCase}
                onExportJson={() =>
                  selectedCampaignId ? triggerBackendAction(endpoints.caseFromCampaign(selectedCampaignId), "POST") : undefined
                }
                onExportStix={() =>
                  selectedCampaignId ? triggerBackendAction(endpoints.stixCaseByCampaign(selectedCampaignId), "GET") : undefined
                }
              />
            )}
            {activeScreen === "defense" && execute && <DefenseCenter />}

            {/* GOVERN */}
            {activeScreen === "ops" && (
              <OperationsCenter data={operationsData} onRunLeakage={handleRunLeakage} leakageActionLabel={leakageActionLabel} />
            )}
            {activeScreen === "corruption" && (
              <CorruptionIntel data={operationsData} onRunLeakage={handleRunLeakage} leakageActionLabel={leakageActionLabel} />
            )}
            {activeScreen === "federation" && <FederationDashboard />}
            {activeScreen === "audit"      && <AuditLog />}
          </main>

          {/* Right inspector */}
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
                      <p className="stat" style={{ color: selectedEntity.risk === "high" ? "var(--danger)" : selectedEntity.risk === "medium" ? "var(--warning)" : "var(--accent)" }}>
                        {selectedEntity.risk}
                      </p>
                    </div>
                    <div><p className="label">First seen</p><p className="stat">{selectedEntity.first_seen}</p></div>
                    <div><p className="label">Last seen</p><p className="stat">{selectedEntity.last_seen}</p></div>
                    <div><p className="label">Sources</p><p className="stat">{selectedEntity.sources.map(sourceLabel).join(" / ")}</p></div>
                  </div>
                  {selectedEntity.notes.length > 0 && (
                    <div className="panel-subsection">
                      <h4>Notes</h4>
                      <ul>{selectedEntity.notes.map((n) => <li key={n}>{n}</li>)}</ul>
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
                  <p className="muted" style={{ fontSize: "0.8rem" }}>{selectedCampaign.type} · {selectedCampaign.status}</p>
                  <button className="ghost" type="button" style={{ marginTop: 8 }} onClick={() => setActiveScreen("campaigns")}>View campaign</button>
                </>
              ) : (
                <p className="muted">No campaign selected.</p>
              )}
            </div>

            <div className="panel">
              <div className="panel-header"><h3>GNN Status</h3></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 7, fontSize: "0.8rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span className="muted">Model loaded</span>
                  <span style={{ color: healthGnnLoaded ? "var(--accent)" : "var(--danger)" }}>{healthGnnLoaded ? "✓ Yes" : "✗ No"}</span>
                </div>
                {healthModelVersion && (
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span className="muted">Version</span>
                    <span className="mono" style={{ fontSize: "0.73rem" }}>{healthModelVersion}</span>
                  </div>
                )}
                {healthGnnMetrics.auc != null && (
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span className="muted">AUC</span>
                    <span style={{ color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>{Number(healthGnnMetrics.auc).toFixed(3)}</span>
                  </div>
                )}
                <button className="ghost" type="button" style={{ marginTop: 4, fontSize: "0.73rem" }} onClick={() => setActiveScreen("gnn")}>GNN Intelligence →</button>
              </div>
            </div>

            {/* Session info */}
            <div className="panel">
              <div className="panel-header"><h3>Session</h3></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: "0.78rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span className="muted">User</span>
                  <span className="mono" style={{ fontSize: "0.72rem" }}>{principal.username}</span>
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
                <button className="ghost" type="button" style={{ marginTop: 4, fontSize: "0.73rem", color: "var(--danger)", display: "flex", alignItems: "center", gap: 4 }} onClick={onLogout}>
                  <LogOut size={11} /> Sign out
                </button>
              </div>
            </div>
          </aside>
        </div>
      </div>

      {/* ── Evidence drawer ──────────────────────────────────────────── */}
      <div className={evidence.open ? "evidence-drawer open" : "evidence-drawer"}>
        <div className="drawer-header">
          <div><p className="label">Evidence</p><h3>{evidence.title}</h3></div>
          <button className="ghost" type="button" onClick={closeEvidence}>Close ×</button>
        </div>
        <div className="drawer-content">
          {evidence.items.length === 0 ? (
            <p className="muted">No evidence loaded.</p>
          ) : (
            evidence.items.map((item) => (
              <div key={item.event_hash} className="evidence-item">
                <span className="mono">{item.event_hash}</span>
                <span className="chip">{sourceLabel(item.source)}</span>
                <span>{item.detail}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
