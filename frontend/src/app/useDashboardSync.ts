import { useEffect, useState } from "react";

import { fetchBackendSnapshot } from "../api/backend";
import { ApiError, apiFetchJson } from "../api/client";
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
  ThreatSummary,
} from "../types/domain";
import { emptyThreatSummary } from "../types/domain";
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
  const [threatSummaryData, setThreatSummaryData] = useState<ThreatSummary>(emptyThreatSummary);
  const [operationsData, setOperationsData] = useState<OperationsSnapshot>(emptyOperationsSnapshot);

  useEffect(() => {
    let cancelled = false;

    const sync = async () => {
      setIsSyncing(true);
      setSyncError("");

      try {
        const [snapshotResult, opsResult, healthResult] = await Promise.allSettled([
          fetchBackendSnapshot(),
          fetchOperationsSnapshot(),
          apiFetchJson<Record<string, unknown>>(endpoints.health()),
        ]);
        if (cancelled) return;

        if (snapshotResult.status !== "fulfilled") {
          throw snapshotResult.reason;
        }

        const snapshot = snapshotResult.value;
        const warnings = [...snapshot.warnings];
        let nextStatus: BackendStatus = snapshot.mode === "live" ? "connected" : "degraded";

        setEventsData(snapshot.events);
        setTimelineData(snapshot.timelineCounts);
        setIndicatorsData(snapshot.indicators);
        setCampaignsData(snapshot.campaigns);
        setInfraClustersData(snapshot.infraClusters);
        setEntitiesData(snapshot.entities);
        setGraphData(snapshot.graph);
        setThreatSummaryData(snapshot.threatSummary);

        if (opsResult.status === "fulfilled") {
          setOperationsData(opsResult.value);
        } else {
          setOperationsData(emptyOperationsSnapshot);
          warnings.push("operations limited");
          if (nextStatus === "connected") nextStatus = "degraded";
        }

        if (healthResult.status === "fulfilled") {
          const health = healthResult.value;
          setHealthGnnLoaded(Boolean(health.gnn_loaded));
          setHealthModelVersion(typeof health.gnn_model_version === "string" ? health.gnn_model_version : null);
          setHealthGnnMetrics(
            health.gnn_metrics != null && typeof health.gnn_metrics === "object"
              ? (health.gnn_metrics as Record<string, unknown>)
              : {},
          );
        } else {
          setHealthGnnLoaded(false);
          setHealthModelVersion(null);
          setHealthGnnMetrics({});
          warnings.push("health limited");
          if (nextStatus === "connected") nextStatus = "degraded";
        }

        setBackendStatus(nextStatus);
        setBackendLabel(
          warnings.length > 0 ? `${snapshot.connectionLabel} · ${warnings.join(", ")}` : snapshot.connectionLabel,
        );
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          setBackendStatus("degraded");
          setBackendLabel("Authentication required");
          setSyncError("session_expired");
          return;
        }
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
    threatSummaryData,
    operationsData,
    setOperationsData,
    triggerSync: () => setSyncNonce((current) => current + 1),
  };
}
