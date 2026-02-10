import { useState } from "react";
import "../App.css";
import LiveFeed from "../screens/LiveFeed";
import Timeline from "../screens/Timeline";
import GraphExplorer from "../screens/GraphExplorer";
import Campaigns from "../screens/Campaigns";
import InfraCorrelation from "../screens/InfraCorrelation";
import CasePackets from "../screens/CasePackets";
import {
  campaigns,
  cases,
  entities,
  events,
  graphData,
  indicators,
  infraClusters,
  sourceOptions,
  timelineCounts,
} from "../data/demoData";
import type { EvidenceItem, EventRecord, GraphEdge, GraphNode, SourceType } from "../types/domain";

const screens = [
  { id: "live", label: "National Live Feed", tag: "S1" },
  { id: "timeline", label: "Timeline / Indicators", tag: "S2" },
  { id: "graph", label: "Threat Graph Explorer", tag: "S3" },
  { id: "campaigns", label: "Campaign Console", tag: "S4" },
  { id: "infra", label: "Infra & VPN Correlation", tag: "S5" },
  { id: "cases", label: "Case Packet + STIX", tag: "S6" },
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
  const [activeScreen, setActiveScreen] = useState<ScreenId>("live");
  const [timeWindow, setTimeWindow] = useState("1h");
  const [sourceFilters, setSourceFilters] = useState<Record<SourceType, boolean>>(() => {
    return sourceOptions.reduce((acc, source) => {
      acc[source] = true;
      return acc;
    }, {} as Record<SourceType, boolean>);
  });
  const [selectedEntity, setSelectedEntity] = useState(entities[0]);
  const [selectedCampaignId, setSelectedCampaignId] = useState(campaigns[0].id);
  const [selectedClusterId, setSelectedClusterId] = useState(infraClusters[0].id);
  const [selectedServiceId, setSelectedServiceId] = useState(indicators[0].serviceId);
  const [selectedCaseId, setSelectedCaseId] = useState(cases[0]?.id ?? "");
  const [evidence, setEvidence] = useState<EvidenceState>({ open: false, title: "", items: [] });
  const [demoOpen, setDemoOpen] = useState(false);
  const [demoStatus, setDemoStatus] = useState("Idle");
  const [entityQuery, setEntityQuery] = useState("");

  const activeCase = cases.find((item) => item.id === selectedCaseId) ?? cases[0];
  const selectedCampaign = campaigns.find((item) => item.id === selectedCampaignId) ?? campaigns[0];

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
    const entity = entities.find((item) =>
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
    setSelectedCampaignId("CAMP-041");
    setActiveScreen("campaigns");
  };

  const handleShowInfra = () => {
    setSelectedClusterId("CL-07");
    setActiveScreen("infra");
  };

  const handleGraphNode = (node: GraphNode) => {
    const entity = entities.find((item) => item.label.toLowerCase().includes(node.label.toLowerCase()));
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
    } catch {
      setDemoStatus(`Queued ${method} ${path}`);
    }
  };

  const searchOptions = entities.map((entity) => entity.label);

  const handleSearch = (value: string) => {
    setEntityQuery(value);
    const entity = entities.find((item) => item.label === value);
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
          </div>
          <div className="status-badge">Live demo</div>
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
                events={events}
                timeline={timelineCounts}
                activeSources={sourceFilters}
                onSelectEvent={handleSelectEvent}
                onShowGraph={handleShowGraph}
                onShowTimeline={handleShowTimeline}
                onShowEvidence={(title, event) => openEvidence(title, event.evidence)}
              />
            )}
            {activeScreen === "timeline" && (
              <Timeline
                indicators={indicators}
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
                campaigns={campaigns}
                selectedId={selectedCampaignId}
                onSelect={setSelectedCampaignId}
                onOpenGraph={() => setActiveScreen("graph")}
                onGenerateCase={() => {
                  setSelectedCaseId(cases[0]?.id ?? "");
                  handleScenario(`/v1/cases/from-campaign/${selectedCampaignId}`);
                  setActiveScreen("cases");
                }}
                onOpenInfra={() => setActiveScreen("infra")}
                onOpenEvidence={() =>
                  openEvidence(
                    "Campaign evidence",
                    events.slice(0, 3).flatMap((item) => item.evidence.slice(0, 1))
                  )
                }
              />
            )}
            {activeScreen === "infra" && (
              <InfraCorrelation
                clusters={infraClusters}
                selectedId={selectedClusterId}
                onSelect={setSelectedClusterId}
                onOpenGraph={() => setActiveScreen("graph")}
                onOpenEvidence={(cluster) => openEvidence(`Evidence for ${cluster.id}`, cluster.evidence)}
              />
            )}
            {activeScreen === "cases" && (
              <CasePackets
                packet={activeCase}
                onExportJson={() => handleScenario(`/v1/cases/${activeCase?.id ?? "CASE"}`, "GET")}
                onExportStix={() => handleScenario(`/v1/export/stix/case/${activeCase?.id ?? "CASE"}`, "GET")}
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
