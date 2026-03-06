import { useEffect, useMemo, useState } from "react";
import { LogOut, RefreshCw, Settings } from "lucide-react";

import "../App.css";

import LoginScreen from "../screens/auth/LoginScreen";
import { apiLogout, clearSession, getRefreshToken, loadPrincipal } from "../api/auth";
import { createCasePacketFromCampaign, fetchCampaignEvidenceForDrawer } from "../api/backend";
import {
  apiFetchJson,
  loadClientCredentials,
  saveClientCredentials,
  type ClientCredentials,
} from "../api/client";
import { endpoints } from "../api/endpoints";
import { runLeakageDetection } from "../api/operations";
import {
  agencyColor,
  agencyName,
  canExecute,
  canManageUsers,
  isAuditorOnly,
  isCentral,
  type Principal,
} from "../types/auth";
import type { CasePacket, EntityProfile, EvidenceItem, EventRecord, SourceType } from "../types/domain";

import ActiveScreen from "./ActiveScreen";
import CredentialsPanel from "./CredentialsPanel";
import EvidenceDrawer from "./EvidenceDrawer";
import Inspector from "./Inspector";
import {
  NAV_ANALYZE,
  NAV_ATTRIBUTE,
  NAV_COMMAND,
  NAV_GOVERN,
  NAV_RESPOND,
  NAV_SENSE,
  NavGroup,
  SOURCE_OPTIONS,
  TIME_WINDOWS,
  type ScreenId,
  sourceLabel,
} from "./navigation";
import { useDashboardSync } from "./useDashboardSync";

type EvidenceState = {
  open: boolean;
  title: string;
  items: EvidenceItem[];
};

export default function App() {
  const [principal, setPrincipal] = useState<Principal | null>(() => loadPrincipal());

  const handleLogout = async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      await apiLogout(refreshToken).catch(() => undefined);
    }
    clearSession();
    setPrincipal(null);
  };

  if (!principal) {
    return <LoginScreen onLogin={setPrincipal} />;
  }

  return <AuthenticatedApp principal={principal} onLogout={() => void handleLogout()} />;
}

