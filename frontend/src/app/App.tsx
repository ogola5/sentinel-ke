import { useEffect, useMemo, useState } from "react";
import { Loader } from "lucide-react";

import "../App.css";

import { apiLogout, clearSession, getRefreshToken } from "../api/auth";
import {
  createCasePacketFromCampaign,
  downloadCasePacketFromCampaign,
  downloadStixBundleForCampaign,
  fetchCampaignEvidenceForDrawer,
} from "../api/backend";
import {
  loadClientCredentials,
  saveClientCredentials,
  type ClientCredentials,
} from "../api/client";
import { runLeakageDetection } from "../api/operations";
import {
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
import GlobalAssistantPanel from "./GlobalAssistantPanel";
import Inspector from "./Inspector";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import WorkflowGuideStrip from "./WorkflowGuideStrip";
import { SCREEN_CHROME, SCREEN_GUIDES, SOURCE_OPTIONS, type ScreenId } from "./navigation";
import { useDashboardSync } from "./useDashboardSync";
import { canonicalServiceKey } from "../utils/entityKeys";

type EvidenceState = {
  open: boolean;
  title: string;
  items: EvidenceItem[];
};

const DEFAULT_PRINCIPAL: Principal = {
  principal_type: "user",
  user_id: "admin",
  username: "admin",
  display_name: "Admin",
  role: "admin",
  access_level: "central",
  section_code: null,
  scopes: ["read", "write", "execute", "manage_users"],
  mfa_authenticated: true,
};

export default function App() {
  const [principal] = useState<Principal>(DEFAULT_PRINCIPAL);

  useEffect(() => {
    const handleAuthExpired = () => {
      clearSession();
    };

    window.addEventListener("sentinel:auth-expired", handleAuthExpired);
    return () => window.removeEventListener("sentinel:auth-expired", handleAuthExpired);
  }, []);

  const handleLogout = async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      await apiLogout(refreshToken).catch(() => undefined);
    }
    clearSession();
  };

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
    snapshotReady,
    healthGnnLoaded,
    healthModelVersion,
    healthGnnMetrics,
    healthPlatformStatus,
    eventsData,
    timelineData,
    indicatorsData,
    threatSummaryData,
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
  const [startupRetryIssued, setStartupRetryIssued] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);

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
  const [investigationEntityKey, setInvestigationEntityKey] = useState<string | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [selectedClusterId, setSelectedClusterId] = useState("");
  const [selectedServiceId, setSelectedServiceId] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [evidence, setEvidence] = useState<EvidenceState>({ open: false, title: "", items: [] });
  const [entityQuery, setEntityQuery] = useState("");
