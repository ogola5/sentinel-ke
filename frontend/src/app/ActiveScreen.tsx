import { Suspense, lazy } from "react";
import { Loader } from "lucide-react";

import type { Principal } from "../types/auth";
import type {
  Campaign,
  CasePacket,
  EntityProfile,
  EventRecord,
  GraphData,
  GraphEdge,
  GraphNode,
  InfraCluster,
  ServiceIndicator,
  SourceType,
  ThreatSummary,
  TimelinePoint,
} from "../types/domain";
import type { OperationsSnapshot } from "../types/operations";
import type { ScreenId } from "./navigation";

const LiveFeed = lazy(() => import("../screens/LiveFeed"));
const Timeline = lazy(() => import("../screens/Timeline"));
const GraphExplorer = lazy(() => import("../screens/GraphExplorer"));
const Campaigns = lazy(() => import("../screens/Campaigns"));
const InfraCorrelation = lazy(() => import("../screens/InfraCorrelation"));
const CasePackets = lazy(() => import("../screens/CasePackets"));
const OperationsCenter = lazy(() => import("../screens/OperationsCenter"));
const GNNIntelligence = lazy(() => import("../screens/analyze/GNNIntelligence"));
const CryptoPosture = lazy(() => import("../screens/analyze/CryptoPosture"));
const DefenseCenter = lazy(() => import("../screens/respond/DefenseCenter"));
const FederationDashboard = lazy(() => import("../screens/govern/FederationDashboard"));
const CorruptionIntel = lazy(() => import("../screens/govern/CorruptionIntel"));
const AuditLog = lazy(() => import("../screens/govern/AuditLog"));
const CentralCommand = lazy(() => import("../screens/command/CentralCommand"));
const ExecBrief = lazy(() => import("../screens/command/ExecBrief"));
const UserManagement = lazy(() => import("../screens/admin/UserManagement"));
const AgencyOnboarding = lazy(() => import("../screens/admin/AgencyOnboarding"));

function ScreenFallback() {
  return (
    <div className="panel">
      <div className="state-box">
        <Loader size={24} className="spin" />
        <p>Loading workspace…</p>
      </div>
    </div>
  );
}

