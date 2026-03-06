import { useEffect, useState } from "react";

import { fetchBackendSnapshot } from "../api/backend";
import { apiFetchJson } from "../api/client";
import { endpoints } from "../api/endpoints";
import { emptyOperationsSnapshot, fetchOperationsSnapshot } from "../api/operations";
import type {
  Campaign,
  EntityProfile,
  EventRecord,
  GraphData,
  InfraCluster,
  ServiceIndicator,
  TimelinePoint,
} from "../types/domain";
import type { OperationsSnapshot } from "../types/operations";

const emptyGraph: GraphData = { nodes: [], edges: [] };

export type BackendStatus = "connected" | "degraded" | "offline";

export function useDashboardSync() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("offline");
  const [backendLabel, setBackendLabel] = useState("Waiting for sync…");
  const [syncError, setSyncError] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncNonce, setSyncNonce] = useState(0);

  const [healthGnnLoaded, setHealthGnnLoaded] = useState(false);
  const [healthModelVersion, setHealthModelVersion] = useState<string | null>(null);
  const [healthGnnMetrics, setHealthGnnMetrics] = useState<Record<string, unknown>>({});

  const [eventsData, setEventsData] = useState<EventRecord[]>([]);
  const [timelineData, setTimelineData] = useState<TimelinePoint[]>([]);
  const [indicatorsData, setIndicatorsData] = useState<ServiceIndicator[]>([]);
  const [campaignsData, setCampaignsData] = useState<Campaign[]>([]);
  const [infraClustersData, setInfraClustersData] = useState<InfraCluster[]>([]);
  const [entitiesData, setEntitiesData] = useState<EntityProfile[]>([]);
  const [graphData, setGraphData] = useState<GraphData>(emptyGraph);
  const [operationsData, setOperationsData] = useState<OperationsSnapshot>(emptyOperationsSnapshot);

  useEffect(() => {
    let cancelled = false;

    const sync = async () => {
      setIsSyncing(true);
      setSyncError("");

      try {
        const [snapshot, ops, health] = await Promise.all([
          fetchBackendSnapshot(),
          fetchOperationsSnapshot(),
          apiFetchJson<Record<string, unknown>>(endpoints.health()),
        ]);
        if (cancelled) return;

        setEventsData(snapshot.events);
        setTimelineData(snapshot.timelineCounts);
        setIndicatorsData(snapshot.indicators);
        setCampaignsData(snapshot.campaigns);
        setInfraClustersData(snapshot.infraClusters);
        setEntitiesData(snapshot.entities);
        setGraphData(snapshot.graph);
        setOperationsData(ops);
        setHealthGnnLoaded(Boolean(health.gnn_loaded));
        setHealthModelVersion(typeof health.gnn_model_version === "string" ? health.gnn_model_version : null);
        setHealthGnnMetrics(
          health.gnn_metrics != null && typeof health.gnn_metrics === "object"
            ? (health.gnn_metrics as Record<string, unknown>)
            : {},
        );
        setBackendStatus(snapshot.mode === "live" ? "connected" : "degraded");
        const warnings = snapshot.warnings.length > 0 ? ` · ${snapshot.warnings.join(", ")}` : "";
        setBackendLabel(`${snapshot.connectionLabel}${warnings}`);
      } catch (err) {
        if (cancelled) return;
        setBackendStatus("offline");
        setBackendLabel("Backend unavailable");
        setSyncError(err instanceof Error ? err.message : "backend_unreachable");
      } finally {
        if (!cancelled) setIsSyncing(false);
      }
    };

    void sync();
    const timer = window.setInterval(() => void sync(), 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [syncNonce]);

  return {
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
    triggerSync: () => setSyncNonce((current) => current + 1),
  };
}
