/**
 * GraphExplorer — S3: Threat Graph Explorer
 *
 * Redesigned for clarity. Any operator, judge, or first-time viewer
 * should understand what they're looking at without explanation.
 *
 * Layout:
 *  - Stats bar (4 numbers at a glance)
 *  - SVG canvas with labeled zone columns + directed edges
 *  - Edge Intelligence panel (human-readable evidence)
 *  - Node Investigation panel (selected node's neighbourhood)
 *  - Collapsible "How to read this" guide
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphData, GraphEdge, GraphNode } from "../types/domain";
import DetailPanel from "../components/DetailPanel";
import { useEventStream } from "../hooks/useEventStream";
import { fetchGraphNeighbours, fetchGraphPath } from "../api/graph";
import type { GraphNeighboursResponse, GraphPathResponse } from "../api/graph";
import { canonicalServiceKey, isCanonicalEntityKey } from "../utils/entityKeys";

const LIVE_WINDOW_MS = 12_000;

// CSS variable names — used directly in SVG (inline SVG inherits the stylesheet)
const COMMUNITY_COLOR: Record<string, string> = {
  target:   "var(--accent)",
  infra:    "var(--accent-2)",
  campaign: "var(--warning)",
  support:  "var(--ink-muted)",
};

// Hex fallbacks for non-SVG elements (span backgrounds, etc.)
const COMMUNITY_HEX: Record<string, string> = {
  target:   "#2fd67d",
  infra:    "#bbf7d2",
  campaign: "#f0bf4c",
  support:  "#abc7b6",
};

const COMMUNITY_LABEL: Record<string, string> = {
  target:   "TARGET SIDE",
  infra:    "ATTACKER INFRASTRUCTURE",
  campaign: "CAMPAIGN GROUPING",
  support:  "SUPPORT",
};

const COMMUNITY_DESC: Record<string, string> = {
  target:   "Services and exposed endpoints receiving hostile activity",
  infra:    "Attacker IPs, clusters, and providers used in the activity",
  campaign: "Operational groupings that tie multiple observations together",
  support:  "Enabler nodes — proxies, registrars, relays",
};

const NODE_ICON: Record<string, string> = {
  service:  "⊞",
  endpoint: "⊞",
  cluster:  "⊛",
  ip:       "⊛",
  asn:      "⊛",
  provider: "⊛",
  campaign: "⚠",
};

// Column X positions match buildGraphFromSnapshot in backend.ts
const ZONE_X: Record<string, number> = {
  target:   130,
  infra:    360,
  campaign: 590,
};

const FULL_ZONES = ["target", "infra", "campaign"] as const;
const OPERATIONAL_ZONES = ["target", "infra"] as const;

function shortLabel(label: string, max = 13): string {
  return label.length > max ? label.slice(0, max - 1) + "…" : label;
}

function readableNodeType(node: GraphNode): string {
  switch (node.type.toLowerCase()) {
    case "service":
      return "target service";
    case "endpoint":
      return "target endpoint";
    case "ip":
      return "attacker IP";
    case "cluster":
      return "infra cluster";
    case "provider":
      return "provider";
    case "campaign":
      return "campaign group";
    default:
      return node.type.toLowerCase();
  }
}

function describeEdge(edge: GraphEdge, nodeById: Map<string, GraphNode>): string {
  const sourceLabel = nodeById.get(edge.source)?.label ?? edge.source;
  const targetLabel = nodeById.get(edge.target)?.label ?? edge.target;
  switch (edge.kind) {
    case "attack_service":
      return `${sourceLabel} was observed attacking service ${targetLabel}.`;
    case "attack_endpoint":
      return `${sourceLabel} was observed targeting endpoint ${targetLabel}.`;
    case "service_endpoint":
      return `${targetLabel} is an exposed endpoint on service ${sourceLabel}.`;
    case "cluster_member":
      return `${targetLabel} belongs to infra cluster ${sourceLabel}.`;
    case "cluster_provider":
      return `${sourceLabel} is associated with provider ${targetLabel}.`;
    case "cluster_target":
      return `${sourceLabel} contains members observed against ${targetLabel}.`;
    case "campaign_link":
      return `${sourceLabel} groups activity linked to ${targetLabel}.`;
    default:
      return `${sourceLabel} is linked to ${targetLabel}.`;
  }
}

function explainNodeMeaning(node: GraphNode, degree: number, live: boolean): string {
  const role = COMMUNITY_DESC[node.community] ?? node.community;
  const liveText = live ? " It has recent live activity in the current window." : "";
  if (node.type.toLowerCase() === "service") {
    return `${node.label} is a target service. In this graph, that means it is a victim-side service receiving hostile pressure or linked attack activity. It currently has ${degree} visible relationship${degree !== 1 ? "s" : ""}.${liveText}`;
  }
  if (node.type.toLowerCase() === "endpoint") {
    return `${node.label} is an exposed endpoint on a target service. It shows where hostile requests are landing. It currently has ${degree} visible relationship${degree !== 1 ? "s" : ""}.${liveText}`;
  }
  if (node.type.toLowerCase() === "ip") {
    return `${node.label} is attacker-side infrastructure. In this graph, an attacker IP means a source that has been observed targeting a service or endpoint. It currently has ${degree} visible relationship${degree !== 1 ? "s" : ""}.${liveText}`;
  }
  if (node.type.toLowerCase() === "cluster") {
    return `${node.label} is an infrastructure cluster. It groups related attacker infrastructure so operators can see whether multiple observations belong to one operational footprint. It currently has ${degree} visible relationship${degree !== 1 ? "s" : ""}.${liveText}`;
  }
  if (node.type.toLowerCase() === "campaign") {
    return `${node.label} is a campaign grouping node. It helps answer whether separate services, endpoints, or attacker infrastructure belong to one broader operation. It currently has ${degree} visible relationship${degree !== 1 ? "s" : ""}.${liveText}`;
  }
  return `${node.label} is shown here as ${readableNodeType(node)}. Its role is ${role}. It currently has ${degree} visible relationship${degree !== 1 ? "s" : ""}.${liveText}`;
}

function explainEdgeMeaning(edge: GraphEdge, nodeById: Map<string, GraphNode>): string {
  const base = describeEdge(edge, nodeById);
  const sources = edge.sources.length > 0 ? ` Sources: ${edge.sources.join(", ")}.` : "";
  const evidence = edge.count > 0 ? ` The link is backed by ${edge.count} observed event${edge.count !== 1 ? "s" : ""}.` : "";
  return `${base}${evidence}${sources}`.trim();
}

function preferredInvestigationKey(node: GraphNode): string | null {
  const normalizedType = node.type.toLowerCase();
  if (normalizedType === "endpoint" && node.id.startsWith("endpoint:")) {
    const raw = node.id.slice("endpoint:".length);
    const splitIndex = raw.indexOf(":");
    if (splitIndex > 0) {
      return canonicalServiceKey(raw.slice(0, splitIndex));
    }
  }
  return isCanonicalEntityKey(node.id) ? node.id : null;
}

function preferredInvestigationLabel(node: GraphNode): string {
  const preferred = preferredInvestigationKey(node);
  if (!preferred) return "Investigate in depth";
  if (preferred !== node.id && node.type.toLowerCase() === "endpoint") {
    return "Investigate parent service";
  }
  return "Investigate in depth";
}

function fmtTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-KE", {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return ts; }
}

function timeAgo(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    if (diff < 60_000)      return "just now";
    if (diff < 3_600_000)   return `${Math.floor(diff / 60_000)}m ago`;
    if (diff < 86_400_000)  return `${Math.floor(diff / 3_600_000)}h ago`;
    return `${Math.floor(diff / 86_400_000)}d ago`;
  } catch { return ts; }
}

const SOURCE_LABEL: Record<string, string> = {
  telco: "📡 Telco",
  bank:  "🏦 Banking",
  gov:   "🏛️ Gov",
  osint: "🌐 OSINT",
  infra: "🖥️ Infra",
};

type GraphExplorerProps = {
  graph: GraphData;
  isSyncing?: boolean;
  snapshotReady?: boolean;
  onSelectNode: (node: GraphNode) => void;
  onSelectEdge: (edge: GraphEdge) => void;
  onInvestigateEntity?: (entityKey: string) => void;
  campaignCount?: number;
};

type GraphViewMode = "operational" | "full";

export default function GraphExplorer({
  graph,
  isSyncing = false,
  snapshotReady = false,
  onSelectNode,
  onSelectEdge,
  onInvestigateEntity,
  campaignCount,
}: GraphExplorerProps) {
  const [viewMode,          setViewMode]          = useState<GraphViewMode>("operational");
  const [selectedEdge,      setSelectedEdge]      = useState<GraphEdge | null>(null);
  const [selectedNode,      setSelectedNode]      = useState<GraphNode | null>(null);
  const [hoveredEdge,       setHoveredEdge]       = useState<GraphEdge | null>(null);
  const [hoveredNode,       setHoveredNode]       = useState<GraphNode | null>(null);
  const [pinned,            setPinned]            = useState<GraphNode[]>([]);
  const [showPath,          setShowPath]          = useState(false);
  const [nodePanel,         setNodePanel]         = useState(false);
  const [showGuide,         setShowGuide]         = useState(false);
  const [focusQuery,        setFocusQuery]        = useState("");
  // Live graph data from Neo4j
  const [liveNeighbours,    setLiveNeighbours]    = useState<GraphNeighboursResponse | null>(null);
  const [neighboursLoading, setNeighboursLoading] = useState(false);
  const [liveGraphNotice,   setLiveGraphNotice]   = useState("");
  // Path finder
  const [pathFromKey,       setPathFromKey]       = useState("");
  const [pathToKey,         setPathToKey]         = useState("");
  const [pathResult,        setPathResult]        = useState<GraphPathResponse | null>(null);
  const [pathLoading,       setPathLoading]       = useState(false);
  const [pathError,         setPathError]         = useState("");

  const [liveServiceIds, setLiveServiceIds] = useState<Set<string>>(new Set());
  const liveTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const { liveEvents, streamStatus } = useEventStream();
  const visibleZones = viewMode === "full" ? FULL_ZONES : OPERATIONAL_ZONES;

  const visibleNodes = useMemo(() => {
    if (viewMode === "full") return graph.nodes;
    return graph.nodes.filter((node) => node.community !== "campaign" && node.community !== "support");
  }, [graph.nodes, viewMode]);

  const visibleNodeIds = useMemo(
    () => new Set(visibleNodes.map((node) => node.id)),
    [visibleNodes],
  );

  const visibleEdges = useMemo(() => {
    if (viewMode === "full") return graph.edges;
    return graph.edges.filter(
      (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target),
    );
  }, [graph.edges, viewMode, visibleNodeIds]);

  useEffect(() => {
    if (liveEvents.length === 0) return;
    const newest = liveEvents[0];
    const svcId  = newest.service_id;
    if (!svcId) return;

    const matchingNode = graph.nodes.find(
      (n) => n.id === canonicalServiceKey(svcId) || n.label.toLowerCase().includes(svcId.toLowerCase()),
    );
    if (!matchingNode) return;

    const key = matchingNode.id;
    setLiveServiceIds((prev) => new Set([...prev, key]));

    const existing = liveTimers.current.get(key);
    if (existing) clearTimeout(existing);

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

  useEffect(() => {
    if (selectedNode && !visibleNodeIds.has(selectedNode.id)) {
      setSelectedNode(null);
      setNodePanel(false);
    }
    if (selectedEdge) {
      const stillVisible = visibleEdges.some((edge) => edge.id === selectedEdge.id);
      if (!stillVisible) setSelectedEdge(null);
    }
  }, [selectedEdge, selectedNode, viewMode, visibleEdges, visibleNodeIds]);

  // ── Live graph fetch when a node is selected ───────────────────────────
  async function loadLiveNeighbours(node: GraphNode) {
    if (!isCanonicalEntityKey(node.id)) {
      setLiveNeighbours(null);
      setLiveGraphNotice("Live neighbour lookup is available only for canonical backend entity keys.");
      setNeighboursLoading(false);
      return;
    }
    setNeighboursLoading(true);
    setLiveNeighbours(null);
    setLiveGraphNotice("");
    const result = await fetchGraphNeighbours(node.id);
    setLiveNeighbours(result);
    if (!result) {
      setLiveGraphNotice("Live graph lookup failed for this entity.");
    }
    setNeighboursLoading(false);
  }

  async function focusExternalEntity(entityKey: string) {
    setNeighboursLoading(true);
    setLiveGraphNotice("");
    const result = await fetchGraphNeighbours(entityKey);
    setNeighboursLoading(false);
    if (!result?.node) {
      setLiveNeighbours(null);
      setLiveGraphNotice(`No live graph data is currently available for ${entityKey}.`);
      return;
    }
    const externalNode: GraphNode = {
      id: result.node.id || entityKey,
      label: result.node.label || entityKey,
      type: result.node.type || "Service",
      community: result.node.community || "target",
      x: ZONE_X.target,
      y: 120,
    };
    setSelectedNode(externalNode);
    setNodePanel(true);
    setLiveNeighbours(result);
    setLiveGraphNotice(
      `${externalNode.label} is outside the current overview snapshot, so you are seeing its live graph neighbourhood instead of a canvas-highlighted snapshot node.`,
    );
  }

  function selectNode(node: GraphNode) {
    setSelectedNode(node);
    setNodePanel(true);
    onSelectNode(node);
    void loadLiveNeighbours(node);
  }

  async function focusFirstMatch() {
    const query = focusQuery.trim().toLowerCase();
    if (!query) return;
    const match = graph.nodes.find(
      (node) =>
        node.label.toLowerCase().includes(query) ||
        node.id.toLowerCase().includes(query),
    );
    if (match) {
      selectNode(match);
      return;
    }

    const canonicalGuess = isCanonicalEntityKey(query) ? query : canonicalServiceKey(query);
    await focusExternalEntity(canonicalGuess);
  }

  // ── Path finder ─────────────────────────────────────────────────────────
  async function runPathFinder() {
    if (!pathFromKey.trim() || !pathToKey.trim()) return;
    setPathLoading(true);
    setPathError("");
    setPathResult(null);
    const result = await fetchGraphPath(pathFromKey.trim(), pathToKey.trim());
    if (!result) {
      setPathError("Path query failed — check entity keys");
    } else if (!result.found) {
      setPathError(`No path found between "${pathFromKey}" and "${pathToKey}" within 4 hops`);
    } else {
      setPathResult(result);
    }
    setPathLoading(false);
  }

  const edgePairKey = (source: string, target: string) =>
    source < target ? `${source}::${target}` : `${target}::${source}`;

  const pathEdges = useMemo(() => {
    if (!showPath || !pathResult?.found) return new Set<string>();
    if (pathResult.edges.length > 0) {
      return new Set(pathResult.edges.map((edge) => edgePairKey(edge.source, edge.target)));
    }
    const derived = new Set<string>();
    for (let index = 1; index < pathResult.path.length; index += 1) {
      derived.add(edgePairKey(pathResult.path[index - 1].id, pathResult.path[index].id));
    }
    return derived;
  }, [showPath, pathResult]);

  const nodeById = useMemo(
    () => new Map(visibleNodes.map((n) => [n.id, n])),
    [visibleNodes],
  );

  const nodeDegree = useMemo(() => {
    const deg = new Map<string, number>();
    for (const e of visibleEdges) {
      deg.set(e.source, (deg.get(e.source) ?? 0) + 1);
      deg.set(e.target, (deg.get(e.target) ?? 0) + 1);
    }
    return deg;
  }, [visibleEdges]);

  const neighborEdges = useMemo(() => {
    if (!selectedNode) return [];
    return visibleEdges.filter(
      (e) => e.source === selectedNode.id || e.target === selectedNode.id,
    );
  }, [selectedNode, visibleEdges]);

  const isLive = streamStatus === "live";

  const counts = useMemo(() => {
    const services = graph.nodes.filter((n) => n.type === "Service");
    const endpoints = graph.nodes.filter((n) => n.type === "Endpoint");
    const ips = graph.nodes.filter((n) => n.type === "IP");
    const clusters = graph.nodes.filter((n) => n.type === "Cluster");
    const providers = graph.nodes.filter((n) => n.type === "Provider");
    const campaignsVisible = graph.nodes.filter((n) => n.community === "campaign");
    return {
      target: services.length + endpoints.length,
      services: services.length,
      endpoints: endpoints.length,
      infra: ips.length + clusters.length + providers.length,
      ips: ips.length,
      clusters: clusters.length,
      providers: providers.length,
      campaign: campaignsVisible.length,
      campaignTotal: campaignCount ?? campaignsVisible.length,
    };
  }, [campaignCount, graph.nodes]);

  const topTargets = useMemo(
    () =>
      graph.nodes
        .filter((node) => node.type === "Service" || node.type === "Endpoint")
        .sort((a, b) => (nodeDegree.get(b.id) ?? 0) - (nodeDegree.get(a.id) ?? 0))
        .slice(0, 3),
    [graph.nodes, nodeDegree],
  );

  const topInfra = useMemo(
    () =>
      graph.nodes
        .filter((node) => node.community === "infra")
        .sort((a, b) => (nodeDegree.get(b.id) ?? 0) - (nodeDegree.get(a.id) ?? 0))
        .slice(0, 4),
    [graph.nodes, nodeDegree],
  );

  const topCampaigns = useMemo(
    () =>
      graph.nodes
        .filter((node) => node.community === "campaign")
        .slice(0, 3),
    [graph.nodes],
  );

  const selectedNeighborhood = useMemo(() => {
    if (!selectedNode) return null;
    const connected = new Set<string>([selectedNode.id]);
    for (const edge of visibleEdges) {
      if (edge.source === selectedNode.id) connected.add(edge.target);
      if (edge.target === selectedNode.id) connected.add(edge.source);
    }
    return connected;
  }, [visibleEdges, selectedNode]);

  const hoverExplanation = useMemo(() => {
    if (hoveredEdge) {
      return {
        title: "Hovered relationship",
        body: explainEdgeMeaning(hoveredEdge, nodeById),
      };
    }
    if (hoveredNode) {
      return {
        title: "Hovered node",
        body: explainNodeMeaning(
          hoveredNode,
          nodeDegree.get(hoveredNode.id) ?? 0,
          liveServiceIds.has(hoveredNode.id),
        ),
      };
    }
    return {
      title: "How to interpret the graph",
      body: "Hover on a node or relationship to get a plain-English explanation. Click to move from overview into investigation.",
    };
  }, [hoveredEdge, hoveredNode, liveServiceIds, nodeById, nodeDegree]);

  // ── Empty state ──────────────────────────────────────────────────────────
  if (graph.nodes.length === 0) {
    return (
      <section className="screen">
        <div className="screen-header">
          <div>
            <p className="eyebrow">S3</p>
            <h2>Threat Graph Explorer</h2>
            <p className="subtle">Kenya's live cyber-threat relationship map.</p>
          </div>
        </div>
        <div className="panel" style={{ textAlign: "center", padding: "56px 24px" }}>
          <p style={{ fontSize: "2.4rem", marginBottom: 8 }}>🕸️</p>
          <p style={{ fontWeight: 700, fontSize: "1.05rem", marginBottom: 6 }}>
            {!snapshotReady && isSyncing ? "Building threat graph snapshot…" : "No threat graph data yet"}
          </p>
          <p className="muted" style={{ maxWidth: 440, margin: "0 auto", lineHeight: 1.6 }}>
            {!snapshotReady && isSyncing
              ? "The frontend is still hydrating events, campaigns, and infrastructure from the backend. This graph will appear once the first shared snapshot is ready."
              : "Once events are ingested, SentinelKE automatically builds a live relationship map connecting attacked services, attack infrastructure, and threat campaign actors."}
          </p>
        </div>
      </section>
    );
  }

  // ── Main view ─────────────────────────────────────────────────────────────
  return (
    <section className="screen">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="screen-header">
        <div>
          <p className="eyebrow">S3</p>
          <h2>Threat Graph Explorer</h2>
          <p className="subtle">
            Read left to right: who is under attack, which infrastructure is being used, and which campaign groupings are active.
          </p>
        </div>
        <div className="chip-row">
          <span className={`stream-badge ${isLive ? "stream-live" : "stream-poll"}`}>
            <span className={isLive ? "pulse" : ""} />
            {isLive ? "LIVE" : "POLL"}
          </span>
          <button
            className={viewMode === "operational" ? "chip chip-active" : "chip ghost"}
            type="button"
            onClick={() => setViewMode("operational")}
            title="Default judge-safe view: target side and attacker infrastructure first"
          >
            Operational view
          </button>
          <button
            className={viewMode === "full" ? "chip chip-active" : "chip ghost"}
            type="button"
            onClick={() => setViewMode("full")}
            title="Show campaign grouping and full graph context"
          >
            Full graph
          </button>
          {liveServiceIds.size > 0 && (
            <span className="chip chip-active" title="Nodes with a threat event in the last 12 seconds">
              ⚡ {liveServiceIds.size} active node{liveServiceIds.size !== 1 ? "s" : ""}
            </span>
          )}
          <button className="ghost" type="button" onClick={() => { setShowPath(p => !p); setPathResult(null); setPathError(""); }}>
            {showPath ? "Close path finder" : "Find path"}
          </button>
          <button className="ghost" type="button" onClick={() => setShowGuide(g => !g)}>
            {showGuide ? "Hide guide" : "How to read"}
          </button>
        </div>
      </div>

      <div className="panel" style={{
        display: "grid",
        gridTemplateColumns: "1.15fr 1fr 1fr",
        gap: 16,
        alignItems: "start",
      }}>
        <div>
          <p className="label" style={{ marginBottom: 4 }}>Operational reading</p>
          <p style={{ fontWeight: 700, marginBottom: 6 }}>
            Who is attacking whom, through what infrastructure, and under which campaign grouping?
          </p>
          <p className="muted" style={{ fontSize: "0.8rem", lineHeight: 1.55 }}>
            {viewMode === "operational"
              ? "This default view emphasizes the operational picture first: target-side nodes on the left and attacker infrastructure in the middle. Campaign grouping is still counted above and available in Full graph when needed."
              : "This full view adds campaign grouping on the right. Use it when a judge asks how multiple observations are grouped into one broader operation."}
            {" "}
            Click a node to focus the graph. Use <strong>Find path</strong> for live Neo4j path lookup.
          </p>
        </div>
        <div>
          <p className="label" style={{ marginBottom: 4 }}>Focus entity</p>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="input"
              placeholder="Try safaricom, kplc, /login, 203.0.113.8"
              value={focusQuery}
              onChange={(event) => setFocusQuery(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") void focusFirstMatch(); }}
            />
            <button className="ghost" type="button" onClick={() => void focusFirstMatch()}>
              Focus
            </button>
          </div>
          <p className="muted" style={{ fontSize: "0.75rem", marginTop: 6 }}>
            Selecting a node dims unrelated nodes so the attack story is easier to follow.
          </p>
        </div>
        <div>
          <p className="label" style={{ marginBottom: 4 }}>What this screen is best for</p>
          <p className="muted" style={{ fontSize: "0.8rem", lineHeight: 1.55 }}>
            Rapid operator understanding: victim, attacker infrastructure, and grouping. For legal-grade detail, move to Investigate,
            Evidence, or Find path.
          </p>
        </div>
      </div>

      {/* ── Explainer guide (collapsible) ──────────────────────────────────── */}
      {showGuide && (
        <div className="panel" style={{
          background: "rgba(47,214,125,0.05)",
          border: "1px solid rgba(47,214,125,0.18)",
          marginBottom: 0,
        }}>
          <p style={{ fontWeight: 700, marginBottom: 12, fontSize: "0.9rem" }}>How to read the graph</p>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
            gap: 16,
          }}>
            {[
              { icon: "🟢", title: "Target side", body: "Victim services and exposed endpoints receiving hostile traffic or pressure." },
              { icon: "🔵", title: "Attacker infrastructure", body: "Attacker IPs, infrastructure clusters, and providers used in the activity." },
              { icon: "🟡", title: "Campaign grouping", body: "Higher-level operational groupings. These help answer whether separate observations belong to one broader operation." },
              { icon: "↔", title: "Snapshot vs live graph", body: "The canvas is a recent snapshot. Find path and live node connections come from the live Neo4j graph." },
            ].map(item => (
              <div key={item.title}>
                <p style={{ fontWeight: 600, marginBottom: 3, fontSize: "0.85rem" }}>
                  {item.icon} {item.title}
                </p>
                <p className="muted" style={{ fontSize: "0.78rem", lineHeight: 1.5 }}>{item.body}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
        gap: "0.5rem",
      }}>
        <div className="panel" style={{ padding: "12px 14px" }}>
          <p className="label" style={{ marginBottom: 6 }}>Who is under attack</p>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {topTargets.map((node) => (
              <button
                key={node.id}
                type="button"
                className="chip"
                onClick={() => selectNode(node)}
                style={{ cursor: "pointer" }}
                title={`${readableNodeType(node)} · ${nodeDegree.get(node.id) ?? 0} connections`}
              >
                {shortLabel(node.label, 22)}
              </button>
            ))}
          </div>
          <p className="muted" style={{ fontSize: "0.75rem", marginTop: 6 }}>
            {counts.services} services and {counts.endpoints} exposed endpoints are visible in this snapshot.
          </p>
        </div>
        <div className="panel" style={{ padding: "12px 14px" }}>
          <p className="label" style={{ marginBottom: 6 }}>Through what infrastructure</p>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {topInfra.map((node) => (
              <button
                key={node.id}
                type="button"
                className="chip"
                onClick={() => selectNode(node)}
                style={{ cursor: "pointer" }}
                title={`${readableNodeType(node)} · ${nodeDegree.get(node.id) ?? 0} connections`}
              >
                {shortLabel(node.label, 22)}
              </button>
            ))}
          </div>
          <p className="muted" style={{ fontSize: "0.75rem", marginTop: 6 }}>
            {counts.ips} attacker IPs, {counts.clusters} clusters, and {counts.providers} providers are visible.
          </p>
        </div>
        <div className="panel" style={{ padding: "12px 14px" }}>
          <p className="label" style={{ marginBottom: 6 }}>Campaign grouping context</p>
          {viewMode === "full" ? (
            <>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {topCampaigns.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    className="chip"
                    onClick={() => selectNode(node)}
                    style={{ cursor: "pointer" }}
                  >
                    {shortLabel(node.label, 24)}
                  </button>
                ))}
              </div>
              <p className="muted" style={{ fontSize: "0.75rem", marginTop: 6 }}>
                {counts.campaign} groupings are visible on the canvas and {counts.campaignTotal} are active in the wider snapshot.
              </p>
            </>
          ) : (
            <p className="muted" style={{ fontSize: "0.78rem", lineHeight: 1.5 }}>
              {counts.campaignTotal} active campaign grouping{counts.campaignTotal !== 1 ? "s are" : " is"} tracked behind this snapshot.
              Keep this hidden in the first pass. Open <strong>Full graph</strong> only if a judge asks how separate observations are grouped into one operation.
            </p>
          )}
        </div>
      </div>

      {/* ── Path finder panel ──────────────────────────────────────────────── */}
      {showPath && (
        <div className="panel" style={{
          background: "rgba(47,214,125,0.04)",
          border: "1px solid rgba(47,214,125,0.2)",
        }}>
          <p style={{ fontWeight: 700, marginBottom: 10, fontSize: "0.88rem" }}>
            Path Finder — shortest route between two entities (Neo4j)
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ flex: 1, minWidth: 160 }}>
              <p className="label" style={{ marginBottom: 4 }}>From entity key</p>
              <input
                className="input"
                placeholder="e.g. service_id:safaricom or ip:203.0.113.8"
                value={pathFromKey}
                onChange={e => setPathFromKey(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") void runPathFinder(); }}
              />
            </div>
            <div style={{ flex: 1, minWidth: 160 }}>
              <p className="label" style={{ marginBottom: 4 }}>To entity key</p>
              <input
                className="input"
                placeholder="e.g. endpoint:safaricom:/login or service_id:kplc"
                value={pathToKey}
                onChange={e => setPathToKey(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") void runPathFinder(); }}
              />
            </div>
            <button
              className="ghost"
              type="button"
              disabled={pathLoading || !pathFromKey.trim() || !pathToKey.trim()}
              onClick={() => void runPathFinder()}
            >
              {pathLoading ? "Searching…" : "Find path"}
            </button>
          </div>
          {pathError && (
            <p style={{ color: "var(--warning)", fontSize: "0.8rem", marginTop: 8 }}>{pathError}</p>
          )}
          {pathResult && (
            <div style={{ marginTop: 12 }}>
              <p style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: 6 }}>
                Path found — {pathResult.hop_count} hop{pathResult.hop_count !== 1 ? "s" : ""}
              </p>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
                {pathResult.path.map((node, idx) => (
                  <span key={node.id} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <span className="chip" style={{
                      background: (COMMUNITY_HEX[node.community ?? ""] ?? "#abc7b6") + "22",
                      borderColor: (COMMUNITY_HEX[node.community ?? ""] ?? "#abc7b6") + "55",
                    }}>
                      {node.label}
                    </span>
                    {idx < pathResult.path.length - 1 && (
                      <span style={{ color: "var(--ink-muted)" }}>→</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Stats bar ──────────────────────────────────────────────────────── */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
        gap: "0.5rem",
      }}>
        {[
          { label: "Target Side",           value: counts.target,       sub: `${counts.services} services · ${counts.endpoints} endpoints`, color: "#2fd67d" },
          { label: "Attacker Infrastructure", value: counts.infra,      sub: `${counts.ips} IPs · ${counts.clusters} clusters`, color: "#bbf7d2" },
          { label: "Campaign Groupings",    value: counts.campaignTotal, sub: `${counts.campaign} shown on canvas`, color: "#f0bf4c" },
          { label: "Relationships",         value: graph.edges.length,  sub: "evidence-backed links", color: "var(--success)" },
        ].map(stat => (
          <div key={stat.label} className="panel" style={{ padding: "10px 14px" }}>
            <p className="label" style={{ marginBottom: 2 }}>{stat.label}</p>
            <p style={{ fontSize: "1.6rem", fontWeight: 700, color: stat.color, margin: "0 0 2px" }}>
              {stat.value}
            </p>
            <p className="muted" style={{ fontSize: "0.72rem" }}>{stat.sub}</p>
          </div>
        ))}
      </div>

      <div className="panel" style={{ padding: "12px 14px" }}>
        <p className="label" style={{ marginBottom: 4 }}>{hoverExplanation.title}</p>
        <p style={{ margin: 0, lineHeight: 1.55, fontSize: "0.84rem" }}>{hoverExplanation.body}</p>
      </div>

      {/* ── Graph canvas ───────────────────────────────────────────────────── */}
      <div className="panel graph-panel">
        <svg
          className="graph-canvas"
          viewBox="0 0 760 460"
          role="img"
          aria-label="Threat relationship graph showing connections between attacked services, attack infrastructure, and campaigns"
          style={{ height: 460 }}
        >
          <defs>
            {/* Arrowhead markers */}
            <marker id="gr-arrow" markerWidth="7" markerHeight="7" refX="19" refY="3.5" orient="auto">
              <path d="M0,0 L0,7 L7,3.5 z" fill="rgba(171,199,182,0.45)" />
            </marker>
            <marker id="gr-arrow-hot" markerWidth="7" markerHeight="7" refX="19" refY="3.5" orient="auto">
              <path d="M0,0 L0,7 L7,3.5 z" fill="#2fd67d" />
            </marker>
            <marker id="gr-arrow-sel" markerWidth="7" markerHeight="7" refX="19" refY="3.5" orient="auto">
              <path d="M0,0 L0,7 L7,3.5 z" fill="#f0bf4c" />
            </marker>
            {/* Glow filter for live nodes */}
            <filter id="gr-glow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* ── Zone background bands ─────────────────────────────────────── */}
          {visibleZones.map(zone => {
            const cx = ZONE_X[zone];
            const color = COMMUNITY_HEX[zone];
            return (
              <g key={zone}>
                <rect
                  x={cx - 65} y={26} width={130} height={418}
                  rx={10} ry={10}
                  fill={color} fillOpacity={0.045}
                  stroke={color} strokeOpacity={0.14} strokeWidth={1}
                />
                <text
                  x={cx} y={18}
                  textAnchor="middle"
                  fontSize={8.5}
                  fill={color}
                  opacity={0.75}
                  fontWeight={700}
                  letterSpacing={0.8}
                >
                  {COMMUNITY_LABEL[zone]}
                </text>
              </g>
            );
          })}

          <text x={94} y={34} textAnchor="middle" fontSize={8} fill="rgba(47,214,125,0.65)">
            services
          </text>
          <text x={174} y={34} textAnchor="middle" fontSize={8} fill="rgba(47,214,125,0.65)">
            endpoints
          </text>
          <text x={320} y={34} textAnchor="middle" fontSize={8} fill="rgba(187,247,210,0.65)">
            clusters
          </text>
          <text x={408} y={34} textAnchor="middle" fontSize={8} fill="rgba(187,247,210,0.65)">
            attacker IPs
          </text>

          {/* ── Edges ─────────────────────────────────────────────────────── */}
          {visibleEdges.map((edge) => {
            const src = nodeById.get(edge.source);
            const tgt = nodeById.get(edge.target);
            if (!src || !tgt) return null;

            const isHot      = showPath && pathEdges.has(edgePairKey(edge.source, edge.target));
            const isSelected = selectedEdge?.id === edge.id;
            const isRelevant = !selectedNeighborhood
              || selectedNeighborhood.has(edge.source)
              || selectedNeighborhood.has(edge.target)
              || isSelected
              || isHot;
            const weight     = Math.min(5, 1 + Math.log2(edge.count + 1));
            const mx         = (src.x + tgt.x) / 2;
            const my         = (src.y + tgt.y) / 2;

            const stroke     = isSelected ? "#f0bf4c" : isHot ? "#2fd67d" : "rgba(171,199,182,0.32)";
            const strokeW    = isSelected ? 3.5 : isHot ? weight : 1.5;
            const markerEnd  = isSelected ? "url(#gr-arrow-sel)" : isHot ? "url(#gr-arrow-hot)" : "url(#gr-arrow)";

            return (
              <g key={edge.id} style={{ cursor: "pointer", opacity: isRelevant ? 1 : 0.14 }}
                onMouseEnter={() => setHoveredEdge(edge)}
                onMouseLeave={() => setHoveredEdge((current) => (current?.id === edge.id ? null : current))}
                onClick={() => { setSelectedEdge(edge); onSelectEdge(edge); }}
              >
                <title>{`${describeEdge(edge, nodeById)}\n${edge.count} event${edge.count !== 1 ? "s" : ""} · sources: ${edge.sources.join(", ")}`}</title>
                <line
                  x1={src.x} y1={src.y}
                  x2={tgt.x} y2={tgt.y}
                  stroke={stroke}
                  strokeWidth={strokeW}
                  markerEnd={markerEnd}
                />
                {/* Wider invisible hit area */}
                <line
                  x1={src.x} y1={src.y}
                  x2={tgt.x} y2={tgt.y}
                  stroke="transparent"
                  strokeWidth={14}
                />
                {/* Event count badge on edge midpoint */}
                {edge.count > 1 && (
                  <text
                    x={mx} y={my - 4}
                    textAnchor="middle"
                    fontSize={8.5}
                    fill={isSelected ? "#f0bf4c" : isHot ? "#2fd67d" : "rgba(171,199,182,0.55)"}
                    style={{ pointerEvents: "none", fontFamily: "monospace" }}
                  >
                    ×{edge.count}
                  </text>
                )}
              </g>
            );
          })}

          {/* ── Nodes ─────────────────────────────────────────────────────── */}
          {visibleNodes.map((node) => {
            const color       = COMMUNITY_COLOR[node.community] ?? "var(--ink-muted)";
            const hex         = COMMUNITY_HEX[node.community]   ?? "#abc7b6";
            const isLiveNode  = liveServiceIds.has(node.id);
            const isSelected  = selectedNode?.id === node.id;
            const isRelevant  = !selectedNeighborhood || selectedNeighborhood.has(node.id);
            const degree      = nodeDegree.get(node.id) ?? 0;
            const r           = Math.min(23, 14 + degree * 1.4);
            const icon        = NODE_ICON[node.type] ?? "◆";

            return (
              <g
                key={node.id}
                className={`graph-node${isLiveNode ? " graph-node-live" : ""}`}
                style={{ filter: isLiveNode ? "url(#gr-glow)" : undefined, opacity: isRelevant ? 1 : 0.24 }}
                onMouseEnter={() => setHoveredNode(node)}
                onMouseLeave={() => setHoveredNode((current) => (current?.id === node.id ? null : current))}
                onClick={() => selectNode(node)}
              >
                <title>{`${node.label}\nRole: ${COMMUNITY_DESC[node.community] ?? node.community}\nType: ${readableNodeType(node)}\nConnections: ${degree}${isLiveNode ? "\n⚡ LIVE — threat event in last 12s" : ""}`}</title>

                {/* White selection ring */}
                {isSelected && (
                  <circle cx={node.x} cy={node.y} r={r + 7}
                    fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth={2} />
                )}
                {/* Animated live ring */}
                {isLiveNode && (
                  <circle cx={node.x} cy={node.y} r={r + 4}
                    className="graph-node-ring" fill="none" stroke={color} />
                )}
                {/* Main circle */}
                <circle cx={node.x} cy={node.y} r={r} fill={hex} fillOpacity={0.88} />
                {/* Type icon */}
                <text
                  x={node.x} y={node.y + 4}
                  textAnchor="middle"
                  fontSize={11} fill="rgba(10,30,18,0.85)" fontWeight={700}
                  style={{ pointerEvents: "none" }}
                >
                  {icon}
                </text>
                {/* Label */}
                <text
                  x={node.x} y={node.y + r + 14}
                  textAnchor="middle"
                  style={{ pointerEvents: "none", fontSize: "0.68rem" }}
                >
                  {shortLabel(node.label)}
                </text>
                {/* Live indicator dot */}
                {isLiveNode && (
                  <text x={node.x + r - 2} y={node.y - r + 5}
                    className="graph-node-live-dot">●</text>
                )}
                {/* Degree badge for hubs (≥3 connections) */}
                {degree >= 3 && (
                  <g>
                    <circle cx={node.x - r + 4} cy={node.y - r + 4} r={7}
                      fill="rgba(0,0,0,0.55)" />
                    <text
                      x={node.x - r + 4} y={node.y - r + 7}
                      textAnchor="middle"
                      fontSize={8} fill="white" fontWeight={700}
                      style={{ pointerEvents: "none" }}
                    >
                      {degree}
                    </text>
                  </g>
                )}
              </g>
            );
          })}
        </svg>

        {/* Graph footer: legend strip */}
        <div style={{
          display: "flex",
          gap: 16,
          padding: "8px 16px",
          borderTop: "1px solid var(--line)",
          flexWrap: "wrap",
          alignItems: "center",
        }}>
          <span style={{ fontSize: "0.72rem", color: "var(--ink-muted)", marginRight: 4 }}>
            Node types:
          </span>
          {[
            { cls: "dot-target",   label: "Target side",      title: "Victim service or exposed endpoint" },
            { cls: "dot-infra",    label: "Attacker infra",   title: "Attacker IP, cluster, or provider" },
            ...(viewMode === "full"
              ? [{ cls: "dot-campaign", label: "Campaign group", title: "Operation grouping" }]
              : []),
            { cls: "dot-live",     label: "⚡ Live activity", title: "Event in last 12s" },
          ].map(l => (
            <span key={l.cls} className="legend-item" title={l.title}>
              <i className={`dot ${l.cls}`} /> {l.label}
            </span>
          ))}
          <span className="muted" style={{ fontSize: "0.72rem", marginLeft: "auto" }}>
            Hover for details · click to inspect · badge = connection count
          </span>
        </div>
      </div>

      {/* ── Bottom panels ──────────────────────────────────────────────────── */}
      <div className="grid-two">

        {/* Left: Edge Intelligence */}
        <div className="panel">
          <div className="panel-header">
            <h3>Edge Intelligence</h3>
            <span className="muted">
              {selectedEdge ? "Click another line to switch" : "Click any line in the graph above"}
            </span>
          </div>

          {selectedEdge ? (
            <div className="edge-detail">
              {/* Relationship headline */}
              <div style={{
                background: "rgba(47,214,125,0.07)",
                border: "1px solid rgba(47,214,125,0.2)",
                borderRadius: 8,
                padding: "10px 12px",
                marginBottom: 12,
              }}>
                <p className="label" style={{ marginBottom: 4 }}>Relationship</p>
                <p style={{ fontWeight: 700, fontSize: "0.88rem" }}>
                  {describeEdge(selectedEdge, nodeById)}
                </p>
                <p className="muted" style={{ fontSize: "0.76rem", marginTop: 3 }}>
                  {selectedEdge.summary ?? "This line is an observed relationship in the current attack snapshot."}
                </p>
              </div>

              <div className="detail-grid" style={{ marginBottom: 12 }}>
                <div>
                  <p className="label">Observed events</p>
                  <p className="stat" style={{ color: "var(--accent)" }}>{selectedEdge.count}</p>
                </div>
                <div>
                  <p className="label">First detected</p>
                  <p className="stat" style={{ fontSize: "0.8rem" }}>{fmtTs(selectedEdge.first_seen)}</p>
                </div>
                <div>
                  <p className="label">Last seen</p>
                  <p className="stat">{timeAgo(selectedEdge.last_seen)}</p>
                </div>
                <div>
                  <p className="label">Data sources</p>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 3 }}>
                    {selectedEdge.sources.map(s => (
                      <span key={s} className="chip" style={{ fontSize: "0.7rem", padding: "1px 6px" }}>
                        {SOURCE_LABEL[s] ?? s.toUpperCase()}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              {selectedEdge.evidence.length > 0 && (
                <details className="panel panel-details">
                  <summary>
                    <span>Forensic trail</span>
                    <span className="muted">{selectedEdge.evidence.length} event hash{selectedEdge.evidence.length !== 1 ? "es" : ""}</span>
                  </summary>
                  <div className="list" style={{ maxHeight: 110, overflowY: "auto", marginTop: 12 }}>
                    {selectedEdge.evidence.slice(0, 6).map((item) => (
                      <div key={item.event_hash} className="list-item mono"
                        style={{ fontSize: "0.66rem", opacity: 0.65, padding: "4px 8px" }}>
                        {item.event_hash.slice(0, 40)}…
                      </div>
                    ))}
                    {selectedEdge.evidence.length > 6 && (
                      <p className="muted" style={{ fontSize: "0.72rem", padding: "2px 8px" }}>
                        +{selectedEdge.evidence.length - 6} more hashes
                      </p>
                    )}
                  </div>
                </details>
              )}
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: "28px 0", color: "var(--ink-muted)" }}>
              <p style={{ fontSize: "1.8rem", marginBottom: 8 }}>↔</p>
              <p style={{ fontSize: "0.83rem", lineHeight: 1.6 }}>
                Select a connection line in the graph<br />
                to see who is linked and the evidence behind it.
              </p>
            </div>
          )}
        </div>

        {/* Right: Node Investigation */}
        <div className="panel">
          <div className="panel-header">
            <h3>Node Investigation</h3>
            <span className="muted">
              {selectedNode
                ? `${COMMUNITY_LABEL[selectedNode.community] ?? selectedNode.community}`
                : "Click any node to investigate"}
            </span>
          </div>

          {selectedNode ? (
            <div>
              {/* Node identity card */}
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
                <span style={{
                  width: 36, height: 36, borderRadius: "50%",
                  background: COMMUNITY_HEX[selectedNode.community] ?? "#abc7b6",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: "1.1rem", flexShrink: 0, color: "rgba(10,30,18,0.85)",
                  fontWeight: 700,
                }}>
                  {NODE_ICON[selectedNode.type] ?? "◆"}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontWeight: 700, marginBottom: 2, wordBreak: "break-all" }}>
                    {selectedNode.label}
                  </p>
                  <p className="muted" style={{ fontSize: "0.76rem", lineHeight: 1.4 }}>
                    {COMMUNITY_DESC[selectedNode.community] ?? selectedNode.community}
                    {" · "}
                    {readableNodeType(selectedNode)}
                  </p>
                </div>
                {liveServiceIds.has(selectedNode.id) && (
                  <span className="chip chip-active" style={{ fontSize: "0.7rem", flexShrink: 0 }}>
                    ⚡ LIVE
                  </span>
                )}
              </div>

              <div className="detail-grid" style={{ marginBottom: 12 }}>
                <div>
                  <p className="label">Role</p>
                  <p>{COMMUNITY_LABEL[selectedNode.community] ?? selectedNode.community}</p>
                </div>
                <div>
                  <p className="label">Node type</p>
                  <p>{readableNodeType(selectedNode)}</p>
                </div>
                <div>
                  <p className="label">Connections</p>
                  <p style={{ fontWeight: 700, color: "var(--accent)", fontSize: "1.1rem" }}>
                    {nodeDegree.get(selectedNode.id) ?? 0}
                  </p>
                </div>
                <div>
                  <p className="label">Threat status</p>
                  <p>{liveServiceIds.has(selectedNode.id) ? "🔴 Active threat" : "⚪ No recent activity"}</p>
                </div>
              </div>

              {/* Connected entities list */}
              {neighborEdges.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <p className="label" style={{ marginBottom: 6 }}>
                    Connected entities — click to inspect the link
                  </p>
                  <div className="list" style={{ maxHeight: 160, overflowY: "auto" }}>
                    {neighborEdges.map(edge => {
                      const isOutbound = edge.source === selectedNode.id;
                      const otherId    = isOutbound ? edge.target : edge.source;
                      const other      = nodeById.get(otherId);
                      return (
                        <div
                          key={edge.id}
                          className="list-item"
                          style={{
                            display: "flex", justifyContent: "space-between",
                            alignItems: "center", cursor: "pointer", padding: "6px 10px",
                          }}
                          onClick={() => { setSelectedEdge(edge); onSelectEdge(edge); }}
                        >
                          <span style={{ fontSize: "0.8rem", display: "flex", alignItems: "center", gap: 6 }}>
                            <span style={{
                              color: isOutbound ? "var(--accent)" : "var(--warning)",
                              fontWeight: 700, fontSize: "0.9rem",
                            }}>
                              {isOutbound ? "→" : "←"}
                            </span>
                            <span style={{
                              display: "inline-block", width: 8, height: 8,
                              borderRadius: "50%",
                              background: COMMUNITY_HEX[other?.community ?? "support"] ?? "#abc7b6",
                              flexShrink: 0,
                            }} />
                            {other?.label ?? otherId}
                          </span>
                          <span className="muted" style={{ fontSize: "0.72rem" }}>
                            ×{edge.count}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Live Neo4j neighbours */}
              {neighboursLoading && (
                <p className="muted" style={{ fontSize: "0.76rem", marginTop: 4, marginBottom: 8 }}>
                  Loading live connections from graph…
                </p>
              )}
              {!neighboursLoading && liveGraphNotice && (
                <p className="muted" style={{ fontSize: "0.76rem", marginTop: 4, marginBottom: 8 }}>
                  {liveGraphNotice}
                </p>
              )}
              {liveNeighbours && liveNeighbours.neighbours.length > 0 && (
                <details className="panel panel-details" style={{ marginBottom: 12 }}>
                  <summary>
                    <span>Live graph connections</span>
                    <span className="muted">{liveNeighbours.neighbours.length} neighbour{liveNeighbours.neighbours.length !== 1 ? "s" : ""}</span>
                  </summary>
                  <div className="list" style={{ maxHeight: 130, overflowY: "auto", marginTop: 12 }}>
                    {liveNeighbours.neighbours.map(n => (
                      <div key={n.id} className="list-item" style={{ fontSize: "0.78rem", padding: "5px 10px", display: "flex", justifyContent: "space-between" }}>
                        <span>
                          <span style={{
                            display: "inline-block", width: 7, height: 7, borderRadius: "50%",
                            background: COMMUNITY_HEX[n.community ?? "support"] ?? "#abc7b6",
                            marginRight: 7,
                          }} />
                          {n.label}
                        </span>
                        {n.risk_score != null && (
                          <span className="muted" style={{ fontSize: "0.7rem" }}>
                            risk {Math.round(n.risk_score)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </details>
              )}

              {/* Pin / compare */}
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  className="ghost"
                  type="button"
                  onClick={() => setPinned(prev =>
                    prev.find(n => n.id === selectedNode.id)
                      ? prev.filter(n => n.id !== selectedNode.id)
                      : [...prev, selectedNode]
                  )}
                >
                  {pinned.find(n => n.id === selectedNode.id) ? "Unpin" : "📌 Pin for comparison"}
                </button>
                {onInvestigateEntity && preferredInvestigationKey(selectedNode) && (
                  <button
                    className="ghost"
                    type="button"
                    style={{ color: "var(--accent)" }}
                    onClick={() => onInvestigateEntity(preferredInvestigationKey(selectedNode) ?? selectedNode.id)}
                  >
                    🔍 {preferredInvestigationLabel(selectedNode)} →
                  </button>
                )}
                {onInvestigateEntity && !preferredInvestigationKey(selectedNode) && (
                  <p className="muted" style={{ marginTop: 4 }}>
                    This visual helper node does not map to a direct investigation key.
                  </p>
                )}
              </div>

              {pinned.length > 0 && (
                <details className="panel panel-details" style={{ marginTop: 10 }}>
                  <summary>
                    <span>Pinned for comparison</span>
                    <span className="muted">{pinned.length} node{pinned.length !== 1 ? "s" : ""}</span>
                  </summary>
                  <div className="pinned" style={{ marginTop: 12 }}>
                    {pinned.map(node => (
                      <span
                        key={node.id}
                        className="chip"
                        style={{
                          background: COMMUNITY_HEX[node.community] + "1a",
                          borderColor: COMMUNITY_HEX[node.community] + "55",
                          cursor: "pointer",
                        }}
                        title={COMMUNITY_DESC[node.community]}
                        onClick={() => selectNode(node)}
                      >
                        {node.label}
                      </span>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: "28px 0", color: "var(--ink-muted)" }}>
              <p style={{ fontSize: "1.8rem", marginBottom: 8 }}>🔍</p>
              <p style={{ fontSize: "0.83rem", lineHeight: 1.6 }}>
                Click any node in the graph to inspect<br />
                its role, connections, and live status.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── Node detail slide-in panel ─────────────────────────────────────── */}
      <DetailPanel
        open={nodePanel && !!selectedNode}
        title={selectedNode?.label ?? "Node"}
        subtitle={selectedNode
          ? `${COMMUNITY_LABEL[selectedNode.community] ?? selectedNode.community} · ${readableNodeType(selectedNode)}`
          : undefined}
        onClose={() => setNodePanel(false)}
      >
        {selectedNode && (
          <>
            <div className="dp-field-grid">
              <div>
                <p className="label">What is this?</p>
                <p>{COMMUNITY_DESC[selectedNode.community] ?? selectedNode.community}</p>
              </div>
              <div>
                <p className="label">Node type</p>
                <p>{readableNodeType(selectedNode)}</p>
              </div>
              <div>
                <p className="label">Connections</p>
                <p style={{ fontWeight: 700, color: "var(--accent)" }}>
                  {nodeDegree.get(selectedNode.id) ?? 0} linked entities
                </p>
              </div>
              <div>
                <p className="label">Live threat activity</p>
                <p>{liveServiceIds.has(selectedNode.id)
                  ? "⚡ Threat event detected in the last 12 seconds"
                  : "No recent activity detected"}
                </p>
              </div>
              <div>
                <p className="label">Entity ID</p>
                <p className="mono" style={{ fontSize: "0.72rem", wordBreak: "break-all" }}>
                  {selectedNode.id}
                </p>
              </div>
            </div>
            {onInvestigateEntity && preferredInvestigationKey(selectedNode) && (
              <div style={{ marginTop: 14 }}>
                <button
                  className="ghost"
                  type="button"
                  style={{ color: "var(--accent)" }}
                  onClick={() => {
                    setNodePanel(false);
                    onInvestigateEntity(preferredInvestigationKey(selectedNode) ?? selectedNode.id);
                  }}
                >
                  🔍 {preferredInvestigationLabel(selectedNode)} →
                </button>
              </div>
            )}
            {onInvestigateEntity && !preferredInvestigationKey(selectedNode) && (
              <p className="muted" style={{ marginTop: 14 }}>
                This node is derived for graph context only and does not open a direct investigation record.
              </p>
            )}
          </>
        )}
      </DetailPanel>

    </section>
  );
}