export default function ActiveScreen({
  activeScreen,
  principal,
  central,
  execute,
  manageUsers,
  operationsData,
  campaignsData,
  eventsData,
  timelineData,
  indicatorsData,
  threatSummaryData,
  infraClustersData,
  entitiesData,
  graphData,
  activeCase,
  selectedCampaignId,
  selectedClusterId,
  selectedServiceId,
  timelineEvidenceRefs,
  sourceFilters,
  healthGnnLoaded,
  healthModelVersion,
  healthGnnMetrics,
  leakageActionLabel,
  onNavigate,
  onSelectEvent,
  onSelectEntity,
  onSelectCampaignId,
  onSelectClusterId,
  onSelectServiceId,
  onOpenEvidence,
  onGenerateCase,
  onOpenCampaignEvidence,
  onRunLeakage,
  onCaseExportJson,
  onCaseExportStix,
}: {
  activeScreen: ScreenId;
  principal: Principal;
  central: boolean;
  execute: boolean;
  manageUsers: boolean;
  operationsData: OperationsSnapshot;
  campaignsData: Campaign[];
  eventsData: EventRecord[];
  timelineData: TimelinePoint[];
  indicatorsData: ServiceIndicator[];
  threatSummaryData: ThreatSummary;
  infraClustersData: InfraCluster[];
  entitiesData: EntityProfile[];
  graphData: GraphData;
  activeCase?: CasePacket;
  selectedCampaignId: string;
  selectedClusterId: string;
  selectedServiceId: string;
  timelineEvidenceRefs: string[];
  sourceFilters: Record<SourceType, boolean>;
  healthGnnLoaded: boolean;
  healthModelVersion: string | null;
  healthGnnMetrics: Record<string, unknown>;
  leakageActionLabel: string;
  onNavigate: (id: ScreenId) => void;
  onSelectEvent: (event: EventRecord) => void;
  onSelectEntity: (entity: EntityProfile) => void;
  onSelectCampaignId: (campaignId: string) => void;
  onSelectClusterId: (clusterId: string) => void;
  onSelectServiceId: (serviceId: string) => void;
  onOpenEvidence: (title: string, items: Array<{ event_hash: string; source: SourceType; detail: string }>) => void;
  onGenerateCase: () => void;
  onOpenCampaignEvidence: () => void;
  onRunLeakage: () => void;
  onCaseExportJson: () => void;
  onCaseExportStix: () => void;
}) {
  return (
    <Suspense fallback={<ScreenFallback />}>
      {activeScreen === "exec" && central && <ExecBrief principal={principal} />}
      {activeScreen === "command" && central && (
        <CentralCommand
          operationsData={operationsData}
          activeCampaignCount={campaignsData.length}
          activeEventCount={eventsData.length}
          healthGnnLoaded={healthGnnLoaded}
          healthModelVersion={healthModelVersion}
          onNavigate={(screen) => onNavigate(screen as ScreenId)}
        />
      )}
      {activeScreen === "onboard" && manageUsers && <AgencyOnboarding />}
      {activeScreen === "users" && manageUsers && <UserManagement />}

      {activeScreen === "live" && (
        <LiveFeed
          events={eventsData}
          timeline={timelineData}
          activeSources={sourceFilters}
          onSelectEvent={onSelectEvent}
          onShowGraph={(event: EventRecord) => {
            onSelectEvent(event);
            onNavigate("graph");
          }}
          onShowTimeline={(event: EventRecord) => {
            onSelectServiceId(event.service_id);
            onNavigate("timeline");
          }}
          onShowEvidence={(title: string, event: EventRecord) => onOpenEvidence(title, event.evidence)}
        />
      )}
      {activeScreen === "timeline" && (
        <Timeline
          indicators={indicatorsData}
          threatSummary={threatSummaryData}
          selectedService={selectedServiceId}
          evidenceRefs={timelineEvidenceRefs}
          onSelectService={onSelectServiceId}
          onOpenCampaign={() => {
            if (campaignsData.length > 0) onSelectCampaignId(campaignsData[0].id);
            onNavigate("campaigns");
          }}
          onShowInfra={() => {
            if (infraClustersData.length > 0) onSelectClusterId(infraClustersData[0].id);
            onNavigate("infra");
          }}
        />
      )}

      {activeScreen === "graph" && (
        <GraphExplorer
          graph={graphData}
          onSelectNode={(node: GraphNode) => {
            const entity = entitiesData.find((item) => item.label.toLowerCase().includes(node.label.toLowerCase()));
            if (entity) onSelectEntity(entity);
          }}
          onSelectEdge={(edge: GraphEdge) => onOpenEvidence(`Edge: ${edge.source} → ${edge.target}`, edge.evidence)}
        />
      )}
      {activeScreen === "gnn" && (
        <GNNIntelligence
          healthGnnLoaded={healthGnnLoaded}
          healthModelVersion={healthModelVersion}
          healthGnnMetrics={healthGnnMetrics}
        />
      )}
      {activeScreen === "crypto" && <CryptoPosture />}

      {activeScreen === "campaigns" && (
        <Campaigns
          campaigns={campaignsData}
          selectedId={selectedCampaignId}
          onSelect={onSelectCampaignId}
          onOpenGraph={() => onNavigate("graph")}
          onGenerateCase={onGenerateCase}
          onOpenInfra={() => onNavigate("infra")}
          onOpenEvidence={onOpenCampaignEvidence}
        />
      )}
      {activeScreen === "infra" && (
        <InfraCorrelation
          clusters={infraClustersData}
          selectedId={selectedClusterId}
          onSelect={onSelectClusterId}
          onOpenGraph={() => onNavigate("graph")}
          onOpenEvidence={(cluster: InfraCluster) => onOpenEvidence(`Evidence: ${cluster.id}`, cluster.evidence)}
        />
      )}

      {activeScreen === "cases" && (
        <CasePackets packet={activeCase} onExportJson={onCaseExportJson} onExportStix={onCaseExportStix} />
      )}
      {activeScreen === "defense" && execute && <DefenseCenter />}

      {activeScreen === "ops" && (
        <OperationsCenter data={operationsData} onRunLeakage={onRunLeakage} leakageActionLabel={leakageActionLabel} />
      )}
      {activeScreen === "corruption" && (
        <CorruptionIntel data={operationsData} onRunLeakage={onRunLeakage} leakageActionLabel={leakageActionLabel} />
      )}
      {activeScreen === "federation" && <FederationDashboard />}
      {activeScreen === "audit" && <AuditLog />}
    </Suspense>
  );
}
