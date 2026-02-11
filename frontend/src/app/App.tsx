import { useEffect, useState } from "react";
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
  fetchOperationsSnapshot,
  runLeakageDetection,
} from "../api/operations";
import { endpoints } from "../api/endpoints";
import {
  campaigns as demoCampaigns,
  cases as demoCases,
  entities as demoEntities,
  events as demoEvents,
  graphData,
  indicators as demoIndicators,
  infraClusters as demoInfraClusters,
  operationsSnapshotDemo,
  sourceOptions,
  timelineCounts as demoTimelineCounts,
} from "../data/demoData";
import type {
  Campaign,
  CasePacket,
  EntityProfile,
  EvidenceItem,
  EventRecord,
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

const sourceLabel = (source: SourceType) => source.toUpperCase();

export default function App() {
  const [backendStatus, setBackendStatus] = useState<"connected" | "degraded" | "offline">("offline");
  const [backendLabel, setBackendLabel] = useState("Demo mode");
  const [isSyncing, setIsSyncing] = useState(false);

  const [eventsData, setEventsData] = useState<EventRecord[]>(demoEvents);
  const [timelineData, setTimelineData] = useState<TimelinePoint[]>(demoTimelineCounts);
  const [indicatorsData, setIndicatorsData] = useState<ServiceIndicator[]>(demoIndicators);
  const [campaignsData, setCampaignsData] = useState<Campaign[]>(demoCampaigns);
  const [infraClustersData, setInfraClustersData] = useState<InfraCluster[]>(demoInfraClusters);
  const [entitiesData, setEntitiesData] = useState<EntityProfile[]>(demoEntities);
  const [casesData, setCasesData] = useState<CasePacket[]>(demoCases);
  const [operationsData, setOperationsData] = useState<OperationsSnapshot>(operationsSnapshotDemo);
  const [leakageActionLabel, setLeakageActionLabel] = useState("Run leakage detector");

  const [activeScreen, setActiveScreen] = useState<ScreenId>("live");
  const [timeWindow, setTimeWindow] = useState("1h");
  const [sourceFilters, setSourceFilters] = useState<Record<SourceType, boolean>>(() => {
    return sourceOptions.reduce((acc, source) => {
      acc[source] = true;
      return acc;
    }, {} as Record<SourceType, boolean>);
  });
  const [selectedEntity, setSelectedEntity] = useState<EntityProfile>(demoEntities[0]);
  const [selectedCampaignId, setSelectedCampaignId] = useState(demoCampaigns[0]?.id ?? "");
  const [selectedClusterId, setSelectedClusterId] = useState(demoInfraClusters[0]?.id ?? "");
  const [selectedServiceId, setSelectedServiceId] = useState(demoIndicators[0]?.serviceId ?? "");
  const [selectedCaseId, setSelectedCaseId] = useState(demoCases[0]?.id ?? "");
  const [evidence, setEvidence] = useState<EvidenceState>({ open: false, title: "", items: [] });
  const [demoOpen, setDemoOpen] = useState(false);
  const [demoStatus, setDemoStatus] = useState("Idle");
  const [entityQuery, setEntityQuery] = useState("");

  useEffect(() => {
    let cancelled = false;

    const syncWithBackend = async () => {
      setIsSyncing(true);
      try {
        const [snapshot, operationsSnapshot] = await Promise.all([
          fetchBackendSnapshot(),
          fetchOperationsSnapshot(),
        ]);
        if (cancelled) return;

        if (snapshot.events.length > 0) setEventsData(snapshot.events);
        if (snapshot.timelineCounts.length > 0) setTimelineData(snapshot.timelineCounts);
        if (snapshot.indicators.length > 0) setIndicatorsData(snapshot.indicators);
        if (snapshot.campaigns.length > 0) setCampaignsData(snapshot.campaigns);
        if (snapshot.infraClusters.length > 0) setInfraClustersData(snapshot.infraClusters);
        if (snapshot.entities.length > 0) setEntitiesData(snapshot.entities);
        setOperationsData(operationsSnapshot);

        setBackendStatus(snapshot.mode === "live" ? "connected" : "degraded");
        setBackendLabel(snapshot.connectionLabel);
      } catch {
        if (cancelled) return;
        setBackendStatus("offline");
        setBackendLabel("Backend unavailable, using demo data");
        setOperationsData(operationsSnapshotDemo);
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
  }, []);

  useEffect(() => {
    if (campaignsData.length === 0) return;
    if (!campaignsData.find((item) => item.id === selectedCampaignId)) {
      setSelectedCampaignId(campaignsData[0].id);
    }
  }, [campaignsData, selectedCampaignId]);

  useEffect(() => {
    if (infraClustersData.length === 0) return;
    if (!infraClustersData.find((item) => item.id === selectedClusterId)) {
      setSelectedClusterId(infraClustersData[0].id);
    }
  }, [infraClustersData, selectedClusterId]);

  useEffect(() => {
    if (indicatorsData.length === 0) return;
    if (!indicatorsData.find((item) => item.serviceId === selectedServiceId)) {
      setSelectedServiceId(indicatorsData[0].serviceId);
    }
  }, [indicatorsData, selectedServiceId]);

  useEffect(() => {
    if (entitiesData.length === 0) return;
    if (!entitiesData.find((item) => item.id === selectedEntity.id)) {
      setSelectedEntity(entitiesData[0]);
    }
  }, [entitiesData, selectedEntity.id]);

  useEffect(() => {
    if (casesData.length === 0) return;
    if (!casesData.find((item) => item.id === selectedCaseId)) {
      setSelectedCaseId(casesData[0].id);
    }
  }, [casesData, selectedCaseId]);

  const activeCase = casesData.find((item) => item.id === selectedCaseId) ?? casesData[0];
  const selectedCampaign = campaignsData.find((item) => item.id === selectedCampaignId) ?? campaignsData[0];

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
    const entity = entitiesData.find((item) =>
      item.label.toLowerCase().includes(event.service_id.toLowerCase()) ||
      item.label.toLowerCase().includes(event.endpoint.toLowerCase())
    );
    if (entity) {
      setSelectedEntity(entity);
    }
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
    if (campaignsData.length > 0) {
      setSelectedCampaignId(campaignsData[0].id);
    }
    setActiveScreen("campaigns");
  };

  const handleShowInfra = () => {
    if (infraClustersData.length > 0) {
      setSelectedClusterId(infraClustersData[0].id);
    }
    setActiveScreen("infra");
  };

  const handleGraphNode = (node: GraphNode) => {
    const entity = entitiesData.find((item) => item.label.toLowerCase().includes(node.label.toLowerCase()));
    if (entity) {
      setSelectedEntity(entity);
    }
  };

  const handleGraphEdge = (edge: GraphEdge) => {
    setEvidence({
      open: true,
      title: `Edge evidence: ${edge.source} -> ${edge.target}`,
      items: edge.evidence,
    });
  };

  const handleScenario = async (path: string, method: "POST" | "GET" = "POST") => {
    setDemoStatus(`${method} ${path}`);
    try {
      await fetch(path, { method });
      setDemoStatus(`Completed ${method} ${path}`);
    } catch {
      setDemoStatus(`Failed ${method} ${path}`);
    }
  };

  const handleGenerateCase = async () => {
    if (!selectedCampaignId) return;
    setDemoStatus(`POST ${endpoints.caseFromCampaign(selectedCampaignId)}`);
    try {
      const packet = await createCasePacketFromCampaign(selectedCampaignId);
      setCasesData((prev) => {
        const withoutCurrent = prev.filter((item) => item.id !== packet.id);
        return [packet, ...withoutCurrent];
      });
      setSelectedCaseId(packet.id);
      setActiveScreen("cases");
      setDemoStatus(`Case generated ${packet.id}`);
    } catch {
      if (casesData.length > 0) {
        setSelectedCaseId(casesData[0].id);
      }
      setDemoStatus("Case generation failed");
      setActiveScreen("cases");
    }
  };

  const handleRunLeakage = async () => {
    setLeakageActionLabel("Running leakage detector...");
    try {
      const summary = await runLeakageDetection(30);
      setOperationsData((prev) => ({ ...prev, leakageSummary: summary }));
      setLeakageActionLabel(`Leakage scan complete (${summary.totalAlerts} alerts)`);
    } catch {
      setLeakageActionLabel("Leakage detector failed");
    }
  };

  const searchOptions = entitiesData.map((entity) => entity.label);

  const handleSearch = (value: string) => {
    setEntityQuery(value);
    const entity = entitiesData.find((item) => item.label === value);
    if (entity) {
      setSelectedEntity(entity);
    }
  };

  return (
    <div className="app">
      <aside className="nav">
        <div className="nav-header">
          <div>
            <p className="eyebrow">Sentinel-Ke</p>
            <h1>National SOC Console</h1>
            <p className="muted">{backendLabel}{isSyncing ? " / syncing..." : ""}</p>
          </div>
          <div className="status-badge">
            {backendStatus === "connected" ? "Backend Live" : backendStatus === "degraded" ? "Backend Degraded" : "Demo Mode"}
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
            <button className="ghost" type="button" onClick={() => setDemoOpen((prev) => !prev)}>
              Scenario Controller
            </button>
          </div>
        </header>

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
                  try {
                    const evidenceItems = await fetchCampaignEvidenceForDrawer(selectedCampaignId);
                    openEvidence(
                      `Campaign evidence (${selectedCampaignId})`,
                      evidenceItems.length > 0
                        ? evidenceItems
                        : eventsData.slice(0, 3).flatMap((item) => item.evidence.slice(0, 1)),
                    );
                  } catch {
                    openEvidence(
                      `Campaign evidence (${selectedCampaignId})`,
                      eventsData.slice(0, 3).flatMap((item) => item.evidence.slice(0, 1)),
                    );
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
                onExportJson={() => handleScenario(endpoints.caseFromCampaign(selectedCampaignId), "POST")}
                onExportStix={() => handleScenario(endpoints.stixCaseByCampaign(selectedCampaignId), "GET")}
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
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3>Active campaign</h3>
                <span className="muted">{selectedCampaign.id}</span>
              </div>
              <p className="label">{selectedCampaign.name}</p>
              <p className="muted">{selectedCampaign.type} / {selectedCampaign.status}</p>
              <button className="ghost" type="button" onClick={() => setActiveScreen("campaigns")}>View campaign</button>
            </div>
          </aside>
        </div>
      </div>

      <div className={demoOpen ? "demo-panel open" : "demo-panel"}>
        <div className="panel-header">
          <h3>Scenario Controller</h3>
          <span className="muted">Deterministic demo</span>
        </div>
        <p className="muted">Status: {demoStatus}</p>
        <div className="demo-actions">
          <button className="ghost" type="button" onClick={() => handleScenario("/v1/demo/scenario/start/A")}>Start Scenario A</button>
          <button className="ghost" type="button" onClick={() => handleScenario("/v1/demo/scenario/start/B")}>Start Scenario B</button>
          <button className="ghost" type="button" onClick={() => handleScenario("/v1/demo/scenario/start/C")}>Start Scenario C</button>
          <button className="ghost" type="button" onClick={() => handleScenario("/v1/demo/scenario/reset")}>Reset</button>
          <button className="ghost" type="button" onClick={() => handleScenario("/v1/demo/replay")}>Replay last 10m</button>
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
