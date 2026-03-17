import { useEffect, useMemo, useState } from "react";

import "../App.css";

import LoginScreen from "../screens/auth/LoginScreen";
import { apiLogout, clearSession, getRefreshToken, loadPrincipal } from "../api/auth";
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
import { SCREEN_CHROME, SCREEN_GUIDES, SOURCE_OPTIONS, type ScreenId } from "./navigation";
import { useDashboardSync } from "./useDashboardSync";
import { canonicalServiceKey } from "../utils/entityKeys";

type EvidenceState = {
  open: boolean;
  title: string;
  items: EvidenceItem[];
};

export default function App() {
  const [principal, setPrincipal] = useState<Principal | null>(() => loadPrincipal());

  useEffect(() => {
    const handleAuthExpired = () => {
      clearSession();
      setPrincipal(null);
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
  const screenGuide = SCREEN_GUIDES[activeScreen];
  const screenChrome = SCREEN_CHROME[activeScreen];
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
          onInvestigateEntity={(entity) => {
            setSelectedEntity(entity);
            setActiveScreen("investigate");
            setInspectorOpen(true);
          }}
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
              selectedEntity={selectedEntity}
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
                } else {
                  // Stub entity so EntityInvestigation receives the key as initialEntityKey
                  setSelectedEntity({ id: entityKey, label: entityKey } as typeof entitiesData[0]);
                }
                setActiveScreen("investigate");
              }}
            />
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

        <footer className="workspace-footer">
          <div className="workspace-footer-block">
            <p className="workspace-footer-label">What This Page Is For</p>
            <p className="workspace-footer-copy">{screenGuide.purpose}</p>
          </div>
          <div className="workspace-footer-block">
            <p className="workspace-footer-label">Use It In 3 Steps</p>
            <ol className="workspace-footer-steps">
              {screenGuide.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>
          <div className="workspace-footer-block">
            <p className="workspace-footer-label">Best Next Move</p>
            <p className="workspace-footer-copy">{screenGuide.next ?? "Stay on this page until one action is complete."}</p>
          </div>
        </footer>
      </div>

      <EvidenceDrawer open={evidence.open} title={evidence.title} items={evidence.items} onClose={closeEvidence} />
    </div>
  );
}
