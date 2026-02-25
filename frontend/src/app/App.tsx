import { useEffect, useMemo, useState } from "react";
import "../App.css";
import LiveFeed from "../screens/LiveFeed";
import Timeline from "../screens/Timeline";
import GraphExplorer from "../screens/GraphExplorer";
import Campaigns from "../screens/Campaigns";
import InfraCorrelation from "../screens/InfraCorrelation";
import CasePackets from "../screens/CasePackets";
import OperationsCenter from "../screens/OperationsCenter";
import {
  createCasePacketFromCampaign,
  fetchBackendSnapshot,
  fetchCampaignEvidenceForDrawer,
} from "../api/backend";
import {
  emptyOperationsSnapshot,
  fetchOperationsSnapshot,
  runLeakageDetection,
} from "../api/operations";
import { endpoints } from "../api/endpoints";
import {
  apiFetchJson,
  loadClientCredentials,
  saveClientCredentials,
  type ClientCredentials,
} from "../api/client";
import type {
  Campaign,
  CasePacket,
  EntityProfile,
  EvidenceItem,
  EventRecord,
  GraphData,
  GraphEdge,
  GraphNode,
  InfraCluster,
  ServiceIndicator,
  SourceType,
  TimelinePoint,
} from "../types/domain";
import type { OperationsSnapshot } from "../types/operations";

const screens = [
  { id: "live", label: "National Live Feed", tag: "S1" },
  { id: "timeline", label: "Timeline / Indicators", tag: "S2" },
  { id: "graph", label: "Threat Graph Explorer", tag: "S3" },
  { id: "campaigns", label: "Campaign Console", tag: "S4" },
  { id: "infra", label: "Infra & VPN Correlation", tag: "S5" },
  { id: "cases", label: "Case Packet + STIX", tag: "S6" },
  { id: "ops", label: "Operations & Economy", tag: "S7" },
] as const;

type ScreenId = (typeof screens)[number]["id"];

type EvidenceState = {
  open: boolean;
  title: string;
  items: EvidenceItem[];
};

const timeWindows = [
  { id: "10m", label: "10m" },
  { id: "1h", label: "1h" },
  { id: "24h", label: "24h" },
  { id: "30d", label: "30d" },
] as const;

const sourceOptions: SourceType[] = ["telco", "bank", "gov", "osint", "infra"];
const sourceLabel = (source: SourceType) => source.toUpperCase();

const emptyGraph: GraphData = { nodes: [], edges: [] };