function AuthenticatedApp({
  principal,
  onLogout,
}: {
  principal: Principal;
  onLogout: () => void;
}) {
  const central = isCentral(principal);
  const execute = canExecute(principal);
  const manageUsers = canManageUsers(principal);
  const auditorOnly = isAuditorOnly(principal);

  const {
    backendStatus,
    backendLabel,
    syncError,
    isSyncing,
    healthGnnLoaded,
    healthModelVersion,
    healthGnnMetrics,
    eventsData,
    timelineData,
    indicatorsData,
    campaignsData,
    infraClustersData,
    entitiesData,
    graphData,
    operationsData,
    setOperationsData,
    triggerSync,
  } = useDashboardSync();

  const [actionStatus, setActionStatus] = useState("");
  const [leakageActionLabel, setLeakageActionLabel] = useState("Run leakage detector");
  const [casesData, setCasesData] = useState<CasePacket[]>([]);

  const defaultScreen: ScreenId = central ? "command" : "live";
  const [activeScreen, setActiveScreen] = useState<ScreenId>(defaultScreen);
  const [timeWindow, setTimeWindow] = useState("1h");
  const [sourceFilters, setSourceFilters] = useState<Record<SourceType, boolean>>(() =>
    SOURCE_OPTIONS.reduce((acc, source) => {
      acc[source] = true;
      return acc;
    }, {} as Record<SourceType, boolean>),
  );
  const [selectedEntity, setSelectedEntity] = useState<EntityProfile | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [selectedClusterId, setSelectedClusterId] = useState("");
  const [selectedServiceId, setSelectedServiceId] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [evidence, setEvidence] = useState<EvidenceState>({ open: false, title: "", items: [] });
  const [entityQuery, setEntityQuery] = useState("");
  const [connectionPanelOpen, setConnectionPanelOpen] = useState(false);
  const [credentials, setCredentials] = useState<ClientCredentials>(() => loadClientCredentials());

  useEffect(() => {
    if (campaignsData.length > 0 && !campaignsData.find((campaign) => campaign.id === selectedCampaignId)) {
      setSelectedCampaignId(campaignsData[0].id);
    }
  }, [campaignsData, selectedCampaignId]);

  useEffect(() => {
    if (infraClustersData.length > 0 && !infraClustersData.find((cluster) => cluster.id === selectedClusterId)) {
      setSelectedClusterId(infraClustersData[0].id);
    }
  }, [infraClustersData, selectedClusterId]);

  useEffect(() => {
    if (indicatorsData.length > 0 && !indicatorsData.find((indicator) => indicator.serviceId === selectedServiceId)) {
      setSelectedServiceId(indicatorsData[0].serviceId);
    }
  }, [indicatorsData, selectedServiceId]);

  useEffect(() => {
    if (entitiesData.length > 0 && (!selectedEntity || !entitiesData.find((entity) => entity.id === selectedEntity.id))) {
      setSelectedEntity(entitiesData[0]);
    }
  }, [entitiesData, selectedEntity]);

  useEffect(() => {
    if (casesData.length > 0 && !casesData.find((packet) => packet.id === selectedCaseId)) {
      setSelectedCaseId(casesData[0].id);
    }
  }, [casesData, selectedCaseId]);

  const activeCase = casesData.find((packet) => packet.id === selectedCaseId);
  const selectedCampaign = campaignsData.find((campaign) => campaign.id === selectedCampaignId);
  const timelineEvidenceRefs = useMemo(
    () =>
      Array.from(
        new Set(eventsData.filter((event) => event.service_id === selectedServiceId).map((event) => event.event_hash)),
      ).slice(0, 12),
    [eventsData, selectedServiceId],
  );

  const toggleSource = (source: SourceType) => {
    setSourceFilters((current) => ({ ...current, [source]: !current[source] }));
  };

  const openEvidence = (title: string, items: EvidenceItem[]) => {
    setEvidence({ open: true, title, items });
  };

  const closeEvidence = () => {
    setEvidence({ open: false, title: "", items: [] });
  };

  const handleSelectEvent = (event: EventRecord) => {
    setSelectedServiceId(event.service_id);
    const entity = entitiesData.find(
      (item) =>
        item.label.toLowerCase().includes(event.service_id.toLowerCase()) ||
        item.label.toLowerCase().includes(event.endpoint.toLowerCase()),
    );
    if (entity) {
      setSelectedEntity(entity);
    }
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
      setCasesData((current) => [packet, ...current.filter((item) => item.id !== packet.id)]);
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
      setOperationsData((current) => ({ ...current, leakageSummary: summary }));
      setLeakageActionLabel(`Done (${summary.totalAlerts} alerts)`);
    } catch {
      setLeakageActionLabel("Scan failed");
    }
  };

  const saveCredentialsAndResync = () => {
    setCredentials(saveClientCredentials(credentials));
    setConnectionPanelOpen(false);
    triggerSync();
  };

  const clearCredentialsAndResync = () => {
    const cleared = saveClientCredentials({ apiKey: "", accessToken: "", legalGrantToken: "", legalTarget: "" });
    setCredentials(cleared);
    triggerSync();
  };

  const statusDotClass = backendStatus === "connected" ? "live" : backendStatus === "degraded" ? "degraded" : "offline";
  const navigate = (id: string) => setActiveScreen(id as ScreenId);

  return (
    <div className="app">
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
          {!auditorOnly && <NavGroup label="SENSE" color="var(--info)" items={NAV_SENSE} active={activeScreen} onSelect={navigate} />}
          {!auditorOnly && (
            <NavGroup label="ANALYZE" color="var(--accent)" items={NAV_ANALYZE} active={activeScreen} onSelect={navigate} />
          )}
          {!auditorOnly && (
            <NavGroup label="ATTRIBUTE" color="var(--warning)" items={NAV_ATTRIBUTE} active={activeScreen} onSelect={navigate} />
          )}
          {!auditorOnly && execute && (
            <NavGroup label="RESPOND" color="var(--risk-critical)" items={NAV_RESPOND} active={activeScreen} onSelect={navigate} />
          )}
          {!auditorOnly && !execute && (
            <NavGroup
              label="RESPOND"
              color="var(--risk-critical)"
              items={[NAV_RESPOND[0]]}
              active={activeScreen}
              onSelect={navigate}
            />
          )}
          <NavGroup label="GOVERN" color="var(--risk-low)" items={NAV_GOVERN} active={activeScreen} onSelect={navigate} />
          {central && <NavGroup label="COMMAND" color="var(--command)" items={NAV_COMMAND} active={activeScreen} onSelect={navigate} />}
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
                onClick={() => setTimeWindow(window.id)}
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
              onClick={() => setConnectionPanelOpen((open) => !open)}
            >
              <Settings size={11} /> Creds
            </button>
            <button
              className="ghost"
              type="button"
              style={{ fontSize: "0.73rem", display: "flex", alignItems: "center", gap: 4 }}
              onClick={triggerSync}
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

      <div className="main">
        <header className="topbar">
          <div className="topbar-group">
            <p className="label" style={{ fontSize: "0.65rem" }}>
              Source filter
            </p>
            <div className="chip-row">
              {SOURCE_OPTIONS.map((source) => (
                <button
                  key={source}
                  className={sourceFilters[source] ? "chip active" : "chip ghost"}
                  type="button"
                  onClick={() => toggleSource(source)}
                >
                  {sourceLabel(source)}
                </button>
              ))}
            </div>
          </div>
          <div className="topbar-group">
            <p className="label" style={{ fontSize: "0.65rem" }}>
              Entity search
            </p>
            <input
              className="search"
              list="entity-options"
              placeholder="Search entities…"
              value={entityQuery}
              onChange={(event) => {
                setEntityQuery(event.target.value);
                const entity = entitiesData.find((item) => item.label === event.target.value);
                if (entity) {
                  setSelectedEntity(entity);
                }
              }}
            />
            <datalist id="entity-options">
              {entitiesData.map((entity) => (
                <option key={entity.label} value={entity.label} />
              ))}
            </datalist>
          </div>
          <div className="topbar-group align-right" />
        </header>

        {connectionPanelOpen && (
          <CredentialsPanel
            credentials={credentials}
            onChange={(key, value) => setCredentials((current) => ({ ...current, [key]: value }))}
            onSave={saveCredentialsAndResync}
            onClear={clearCredentialsAndResync}
          />
        )}

        <div className="content">
          <main className="primary">
            <ActiveScreen
              activeScreen={activeScreen}
              principal={principal}
              central={central}
              execute={execute}
              manageUsers={manageUsers}
              operationsData={operationsData}
              campaignsData={campaignsData}
              eventsData={eventsData}
              timelineData={timelineData}
              indicatorsData={indicatorsData}
              infraClustersData={infraClustersData}
              entitiesData={entitiesData}
              graphData={graphData}
              activeCase={activeCase}
              selectedCampaignId={selectedCampaignId}
              selectedClusterId={selectedClusterId}
              selectedServiceId={selectedServiceId}
              timelineEvidenceRefs={timelineEvidenceRefs}
              sourceFilters={sourceFilters}
              healthGnnLoaded={healthGnnLoaded}
              healthModelVersion={healthModelVersion}
              healthGnnMetrics={healthGnnMetrics}
              leakageActionLabel={leakageActionLabel}
              onNavigate={(id) => setActiveScreen(id)}
              onSelectEvent={handleSelectEvent}
              onSelectEntity={setSelectedEntity}
              onSelectCampaignId={setSelectedCampaignId}
              onSelectClusterId={setSelectedClusterId}
              onSelectServiceId={setSelectedServiceId}
              onOpenEvidence={openEvidence}
              onGenerateCase={() => void handleGenerateCase()}
              onOpenCampaignEvidence={async () => {
                if (!selectedCampaignId) return;
                try {
                  const items = await fetchCampaignEvidenceForDrawer(selectedCampaignId);
                  openEvidence(`Campaign evidence (${selectedCampaignId})`, items);
                } catch {
                  openEvidence("Campaign evidence", []);
                }
              }}
              onRunLeakage={() => void handleRunLeakage()}
              onCaseExportJson={() => {
                if (selectedCampaignId) {
                  void triggerBackendAction(endpoints.caseFromCampaign(selectedCampaignId), "POST");
                }
              }}
              onCaseExportStix={() => {
                if (selectedCampaignId) {
                  void triggerBackendAction(endpoints.stixCaseByCampaign(selectedCampaignId), "GET");
                }
              }}
            />
          </main>

          <Inspector
            principal={principal}
            central={central}
            selectedEntity={selectedEntity}
            selectedCampaign={selectedCampaign}
            healthGnnLoaded={healthGnnLoaded}
            healthModelVersion={healthModelVersion}
            healthGnnMetrics={healthGnnMetrics}
            onNavigate={(id) => setActiveScreen(id)}
            onLogout={onLogout}
          />
        </div>
      </div>

      <EvidenceDrawer open={evidence.open} title={evidence.title} items={evidence.items} onClose={closeEvidence} />
    </div>
  );
}
