import { useEffect, useMemo, useState } from "react";

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
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import { SOURCE_OPTIONS, type ScreenId } from "./navigation";
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

  return (
    <div className="app">
      <Sidebar
        principal={principal}
        activeScreen={activeScreen}
        auditorOnly={auditorOnly}
        central={central}
        execute={execute}
        timeWindow={timeWindow}
        backendStatus={backendStatus}
        backendLabel={backendLabel}
        isSyncing={isSyncing}
        syncError={syncError}
        actionStatus={actionStatus}
        healthGnnLoaded={healthGnnLoaded}
        onNavigate={(id) => setActiveScreen(id)}
        onSelectTimeWindow={setTimeWindow}
        onToggleConnectionPanel={() => setConnectionPanelOpen((open) => !open)}
        onTriggerSync={triggerSync}
        onLogout={onLogout}
      />

      <div className="main">
        <Topbar
          sourceFilters={sourceFilters}
          entityQuery={entityQuery}
          entities={entitiesData}
          onToggleSource={toggleSource}
          onEntityQueryChange={setEntityQuery}
          onSelectEntity={setSelectedEntity}
        />

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