export default function App() {
  const [backendStatus, setBackendStatus] = useState<"connected" | "degraded" | "offline">("offline");
  const [backendLabel, setBackendLabel] = useState("Waiting for backend sync");
  const [syncError, setSyncError] = useState("");
  const [actionStatus, setActionStatus] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncNonce, setSyncNonce] = useState(0);

  const [eventsData, setEventsData] = useState<EventRecord[]>([]);
  const [timelineData, setTimelineData] = useState<TimelinePoint[]>([]);
  const [indicatorsData, setIndicatorsData] = useState<ServiceIndicator[]>([]);
  const [campaignsData, setCampaignsData] = useState<Campaign[]>([]);
  const [infraClustersData, setInfraClustersData] = useState<InfraCluster[]>([]);
  const [entitiesData, setEntitiesData] = useState<EntityProfile[]>([]);
  const [graphData, setGraphData] = useState<GraphData>(emptyGraph);
  const [casesData, setCasesData] = useState<CasePacket[]>([]);
  const [operationsData, setOperationsData] = useState<OperationsSnapshot>(emptyOperationsSnapshot);
  const [leakageActionLabel, setLeakageActionLabel] = useState("Run leakage detector");

  const [activeScreen, setActiveScreen] = useState<ScreenId>("live");
  const [timeWindow, setTimeWindow] = useState("1h");
  const [sourceFilters, setSourceFilters] = useState<Record<SourceType, boolean>>(() =>
    sourceOptions.reduce(
      (acc, source) => {
        acc[source] = true;
        return acc;
      },
      {} as Record<SourceType, boolean>,
    ),
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
    let cancelled = false;

    const syncWithBackend = async () => {
      setIsSyncing(true);
      setSyncError("");
      try {
        const [snapshot, operationsSnapshot] = await Promise.all([
          fetchBackendSnapshot(),
          fetchOperationsSnapshot(),
        ]);
        if (cancelled) return;

        setEventsData(snapshot.events);
        setTimelineData(snapshot.timelineCounts);
        setIndicatorsData(snapshot.indicators);
        setCampaignsData(snapshot.campaigns);
        setInfraClustersData(snapshot.infraClusters);
        setEntitiesData(snapshot.entities);
        setGraphData(snapshot.graph);
        setOperationsData(operationsSnapshot);

        setBackendStatus(snapshot.mode === "live" ? "connected" : "degraded");
        const warnings = snapshot.warnings.length > 0 ? ` / warnings: ${snapshot.warnings.join(", ")}` : "";
        setBackendLabel(`${snapshot.connectionLabel}${warnings}`);
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "backend_unreachable";
        setBackendStatus("offline");
        setBackendLabel("Backend unavailable");
        setSyncError(message);
      } finally {
        if (!cancelled) setIsSyncing(false);
      }
    };

    void syncWithBackend();
    const timer = window.setInterval(() => {
      void syncWithBackend();
    }, 30_000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [syncNonce]);

  useEffect(() => {
    if (campaignsData.length === 0) {
      setSelectedCampaignId("");
      return;
    }
    if (!campaignsData.find((item) => item.id === selectedCampaignId)) {
      setSelectedCampaignId(campaignsData[0].id);
    }
  }, [campaignsData, selectedCampaignId]);

  useEffect(() => {
    if (infraClustersData.length === 0) {
      setSelectedClusterId("");
      return;
    }
    if (!infraClustersData.find((item) => item.id === selectedClusterId)) {
      setSelectedClusterId(infraClustersData[0].id);
    }
  }, [infraClustersData, selectedClusterId]);

  useEffect(() => {
    if (indicatorsData.length === 0) {
      setSelectedServiceId("");
      return;
    }
    if (!indicatorsData.find((item) => item.serviceId === selectedServiceId)) {
      setSelectedServiceId(indicatorsData[0].serviceId);
    }
  }, [indicatorsData, selectedServiceId]);

  useEffect(() => {
    if (entitiesData.length === 0) {
      setSelectedEntity(null);
      return;
    }
    if (!selectedEntity || !entitiesData.find((item) => item.id === selectedEntity.id)) {
      setSelectedEntity(entitiesData[0]);
    }
  }, [entitiesData, selectedEntity]);

  useEffect(() => {
    if (casesData.length === 0) {
      setSelectedCaseId("");
      return;
    }
    if (!casesData.find((item) => item.id === selectedCaseId)) {
      setSelectedCaseId(casesData[0].id);
    }
  }, [casesData, selectedCaseId]);

  const activeCase = casesData.find((item) => item.id === selectedCaseId);
  const selectedCampaign = campaignsData.find((item) => item.id === selectedCampaignId);

  const timelineEvidenceRefs = useMemo(() => {
    if (!selectedServiceId) return [];
    return Array.from(
      new Set(
        eventsData
          .filter((item) => item.service_id === selectedServiceId)
          .map((item) => item.event_hash),
      ),
    ).slice(0, 12);
  }, [eventsData, selectedServiceId]);

  const toggleSource = (source: SourceType) => {
    setSourceFilters((prev) => ({ ...prev, [source]: !prev[source] }));
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
    if (entity) setSelectedEntity(entity);
  };

  const handleShowGraph = (event: EventRecord) => {
    handleSelectEvent(event);
    setActiveScreen("graph");
  };

  const handleShowTimeline = (event: EventRecord) => {
    setSelectedServiceId(event.service_id);
    setActiveScreen("timeline");
  };

  const handleOpenCampaign = () => {
    if (campaignsData.length > 0) setSelectedCampaignId(campaignsData[0].id);
    setActiveScreen("campaigns");
  };

  const handleShowInfra = () => {
    if (infraClustersData.length > 0) setSelectedClusterId(infraClustersData[0].id);
    setActiveScreen("infra");
  };

  const handleGraphNode = (node: GraphNode) => {
    const entity = entitiesData.find((item) => item.label.toLowerCase().includes(node.label.toLowerCase()));
    if (entity) setSelectedEntity(entity);
  };

  const handleGraphEdge = (edge: GraphEdge) => {
    setEvidence({
      open: true,
      title: `Edge evidence: ${edge.source} -> ${edge.target}`,
      items: edge.evidence,
    });
  };

  const triggerBackendAction = async (path: string, method: "POST" | "GET" = "POST") => {
    setActionStatus(`${method} ${path}`);
    try {
      await apiFetchJson<Record<string, unknown>>(path, { method });
      setActionStatus(`completed ${method} ${path}`);
    } catch (error) {
      setActionStatus(`failed ${method} ${path}: ${error instanceof Error ? error.message : "request_failed"}`);
    }
  };

  const handleGenerateCase = async () => {
    if (!selectedCampaignId) return;
    setActionStatus(`POST ${endpoints.caseFromCampaign(selectedCampaignId)}`);
    try {
      const packet = await createCasePacketFromCampaign(selectedCampaignId);
      setCasesData((prev) => {
        const withoutCurrent = prev.filter((item) => item.id !== packet.id);
        return [packet, ...withoutCurrent];
      });
      setSelectedCaseId(packet.id);
      setActiveScreen("cases");
      setActionStatus(`case generated ${packet.id}`);
    } catch (error) {
      setActionStatus(`case generation failed: ${error instanceof Error ? error.message : "request_failed"}`);
      setActiveScreen("cases");
    }
  };

  const handleRunLeakage = async () => {
    setLeakageActionLabel("Running leakage detector...");
    try {
      const summary = await runLeakageDetection(30);
      setOperationsData((prev) => ({ ...prev, leakageSummary: summary }));
      setLeakageActionLabel(`Leakage scan complete (${summary.totalAlerts} alerts)`);
      setActionStatus("leakage detector completed");
    } catch (error) {
      setLeakageActionLabel("Leakage detector failed");
      setActionStatus(`leakage detector failed: ${error instanceof Error ? error.message : "request_failed"}`);
    }
  };

  const searchOptions = entitiesData.map((entity) => entity.label);

  const handleSearch = (value: string) => {
    setEntityQuery(value);
    const entity = entitiesData.find((item) => item.label === value);
    if (entity) setSelectedEntity(entity);
  };

  const saveCredentialsAndResync = () => {
    const persisted = saveClientCredentials(credentials);
    setCredentials(persisted);
    setConnectionPanelOpen(false);
    setSyncNonce((prev) => prev + 1);
  };

  const clearCredentials = () => {
    const cleared = saveClientCredentials({
      apiKey: "",
      accessToken: "",
      legalGrantToken: "",
      legalTarget: "",
    });
    setCredentials(cleared);
    setActionStatus("local client credentials cleared");
    setSyncNonce((prev) => prev + 1);
  };

  return (
    <div className="app">
      <aside className="nav">
        <div className="nav-header">
          <div>
            <p className="eyebrow">Sentinel-Ke</p>
            <h1>National SOC Console</h1>
            <p className="muted">
              {backendLabel}
              {isSyncing ? " / syncing..." : ""}
            </p>
            {syncError && <p className="muted">Sync error: {syncError}</p>}
            {actionStatus && <p className="muted">Action: {actionStatus}</p>}
          </div>
          <div className="status-badge">
            {backendStatus === "connected"
              ? "Backend Live"
              : backendStatus === "degraded"
                ? "Backend Degraded"
                : "Backend Offline"}
          </div>
        </div>
        <nav className="nav-list">
          {screens.map((screen) => (
            <button
              key={screen.id}
              className={activeScreen === screen.id ? "nav-item active" : "nav-item"}
              type="button"
              onClick={() => setActiveScreen(screen.id)}
            >
              <span>{screen.tag}</span>
              <span>{screen.label}</span>
            </button>
          ))}
        </nav>
        <div className="nav-footer">
          <p className="label">Global time window</p>
          <div className="chip-row">
            {timeWindows.map((window) => (
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
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-group">
            <div>
              <p className="label">Source filter</p>
              <div className="chip-row">
                {sourceOptions.map((source) => (
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
          </div>
          <div className="topbar-group">
            <div>
              <p className="label">Entity search</p>
              <input
                className="search"
                list="entity-options"
                placeholder="Search entities"
                value={entityQuery}
                onChange={(event) => handleSearch(event.target.value)}
              />
              <datalist id="entity-options">
                {searchOptions.map((label) => (
                  <option key={label} value={label} />
                ))}
              </datalist>
            </div>
          </div>
          <div className="topbar-group align-right">
            <div className="chip-row">
              <button className="ghost" type="button" onClick={() => setConnectionPanelOpen((prev) => !prev)}>
                API Credentials
              </button>
              <button className="ghost" type="button" onClick={() => setSyncNonce((prev) => prev + 1)}>
                Resync
              </button>
            </div>
          </div>
        </header>

        {connectionPanelOpen && (
          <div className="panel connection-panel">
            <div className="panel-header">
              <h3>Client Credentials</h3>
              <span className="muted">Stored in browser localStorage</span>
            </div>
            <div className="grid-two">
              <label>
                <p className="label">X-API-Key</p>
                <input
                  className="search"
                  value={credentials.apiKey}
                  onChange={(event) => setCredentials((prev) => ({ ...prev, apiKey: event.target.value }))}
                  placeholder="Frontend API key"
                />
              </label>
              <label>
                <p className="label">Bearer Token</p>
                <input
                  className="search"
                  value={credentials.accessToken}
                  onChange={(event) => setCredentials((prev) => ({ ...prev, accessToken: event.target.value }))}
                  placeholder="Access token"
                />
              </label>
            </div>
            <div className="grid-two">
              <label>
                <p className="label">Legal Grant Token</p>
                <input
                  className="search"
                  value={credentials.legalGrantToken}
                  onChange={(event) => setCredentials((prev) => ({ ...prev, legalGrantToken: event.target.value }))}
                  placeholder="X-Legal-Grant-Token"
                />
              </label>
              <label>
                <p className="label">Legal Target</p>
                <input
                  className="search"
                  value={credentials.legalTarget}
                  onChange={(event) => setCredentials((prev) => ({ ...prev, legalTarget: event.target.value }))}
                  placeholder="economy:procurement"
                />
              </label>
            </div>
            <div className="chip-row">
              <button className="ghost" type="button" onClick={saveCredentialsAndResync}>
                Save & Resync
              </button>
              <button className="ghost" type="button" onClick={clearCredentials}>
                Clear Stored Credentials
              </button>
            </div>
          </div>
        )}

        <div className="content">
          <main className="primary">
            {activeScreen === "live" && (
              <LiveFeed
                events={eventsData}
                timeline={timelineData}
                activeSources={sourceFilters}
                onSelectEvent={handleSelectEvent}
                onShowGraph={handleShowGraph}
                onShowTimeline={handleShowTimeline}
                onShowEvidence={(title, event) => openEvidence(title, event.evidence)}
              />
            )}
            {activeScreen === "timeline" && (
              <Timeline
                indicators={indicatorsData}
                selectedService={selectedServiceId}
                evidenceRefs={timelineEvidenceRefs}
                onSelectService={setSelectedServiceId}
                onOpenCampaign={handleOpenCampaign}
                onShowInfra={handleShowInfra}
              />
            )}
            {activeScreen === "graph" && (
              <GraphExplorer
                graph={graphData}
                onSelectNode={handleGraphNode}
                onSelectEdge={handleGraphEdge}
              />
            )}
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
                    const evidenceItems = await fetchCampaignEvidenceForDrawer(selectedCampaignId);
                    openEvidence(`Campaign evidence (${selectedCampaignId})`, evidenceItems);
                  } catch (error) {
                    setActionStatus(
                      `campaign evidence failed: ${error instanceof Error ? error.message : "request_failed"}`,
                    );
                    openEvidence(`Campaign evidence (${selectedCampaignId})`, []);
                  }
                }}
              />
            )}
            {activeScreen === "infra" && (
              <InfraCorrelation
                clusters={infraClustersData}
                selectedId={selectedClusterId}
                onSelect={setSelectedClusterId}
                onOpenGraph={() => setActiveScreen("graph")}
                onOpenEvidence={(cluster) => openEvidence(`Evidence for ${cluster.id}`, cluster.evidence)}
              />
            )}
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
            {activeScreen === "ops" && (
              <OperationsCenter
                data={operationsData}
                onRunLeakage={handleRunLeakage}
                leakageActionLabel={leakageActionLabel}
              />
            )}
          </main>

          <aside className="inspector">
            <div className="panel">
              <div className="panel-header">
                <h3>Entity Profile</h3>
                <span className="muted">Right-side inspector</span>
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
                      <p className="stat">{selectedEntity.risk}</p>
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
                  <div className="panel-subsection">
                    <h4>Notes</h4>
                    <ul>
                      {selectedEntity.notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3>Active campaign</h3>
                <span className="muted">{selectedCampaign?.id ?? "-"}</span>
              </div>
              {selectedCampaign ? (
                <>
                  <p className="label">{selectedCampaign.name}</p>
                  <p className="muted">
                    {selectedCampaign.type} / {selectedCampaign.status}
                  </p>
                  <button className="ghost" type="button" onClick={() => setActiveScreen("campaigns")}>
                    View campaign
                  </button>
                </>
              ) : (
                <p className="muted">No campaign selected.</p>
              )}
            </div>
          </aside>
        </div>
      </div>

      <div className={evidence.open ? "evidence-drawer open" : "evidence-drawer"}>
        <div className="drawer-header">
          <div>
            <p className="label">Evidence drawer</p>
            <h3>{evidence.title}</h3>
          </div>
          <button className="ghost" type="button" onClick={closeEvidence}>
            Close
          </button>
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
