import { useMemo, useState } from "react";
import type { GraphData, GraphEdge, GraphNode } from "../types/domain";

type GraphExplorerProps = {
  graph: GraphData;
  onSelectNode: (node: GraphNode) => void;
  onSelectEdge: (edge: GraphEdge) => void;
};

const communityColors: Record<string, string> = {
  target: "var(--accent)",
  infra: "var(--accent-2)",
  campaign: "var(--warning)",
  support: "var(--ink-muted)",
};

const extraNodes: GraphNode[] = [
  { id: "ip-rot-1", label: "45.83.19.33", type: "IP", x: 360, y: 280, community: "infra" },
  { id: "ip-rot-2", label: "45.83.21.55", type: "IP", x: 520, y: 280, community: "infra" },
];

const extraEdges: GraphEdge[] = [
  {
    id: "edge-9",
    source: "ip-rot-1",
    target: "asn-9009",
    evidence: [
      { event_hash: "ev_2c8bde1", source: "infra", detail: "Rotation interval 09:06" },
    ],
    first_seen: "09:06",
    last_seen: "09:08",
    count: 312,
    sources: ["infra"],
  },
  {
    id: "edge-10",
    source: "ip-rot-2",
    target: "asn-9009",
    evidence: [
      { event_hash: "ev_3b8f11d", source: "telco", detail: "Rotation interval 09:08" },
    ],
    first_seen: "09:08",
    last_seen: "09:10",
    count: 288,
    sources: ["telco"],
  },
];

const pathEdges = new Set(["edge-1", "edge-2", "edge-3", "edge-5"]);

export default function GraphExplorer({
  graph,
  onSelectNode,
  onSelectEdge,
}: GraphExplorerProps) {
  const [expanded, setExpanded] = useState(false);
  const [pinned, setPinned] = useState<GraphNode[]>([]);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [showPath, setShowPath] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const data = useMemo<GraphData>(() => {
    if (!expanded) return graph;
    return {
      nodes: [...graph.nodes, ...extraNodes],
      edges: [...graph.edges, ...extraEdges],
    };
  }, [expanded, graph]);

  const nodeById = useMemo(() => {
    return new Map(data.nodes.map((node) => [node.id, node]));
  }, [data.nodes]);

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S3</p>
          <h2>Threat Graph Explorer</h2>
          <p className="subtle">Entity relationships with evidence-grade edges.</p>
        </div>
        <div className="chip-row">
          <button className="ghost" type="button" onClick={() => setExpanded((prev) => !prev)}>
            {expanded ? "Collapse neighbors" : "Expand neighbors"}
          </button>
          <button className="ghost" type="button" onClick={() => setShowPath((prev) => !prev)}>
            {showPath ? "Hide shortest path" : "Highlight shortest path"}
          </button>
        </div>
      </div>

      <div className="panel graph-panel">
        <svg className="graph-canvas" viewBox="0 0 720 420" role="img">
          {data.edges.map((edge) => {
            const source = nodeById.get(edge.source);
            const target = nodeById.get(edge.target);
            if (!source || !target) return null;
            const isPath = showPath && pathEdges.has(edge.id);
            return (
              <line
                key={edge.id}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                className={isPath ? "graph-edge path" : "graph-edge"}
                onClick={() => {
                  setSelectedEdge(edge);
                  onSelectEdge(edge);
                }}
              />
            );
          })}
          {data.nodes.map((node) => {
            const color = communityColors[node.community] ?? "var(--ink)";
            return (
              <g
                key={node.id}
                className="graph-node"
                onClick={() => {
                  setSelectedNode(node);
                  onSelectNode(node);
                }}
              >
                <circle cx={node.x} cy={node.y} r="18" fill={color} />
                <text x={node.x} y={node.y + 34} textAnchor="middle">
                  {node.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>Edge evidence</h3>
            <span className="muted">Click edges to view evidence refs</span>
          </div>
          <div className="legend">
            <span className="legend-item">
              <i className="dot" style={{ background: "var(--accent)" }} /> Targeted service
            </span>
            <span className="legend-item">
              <i className="dot" style={{ background: "var(--accent-2)" }} /> Infra cluster
            </span>
            <span className="legend-item">
              <i className="dot" style={{ background: "var(--warning)" }} /> Campaign
            </span>
          </div>
          {selectedEdge ? (
            <div className="edge-detail">
              <div className="detail-grid">
                <div>
                  <p className="label">First seen</p>
                  <p className="stat">{selectedEdge.first_seen}</p>
                </div>
                <div>
                  <p className="label">Last seen</p>
                  <p className="stat">{selectedEdge.last_seen}</p>
                </div>
                <div>
                  <p className="label">Count</p>
                  <p className="stat">{selectedEdge.count}</p>
                </div>
                <div>
                  <p className="label">Sources</p>
                  <p className="stat">
                    {selectedEdge.sources.map((source) => source.toUpperCase()).join(" / ")}
                  </p>
                </div>
              </div>
              <div className="list">
                {selectedEdge.evidence.map((item) => (
                  <div key={item.event_hash} className="list-item mono">
                    {item.event_hash}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="muted">
              Evidence paths reference event_hash values from the live feed. Pins allow side-by-side
              comparison in the inspector.
            </p>
          )}
        </div>
        <div className="panel">
          <div className="panel-header">
            <h3>Pinned nodes</h3>
            <span className="muted">Pin entities for comparison</span>
          </div>
          <div className="pinned">
            {pinned.length === 0 ? (
              <p className="muted">No nodes pinned yet.</p>
            ) : (
              pinned.map((node) => (
                <span key={node.id} className="chip">
                  {node.label}
                </span>
              ))
            )}
          </div>
          <button
            className="ghost"
            type="button"
            onClick={() => {
              const node = selectedNode ?? graph.nodes[0];
              if (!node) return;
              setPinned((prev) => (prev.find((item) => item.id === node.id) ? prev : [...prev, node]));
            }}
          >
            Pin node
          </button>
        </div>
      </div>
    </section>
  );
}
