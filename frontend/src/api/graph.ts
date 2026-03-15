import { apiFetchJson } from "./client";
import { endpoints } from "./endpoints";

export interface LiveGraphNode {
  id: string;
  label: string;
  type: string;
  risk_score?: number;
  community?: string;
  properties?: Record<string, unknown>;
}

export interface LiveGraphEdge {
  source: string;
  target: string;
  type?: string;
  weight?: number;
  evidence?: string[];
}

export interface GraphNeighboursResponse {
  entity_key: string;
  node?: LiveGraphNode;
  neighbours: LiveGraphNode[];
  edges: LiveGraphEdge[];
  hop_count?: number;
}

export interface GraphPathResponse {
  found: boolean;
  path: LiveGraphNode[];
  edges: LiveGraphEdge[];
  hop_count: number;
}

export async function fetchGraphNeighbours(
  entityKey: string,
  limit = 20,
): Promise<GraphNeighboursResponse | null> {
  try {
    const data = await apiFetchJson<Record<string, unknown>>(
      endpoints.graphNeighbors(entityKey, limit),
    );
    const neighbours = Array.isArray(data.neighbours)
      ? (data.neighbours as LiveGraphNode[])
      : Array.isArray(data.nodes)
        ? (data.nodes as LiveGraphNode[])
        : [];
    const edges = Array.isArray(data.edges) ? (data.edges as LiveGraphEdge[]) : [];
    return {
      entity_key: entityKey,
      node: data.node as LiveGraphNode | undefined,
      neighbours,
      edges,
      hop_count: typeof data.hop_count === "number" ? data.hop_count : neighbours.length,
    };
  } catch {
    return null;
  }
}

export async function fetchGraphPath(
  fromKey: string,
  toKey: string,
  maxHops = 4,
): Promise<GraphPathResponse | null> {
  try {
    const data = await apiFetchJson<Record<string, unknown>>(
      endpoints.graphPath(fromKey, toKey, maxHops),
    );
    const path = Array.isArray(data.path) ? (data.path as LiveGraphNode[]) : [];
    const edges = Array.isArray(data.edges) ? (data.edges as LiveGraphEdge[]) : [];
    return {
      found: Boolean(data.found ?? path.length > 0),
      path,
      edges,
      hop_count: typeof data.hop_count === "number" ? data.hop_count : path.length,
    };
  } catch {
    return null;
  }
}

export async function fetchRecentCases(
  limit = 20,
): Promise<Array<Record<string, unknown>>> {
  try {
    const data = await apiFetchJson<{ items: Array<Record<string, unknown>> }>(
      endpoints.casesRecent(limit),
    );
    return data.items ?? [];
  } catch {
    return [];
  }
}