const [connectionPanelOpen, setConnectionPanelOpen] = useState(false);
  const [credentials, setCredentials] = useState<ClientCredentials>(() => loadClientCredentials());

  useEffect(() => {
    if (startupRetryIssued || !snapshotReady || isSyncing) return;
    if (eventsData.length > 0 || campaignsData.length > 0 || infraClustersData.length > 0) return;
    setStartupRetryIssued(true);
    const timer = window.setTimeout(() => {
      triggerSync();
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [
    campaignsData.length,
    eventsData.length,
    infraClustersData.length,
    isSyncing,
    snapshotReady,
    startupRetryIssued,
    triggerSync,
  ]);

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
      setInvestigationEntityKey((current) => current ?? entitiesData[0].id);
    }
  }, [entitiesData, selectedEntity]);

  useEffect(() => {
    if (casesData.length > 0 && !casesData.find((packet) => packet.id === selectedCaseId)) {
      setSelectedCaseId(casesData[0].id);
    }
  }, [casesData, selectedCaseId]);

  const activeCase = casesData.find((packet) => packet.id === selectedCaseId);
  const selectedCampaign = campaignsData.find((campaign) => campaign.id === selectedCampaignId);
  const screenGuide = SCREEN_GUIDES[activeScreen];
  const screenChrome = SCREEN_CHROME[activeScreen];
  const showWorkflowGuide = ["command", "ops", "live", "graph", "investigate", "defense", "reports", "gnn"].includes(activeScreen);
  const showWorkspaceLoading = !snapshotReady && isSyncing;
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
        item.id === canonicalServiceKey(event.service_id) ||
        item.label.toLowerCase().includes(event.service_id.toLowerCase()) ||
        item.label.toLowerCase().includes(event.endpoint.toLowerCase()),
    );
    if (entity) {
      setSelectedEntity(entity);
      setInvestigationEntityKey(entity.id);
    }
  };

  const handleGenerateCase = async (campaignId?: string) => {
    const id = campaignId ?? selectedCampaignId;
    if (!id) return;
    try {
      const packet = await createCasePacketFromCampaign(id);
      setSelectedCampaignId(id);
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

  return (
    <div className="app">
      <Sidebar
        principal={principal}
        activeScreen={activeScreen}
        auditorOnly={auditorOnly}
        central={central}
        execute={execute}
        manageUsers={manageUsers}
        collapsed={navCollapsed}
        backendStatus={backendStatus}
        backendLabel={backendLabel}
        isSyncing={isSyncing}
        syncError={syncError}
        actionStatus={actionStatus}
        healthGnnLoaded={healthGnnLoaded}
        onNavigate={(id) => setActiveScreen(id)}
        onToggleCollapse={() => setNavCollapsed((c) => !c)}
        onToggleConnectionPanel={() => setConnectionPanelOpen((open) => !open)}
        onTriggerSync={triggerSync}
        onLogout={onLogout}
      />

      <div className="main">
        <Topbar
          activeScreen={activeScreen}
          sourceFilters={sourceFilters}
          timeWindow={timeWindow}
          entityQuery={entityQuery}
          entities={entitiesData}
          inspectorOpen={inspectorOpen}
          assistantOpen={assistantOpen}
          onToggleSource={toggleSource}
          onSelectTimeWindow={setTimeWindow}
          onEntityQueryChange={setEntityQuery}
          onApplyEntityExample={(value) => setEntityQuery(value)}
          onInvestigateEntity={(entity) => {
            setSelectedEntity(entity);
            setInvestigationEntityKey(entity.id);
            setActiveScreen("investigate");
            setInspectorOpen(true);
          }}
          onOpenNextScreen={(screen) => setActiveScreen(screen)}
          onOpenInspector={() => setInspectorOpen(true)}
          onToggleAssistant={() => setAssistantOpen((open) => !open)}
        />

        <GlobalAssistantPanel
          open={assistantOpen}
          activeScreen={activeScreen}
          screenTitle={screenChrome.title}
          screenGuide={screenGuide}
          principal={principal}
          backendLabel={backendLabel}
          selectedEntity={selectedEntity}
          selectedCampaignId={selectedCampaignId}
          selectedServiceId={selectedServiceId}
          selectedCaseId={selectedCaseId}
          eventCount={eventsData.length}
          campaignCount={campaignsData.length}
          entityCount={entitiesData.length}
          graphNodes={graphData.nodes.length}
          graphEdges={graphData.edges.length}
          healthGnnLoaded={healthGnnLoaded}
          healthModelVersion={healthModelVersion}
          actionStatus={actionStatus}
          onClose={() => setAssistantOpen(false)}
          onRequireLogin={onLogout}
        />

        {connectionPanelOpen && (
          <CredentialsPanel
            credentials={credentials}
            onChange={(key, value) => setCredentials((current) => ({ ...current, [key]: value }))}
            onSave={saveCredentialsAndResync}
            onClear={clearCredentialsAndResync}
            onClose={() => setConnectionPanelOpen(false)}
          />
        )}

        <div className={`content${inspectorOpen ? " inspector-open" : ""}`}>
          <main className="primary">
            {showWorkspaceLoading ? (
              <section className="panel" style={{ maxWidth: 560, width: "100%", margin: "0 auto", textAlign: "center" }}>
                <div className="state-box" style={{ padding: "40px 24px" }}>
                  <Loader size={24} className="spin" />
                  <p style={{ fontWeight: 700, marginTop: 12 }}>Syncing live workspace…</p>
                  <p className="muted" style={{ maxWidth: 420, margin: "8px auto 0" }}>
                    Sentinel-KE is loading events, campaigns, infrastructure, and graph context from the backend before opening the workspace.
                  </p>
                </div>
              </section>
            ) : (
              <>
                {showWorkflowGuide && (
                  <WorkflowGuideStrip
                    title={screenChrome.title}
                    guide={screenGuide}
                    onNavigate={(screen) => setActiveScreen(screen)}
                    onApplyExample={(value) => setEntityQuery(value)}
                  />
                )}
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
                  threatSummaryData={threatSummaryData}
                  infraClustersData={infraClustersData}
                  entitiesData={entitiesData}
                  graphData={graphData}
                  activeCase={activeCase}
                  isSyncing={isSyncing}
                  snapshotReady={snapshotReady}
                  selectedEntity={selectedEntity}
                  investigationEntityKey={investigationEntityKey}
                  selectedCampaignId={selectedCampaignId}
                  selectedClusterId={selectedClusterId}
                  selectedServiceId={selectedServiceId}
                  timelineEvidenceRefs={timelineEvidenceRefs}
                  sourceFilters={sourceFilters}
                  healthGnnLoaded={healthGnnLoaded}
                  healthModelVersion={healthModelVersion}
                  healthGnnMetrics={healthGnnMetrics}
                  healthPlatformStatus={healthPlatformStatus}
                  leakageActionLabel={leakageActionLabel}
                  onNavigate={(id) => setActiveScreen(id)}
                  onSelectEvent={handleSelectEvent}
                  onSelectEntity={(entity) => {
                    setSelectedEntity(entity);
                    setInvestigationEntityKey(entity.id);
                    setInspectorOpen(true);
                  }}
                  onSelectCampaignId={setSelectedCampaignId}
                  onSelectClusterId={setSelectedClusterId}
                  onSelectServiceId={setSelectedServiceId}
                  onOpenEvidence={openEvidence}
                  onGenerateCase={() => void handleGenerateCase()}
                  onGenerateCaseForId={(id: string) => void handleGenerateCase(id)}
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
                    const exportCampaignId = activeCase?.campaignId ?? selectedCampaignId;
                    if (exportCampaignId) {
                      void (async () => {
                        try {
                          const filename = await downloadCasePacketFromCampaign(exportCampaignId);
                          setActionStatus(`downloaded ${filename}`);
                        } catch (err) {
                          setActionStatus(`failed: ${err instanceof Error ? err.message : "request_failed"}`);
                        }
                      })();
                    }
                  }}
                  onCaseExportStix={() => {
                    const exportCampaignId = activeCase?.campaignId ?? selectedCampaignId;
                    if (exportCampaignId) {
                      void (async () => {
                        try {
                          const filename = await downloadStixBundleForCampaign(exportCampaignId);
                          setActionStatus(`downloaded ${filename}`);
                        } catch (err) {
                          setActionStatus(`failed: ${err instanceof Error ? err.message : "request_failed"}`);
                        }
                      })();
                    }
                  }}
                  onInvestigateEntity={(entityKey: string) => {
                    const match = entitiesData.find(
                      (e) => e.id === entityKey || e.label.toLowerCase() === entityKey.toLowerCase(),
                    );
                    if (match) {
                      setSelectedEntity(match);
                    }
                    setInvestigationEntityKey(entityKey);
                    setActiveScreen("investigate");
                  }}
                />
              </>
            )}
          </main>

          {inspectorOpen && (
            <Inspector
              principal={principal}
              selectedEntity={selectedEntity}
              selectedCampaign={selectedCampaign}
              onNavigate={(id) => setActiveScreen(id)}
              onClose={() => setInspectorOpen(false)}
            />
          )}
        </div>

      </div>

      <EvidenceDrawer open={evidence.open} title={evidence.title} items={evidence.items} onClose={closeEvidence} />
    </div>
  );
}
