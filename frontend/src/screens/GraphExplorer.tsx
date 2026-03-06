/**
 * GraphExplorer — S3: Threat Graph Explorer
 *
 * SVG threat graph with real-time node pulsing via SSE stream.
 * Nodes whose service_id matches a recently-seen SSE event get an
 * animated ring ("live node") — no graph re-layout needed.
 *
 * Click a node → DetailPanel with node details.
 * Click an edge → edge evidence shown in bottom-left panel.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphData, GraphEdge, GraphNode } from "../types/domain";
import DetailPanel from "../components/DetailPanel";
import { useEventStream } from "../hooks/useEventStream";

const LIVE_WINDOW_MS = 12_000;   // node stays "live" for 12 s after an SSE event

const COMMUNITY_COLORS: Record<string, string> = {
  target:   "var(--accent)",
  infra:    "var(--accent-2)",
  campaign: "var(--warning)",
  support:  "var(--ink-muted)",
};

type GraphExplorerProps = {
  graph: GraphData;
  onSelectNode: (node: GraphNode) => void;
  onSelectEdge: (edge: GraphEdge) => void;
};

export default function GraphExplorer({ graph, onSelectNode, onSelectEdge }: GraphExplorerProps) {
  const [pinned,       setPinned]       = useState<GraphNode[]>([]);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [showPath,     setShowPath]     = useState(false);
  const [nodePanel,    setNodePanel]    = useState(false);

  // Track service_ids that had recent SSE events → pulse their graph node
  const [liveServiceIds, setLiveServiceIds] = useState<Set<string>>(new Set());
  const liveTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const { liveEvents, streamStatus } = useEventStream();

  // When new SSE events arrive, mark matching nodes as "live" for LIVE_WINDOW_MS
  useEffect(() => {
    if (liveEvents.length === 0) return;
    const newest = liveEvents[0];
    const svcId  = newest.service_id;
    if (!svcId) return;

    // Check if any graph node matches this service_id
    const matchingNode = graph.nodes.find(
      (n) => n.id === svcId || n.label.toLowerCase().includes(svcId.toLowerCase()),
    );
    if (!matchingNode) return;

    const key = matchingNode.id;

    setLiveServiceIds((prev) => new Set([...prev, key]));

    // Clear existing timer for this node
    const existing = liveTimers.current.get(key);
    if (existing) clearTimeout(existing);

    // Remove from live set after window expires
    const timer = setTimeout(() => {
      setLiveServiceIds((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
      liveTimers.current.delete(key);
    }, LIVE_WINDOW_MS);

    liveTimers.current.set(key, timer);
  }, [liveEvents, graph.nodes]);

  const pathEdges = useMemo(
    () => new Set(graph.edges.slice(0, Math.min(4, graph.edges.length)).map((e) => e.id)),
    [graph.edges],
  );

  const nodeById = useMemo(
    () => new Map(graph.nodes.map((n) => [n.id, n])),
    [graph.nodes],
  );

  const isLive = streamStatus === "live";

  if (graph.nodes.length === 0) {
    return (
      <section className="screen">
        <div className="screen-header">
          <div>
            <p className="eyebrow">S3</p>
            <h2>Threat Graph Explorer</h2>
            <p className="subtle">Entity relationships with evidence-grade edges.</p>
          </div>
        </div>
        <div className="panel">
          <p className="muted">No graph data available yet. Seed data or wait for the backend sync.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="screen">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="screen-header">
        <div>
          <p className="eyebrow">S3</p>
          <h2>Threat Graph Explorer</h2>
          <p className="subtle">Entity relationships · evidence-grade edges · real-time node activity</p>
        </div>
        <div className="chip-row">
          <span className={`stream-badge ${isLive ? "stream-live" : "stream-poll"}`}>
            <span className={isLive ? "pulse" : ""} />
            {isLive ? "LIVE" : "POLL"}
          </span>
          {liveServiceIds.size > 0 && (
            <span className="chip chip-active">
              {liveServiceIds.size} active node{liveServiceIds.size > 1 ? "s" : ""}
            </span>
          )}
          <button className="ghost" type="button" onClick={() => setShowPath((p) => !p)}>
            {showPath ? "Hide top links" : "Highlight top links"}
          </button>
        </div>
      </div>

      {/* ── Graph canvas ───────────────────────────────────────────────── */}
      <div className="panel graph-panel">
        <svg className="graph-canvas" viewBox="0 0 720 420" role="img" aria-label="Threat graph">
          {/* Edges */}
          {graph.edges.map((edge) => {
            const src = nodeById.get(edge.source);
            const tgt = nodeById.get(edge.target);
            if (!src || !tgt) return null;
            const isPath = showPath && pathEdges.has(edge.id);
            return (
              <line
                key={edge.id}
                x1={src.x} y1={src.y}
                x2={tgt.x} y2={tgt.y}
                className={isPath ? "graph-edge path" : "graph-edge"}
                onClick={() => { setSelectedEdge(edge); onSelectEdge(edge); }}
              />
            );
          })}

          {/* Nodes */}
          {graph.nodes.map((node) => {
            const color  = COMMUNITY_COLORS[node.community] ?? "var(--ink)";
            const isLiveNode = liveServiceIds.has(node.id);
            return (
              <g
                key={node.id}
                className={`graph-node${isLiveNode ? " graph-node-live" : ""}`}
                onClick={() => {
                  setSelectedNode(node);
                  setNodePanel(true);
                  onSelectNode(node);
                }}
              >
                {/* Pulsing ring for live nodes */}
                {isLiveNode && (
                  <circle
                    cx={node.x} cy={node.y} r="26"
                    className="graph-node-ring"
                    fill="none"
                    stroke={color}
                  />
                )}
                <circle cx={node.x} cy={node.y} r="18" fill={color} />
                <text x={node.x} y={node.y + 34} textAnchor="middle">
                  {node.label}
                </text>
                {isLiveNode && (
                  <text x={node.x + 14} y={node.y - 14} className="graph-node-live-dot">●</text>
                )}
              </g>
            );
          })}
        </svg>
      </div>

      {/* ── Legend + edge evidence ────────────────────────────────────── */}
      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>Edge evidence</h3>
            <span className="muted">Click edges to view evidence refs</span>
          </div>
          <div className="legend">
            <span className="legend-item"><i className="dot dot-target" /> Target service</span>
            <span className="legend-item"><i className="dot dot-infra" />  Infra cluster</span>
            <span className="legend-item"><i className="dot dot-campaign" /> Campaign</span>
            <span className="legend-item"><i className="dot dot-live" /> Live (SSE event)</span>
          </div>
          {selectedEdge ? (
            <div className="edge-detail">
              <div className="detail-grid">
                <div><p className="label">First seen</p><p className="stat">{selectedEdge.first_seen}</p></div>
                <div><p className="label">Last seen</p><p className="stat">{selectedEdge.last_seen}</p></div>
                <div><p className="label">Count</p><p className="stat">{selectedEdge.count}</p></div>
                <div>
                  <p className="label">Sources</p>
                  <p className="stat">{selectedEdge.sources.map((s) => s.toUpperCase()).join(" / ")}</p>
                </div>
              </div>
              <div className="list">
                {selectedEdge.evidence.map((item) => (
                  <div key={item.event_hash} className="list-item mono">{item.event_hash}</div>
                ))}
              </div>
            </div>
          ) : (
            <p className="muted">Click an edge to view evidence.</p>
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
                <span key={node.id} className="chip">{node.label}</span>
              ))
            )}
          </div>
          <button
            className="ghost"
            type="button"
            onClick={() => {
              const node = selectedNode ?? graph.nodes[0];
              if (!node) return;
              setPinned((prev) =>
                prev.find((n) => n.id === node.id) ? prev : [...prev, node],
              );
            }}
          >
            Pin selected node
          </button>
        </div>
      </div>

      {/* ── Node detail panel ─────────────────────────────────────────── */}
      <DetailPanel
        open={nodePanel && !!selectedNode}
        title={selectedNode?.label ?? "Node"}
        subtitle={selectedNode ? `${selectedNode.community} · ${selectedNode.type}` : undefined}
        onClose={() => setNodePanel(false)}
      >
        {selectedNode && (
          <div className="dp-field-grid">
            <div><p className="label">ID</p><p className="mono">{selectedNode.id}</p></div>
            <div><p className="label">Type</p><p>{selectedNode.type}</p></div>
            <div><p className="label">Community</p><p>{selectedNode.community}</p></div>
            <div>
              <p className="label">Live activity</p>
              <p>{liveServiceIds.has(selectedNode.id) ? "● Active (SSE event)" : "No recent activity"}</p>
            </div>
            <div>
              <p className="label">Edge count</p>
              <p>
                {graph.edges.filter(
                  (e) => e.source === selectedNode.id || e.target === selectedNode.id,
                ).length}
              </p>
            </div>
          </div>
        )}
      </DetailPanel>
    </section>
  );
}
