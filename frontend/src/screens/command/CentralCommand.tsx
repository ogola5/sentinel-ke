import { useEffect, useMemo, useState } from "react";
import {
  Database,
  Globe,
  Loader,
  Network,
  RefreshCw,
  Shield,
  TrendingUp,
  Users,
} from "lucide-react";

import ArchitectureFlow from "../../app/ArchitectureFlow";
import ScenarioLauncher from "../../components/ScenarioLauncher";
import { fetchFederationCorrelations, fetchFederationPartners } from "../../api/federation";
import { apiListUsers } from "../../api/auth";
import { fetchDriftReports, fetchPlatformTrustSummary, runDriftCheck } from "../../api/ai";
import {
  createRestoreDrill,
  fetchBackupAttestations,
  fetchRestoreDrills,
  upsertBackupAttestation,
} from "../../api/defense";
import { agencyColor, agencyName, type AuthUser, KENYA_AGENCIES } from "../../types/auth";
import type { FederationCorrelation, FederationPartner } from "../../types/federation";
import type { AIDriftReport, PlatformTrustSummary } from "../../types/ai";
import type { BackupAttestationRecord, RestoreDrillRecord } from "../../types/defense";
import type { ThreatSummary } from "../../types/domain";
import type { OperationsSnapshot } from "../../types/operations";
import { formatRiskScore, isHighRisk } from "../../utils/risk";

interface Props {
  operationsData: OperationsSnapshot;
  activeCampaignCount: number;
  activeEventCount: number;
  isSyncing: boolean;
  snapshotReady: boolean;
  healthGnnLoaded: boolean;
  healthModelVersion: string | null;
  healthPlatformStatus: Record<string, unknown>;
  threatSummaryData: ThreatSummary;
  onNavigate: (screen: string) => void;
}

type CommandView = "brief" | "network" | "readiness";

const ALL_AGENCIES = Object.keys(KENYA_AGENCIES);

function threatLevel(critCount: number, highCount: number): { level: string; color: string; note: string } {
  if (critCount > 0) {
    return { level: "CRITICAL", color: "var(--risk-critical)", note: "Immediate coordination required." };
  }
  if (highCount > 5) {
    return { level: "HIGH", color: "var(--risk-high)", note: "Elevated cross-agency pressure." };
  }
  if (highCount > 0) {
    return { level: "ELEVATED", color: "var(--risk-medium)", note: "Multiple queues need review." };
  }
  return { level: "GUARDED", color: "var(--accent)", note: "No critical queue is active right now." };
}

export default function CentralCommand({
  operationsData,
  activeCampaignCount,
  activeEventCount,
  isSyncing,
  snapshotReady,
  healthGnnLoaded,
  healthModelVersion,
  healthPlatformStatus,
  threatSummaryData,
  onNavigate,
}: Props) {
  const [view, setView] = useState<CommandView>("brief");
  const [partners, setPartners] = useState<FederationPartner[]>([]);
  const [correlations, setCorrelations] = useState<FederationCorrelation[]>([]);
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [trustSummary, setTrustSummary] = useState<PlatformTrustSummary | null>(null);
  const [driftReports, setDriftReports] = useState<AIDriftReport[]>([]);
  const [backupAttestations, setBackupAttestations] = useState<BackupAttestationRecord[]>([]);
  const [restoreDrills, setRestoreDrills] = useState<RestoreDrillRecord[]>([]);
  const [backupAssetId, setBackupAssetId] = useState("sentinel-primary-db");
  const [backupId, setBackupId] = useState(`backup-${new Date().toISOString().slice(0, 10)}`);
  const [backupImmutable, setBackupImmutable] = useState(true);
  const [backupStatus, setBackupStatus] = useState("healthy");
  const [backupRpoHours, setBackupRpoHours] = useState("24");
  const [restoreSuccess, setRestoreSuccess] = useState(true);
  const [restoreTargetMinutes, setRestoreTargetMinutes] = useState("240");
  const [restoreActualMinutes, setRestoreActualMinutes] = useState("180");
  const [restoreNotes, setRestoreNotes] = useState("");
  const [driftPredictionType, setDriftPredictionType] = useState<"risk_gnn" | "corruption_risk">("risk_gnn");
  const [resilienceStatus, setResilienceStatus] = useState<string | null>(null);
  const [driftStatus, setDriftStatus] = useState<string | null>(null);
  const [opsBusy, setOpsBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const [partnerRows, correlationRows, userRows, trust, driftRows, backupRows, restoreRows] = await Promise.all([
      fetchFederationPartners(),
      fetchFederationCorrelations(20),
      apiListUsers().then((r) => r.items).catch(() => [] as AuthUser[]),
      fetchPlatformTrustSummary(),
      fetchDriftReports(6),
      fetchBackupAttestations(6),
      fetchRestoreDrills(6),
    ]);
    setPartners(partnerRows);
    setCorrelations(correlationRows);
    setUsers(userRows);
    setTrustSummary(trust);
    setDriftReports(driftRows);
    setBackupAttestations(backupRows);
    setRestoreDrills(restoreRows);
    setLoading(false);
  };

  useEffect(() => {
    void load();
  }, []);

  const criticalQueueCount =
    threatSummaryData.campaign_risk.critical +
    operationsData.integrityAlerts.filter((item) => item.severity.toLowerCase() === "critical").length;
  const highQueueCount =
    threatSummaryData.campaign_risk.high +
    operationsData.procurementAnomalies.filter((item) => item.severity.toLowerCase() === "high").length +
    operationsData.predictions.filter((item) => isHighRisk(item.score)).length;
  const nationalThreat = threatLevel(criticalQueueCount, highQueueCount);

  const onlinePartnerIds = new Set(
    partners
      .filter((item) => item.status === "online")
      .map((item) => item.partner_id.toUpperCase()),
  );
  const agencyUserCounts = ALL_AGENCIES.map((code) => ({
    code,
    label: code,
    count: users.filter((user) => user.section_code === code && user.is_active).length,
  })).filter((item) => item.count > 0);

  const topThreats = useMemo(
    () => threatSummaryData.top_threats.slice(0, 6),
    [threatSummaryData.top_threats],
  );
  const forecast = threatSummaryData.forecast;
  const highRiskPredictions = operationsData.predictions.filter((item) => isHighRisk(item.score));
  const mfaEnabled = users.filter((item) => item.mfa_enabled).length;
  const lockedCount = users.filter((item) => item.locked_until).length;
  const centralUsers = users.filter((item) => item.access_level === "central").length;
  const sectionUsers = users.filter((item) => item.access_level === "section").length;
  const trustTone =
    trustSummary?.overall_status === "pass"
      ? "var(--accent)"
      : trustSummary?.overall_status === "fail"
        ? "var(--risk-critical)"
        : "var(--warning)";
  const trustCheckCounts = (trustSummary?.checks ?? []).reduce(
    (acc, check) => {
      acc[check.status] += 1;
      return acc;
    },
    { pass: 0, warn: 0, fail: 0 },
  );
  const cyberGovernance = trustSummary?.model_governance?.find((item) => item.prediction_type === "risk_gnn") ?? null;
  const corruptionGovernance = trustSummary?.model_governance?.find((item) => item.prediction_type === "corruption_risk") ?? null;
  const hasPlatformHealth = Object.keys(healthPlatformStatus).length > 0;
  const schemaContractOk = hasPlatformHealth && healthPlatformStatus.schema_contract_ok === true;
  const schemaMissingCount = Number(healthPlatformStatus.schema_missing_count ?? 0);
  const federationSignedRequired = hasPlatformHealth && healthPlatformStatus.federation_signed_requests_required === true;
  const leadCorrelation = correlations[0] ?? null;
  const topThreatLead = topThreats[0] ?? null;
  const activePartners = onlinePartnerIds.size;
  const attentionPartners = partners.filter((item) => item.status !== "online").length;
  const priorityQueues = [
    {
      title: "AI review queue",
      value: `${highRiskPredictions.length}`,
      note: `${highRiskPredictions.length} entities are above the review threshold and need analyst judgment.`,
      action: "Open GNN Intelligence",
      screen: "gnn",
      tone: "var(--risk-high)",
    },
    {
      title: "Campaign escalation",
      value: `${threatSummaryData.campaign_risk.critical} critical`,
      note: `${threatSummaryData.campaign_risk.high} high campaign indicators are still active across the current window.`,
      action: "Open Campaigns",
      screen: "campaigns",
      tone: "var(--warning)",
    },
    {
      title: "Integrity leakage review",
      value: `KES ${operationsData.leakageSummary.suspectedAmountTotal.toLocaleString()}`,
      note: `${operationsData.integrityAlerts.length} integrity alerts and ${operationsData.leakageSummary.totalAlerts} leakage alerts are open for operational follow-up.`,
      action: "Open Operations",
      screen: "ops",
      tone: "var(--danger)",
    },
  ];
  const readinessHeadline =
    trustSummary?.overall_status === "pass"
      ? "Operationally ready"
      : trustSummary?.overall_status === "fail"
        ? "Readiness gap detected"
        : "Readiness requires attention";
  const readinessSummary =
    trustSummary?.headline ??
    (healthGnnLoaded
      ? "Core analytics are available. Use this view to confirm policy, evidence, and operator readiness."
      : "Core analytics are not currently loaded. Treat this as a platform recovery and readiness issue.");
  const campaignCountDisplay = !snapshotReady && isSyncing ? "…" : String(activeCampaignCount);
  const liveEventCount = activeEventCount > 0 ? activeEventCount : operationsData.metrics.events;
  const eventCountDisplay = !snapshotReady && isSyncing && liveEventCount === 0 ? "…" : String(liveEventCount);
  const handleBackupAttestation = async () => {
    if (!backupAssetId.trim() || !backupId.trim()) return;
    setOpsBusy(true);
    setResilienceStatus(null);
    try {
      await upsertBackupAttestation({
        asset_id: backupAssetId.trim(),
        backup_id: backupId.trim(),
        immutable: backupImmutable,
        status: backupStatus,
        rpo_hours: Number(backupRpoHours) || undefined,
        storage_tier: "warm",
        evidence: { source: "central_command", mode: "manual_attestation" },
      });
      setResilienceStatus("Backup attestation recorded.");
      await load();
    } catch (err) {
      setResilienceStatus(err instanceof Error ? err.message : "backup_attestation_failed");
    } finally {
      setOpsBusy(false);
    }
  };

  const handleRestoreDrill = async () => {
    if (!backupAssetId.trim() || !backupId.trim()) return;
    setOpsBusy(true);
    setResilienceStatus(null);
    try {
      await createRestoreDrill({
        asset_id: backupAssetId.trim(),
        backup_id: backupId.trim(),
        success: restoreSuccess,
        rto_target_minutes: Number(restoreTargetMinutes) || 240,
        rto_actual_minutes: Number(restoreActualMinutes) || undefined,
        notes: restoreNotes.trim() || undefined,
        evidence: { source: "central_command", mode: "manual_restore_drill" },
      });
      setResilienceStatus("Restore drill recorded.");
      await load();
    } catch (err) {
      setResilienceStatus(err instanceof Error ? err.message : "restore_drill_failed");
    } finally {
      setOpsBusy(false);
    }
  };

  const handleRunDriftCheck = async () => {
    setOpsBusy(true);
    setDriftStatus(null);
    try {
      const result = await runDriftCheck(driftPredictionType);
      if (!result) {
        throw new Error("drift_run_failed");
      }
      setDriftStatus(
        `Drift run complete: ${String(result.status ?? "unknown")} · score ${String(result.drift_score ?? "—")}`,
      );
      await load();
    } catch (err) {
      setDriftStatus(err instanceof Error ? err.message : "drift_run_failed");
    } finally {
      setOpsBusy(false);
    }
  };

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">C1</p>
          <h2>National Command Centre</h2>
          <p className="subtle">
            National posture across cyber operations, public-sector integrity, sovereign federation, and operational readiness.
          </p>
        </div>
        <div className="screen-header-actions">
          <div className="chip-row">
            {[
              { id: "brief", label: "National Brief" },
              { id: "network", label: "Agency Network" },
              { id: "readiness", label: "Readiness" },
            ].map((item) => (
              <button
                key={item.id}
                type="button"
                className={view === item.id ? "chip active" : "chip ghost"}
                onClick={() => setView(item.id as CommandView)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button className="ghost" type="button" onClick={() => void load()} disabled={loading}>
            {loading ? <Loader size={14} className="spin" /> : <RefreshCw size={14} />}
            &nbsp;Refresh
          </button>
        </div>
      </div>

      <ArchitectureFlow
        label="Architecture flow"
        title="How this screen should be read"
        summary="Start with agency and partner signals, then read the shared national picture, then assign response priority."
        steps={[
          { stage: "Agency edge", title: "Local detections", detail: "Each agency scores and triages its own telemetry first.", tone: "info" },
          { stage: "Federation hub", title: "Shared warning layer", detail: "The hub aggregates partner freshness and correlation signals.", tone: "accent" },
          { stage: "Command", title: "National posture", detail: "Command sees queue pressure, partner coverage, and cross-agency risk.", tone: "warning" },
          { stage: "Action", title: "Set priorities", detail: "Push analysts toward the next queue, report, or response track.", tone: "danger" },
        ]}
      />

      {view === "brief" && (
        <>
          <div className="focus-layout">
            <div className={`panel focus-hero ${criticalQueueCount > 0 ? "focus-hero-danger" : highQueueCount > 0 ? "focus-hero-warning" : "focus-hero-accent"}`}>
              <p className="focus-kicker">National posture</p>
              <p className="focus-value" style={{ color: nationalThreat.color }}>{nationalThreat.level}</p>
              <p className="focus-copy">
                {nationalThreat.note} {!snapshotReady && isSyncing
                  ? " Live event and campaign counts are still syncing from the backend."
                  : forecast.forecast_score != null
                    ? ` Forecast pressure is ${formatRiskScore(forecast.forecast_score)} / 100 and the current trend is ${forecast.trend}.`
                    : " Forecast data is still building for the current national window."}
              </p>
              <div className="focus-stat-grid">
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Campaigns</div>
                  <div className="focus-stat-value">{campaignCountDisplay}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Live events</div>
                  <div className="focus-stat-value">{eventCountDisplay}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">AI queue</div>
                  <div className="focus-stat-value">{highRiskPredictions.length}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Cross-agency hits</div>
                  <div className="focus-stat-value">{correlations.length}</div>
                </div>
              </div>
            </div>

            <div className="panel priority-stack">
              <div className="panel-header">
                <h3>First moves</h3>
                <span className="muted">One decision queue at a time</span>
              </div>
              {priorityQueues.map((item) => (
                <div key={item.title} className="priority-card">
                  <div className="priority-card-head">
                    <div>
                      <h4 className="priority-card-title">{item.title}</h4>
                      <p className="priority-card-copy">{item.note}</p>
                    </div>
                    <span style={{ color: item.tone, fontWeight: 700, whiteSpace: "nowrap" }}>{item.value}</span>
                  </div>
                  <div className="priority-card-actions">
                    <button className="ghost" type="button" onClick={() => onNavigate(item.screen)}>
                      {item.action}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>National value at a glance</h3>
              <span className="muted">Why this matters beyond a single SOC</span>
            </div>
            <div className="story-rail story-rail-three">
              <div className="story-card">
                <p className="story-card-label">Cross-sector impact</p>
                <h4>{campaignCountDisplay} cyber campaigns · {operationsData.integrityAlerts.length} integrity alerts</h4>
                <p>One operating model spans public services, fraud-linked abuse patterns, and procurement review instead of isolated tools.</p>
              </div>
              <div className="story-card">
                <p className="story-card-label">Sovereign control</p>
                <h4>{federationSignedRequired ? "Signed federation enforced" : "Federation signing needs work"}</h4>
                <p>{schemaContractOk ? "Schema controls are clean at the hub." : `${schemaMissingCount} schema gaps still need remediation.`} Agencies can share governed warning data without forcing raw-data centralization.</p>
              </div>
              <div className="story-card">
                <p className="story-card-label">Deployment velocity</p>
                <h4>{partners.length} partner links · {sectionUsers} agency users</h4>
                <p>Connector-first onboarding means agencies plug existing systems into the workflow instead of rewriting their infrastructure.</p>
              </div>
              <div className="story-card">
                <p className="story-card-label">Public trust</p>
                <h4>{trustCheckCounts.pass} pass · {trustCheckCounts.warn} warn · {trustCheckCounts.fail} fail</h4>
                <p>Evidence paths, human review, fairness gates, and explicit caveats are visible in the workflow instead of hidden behind a score.</p>
              </div>
              <div className="story-card">
                <p className="story-card-label">Operator leverage</p>
                <h4>{eventCountDisplay} events → {operationsData.metrics.anomalies} anomalies → {highRiskPredictions.length} review entities</h4>
                <p>The platform compresses noisy volume into bounded queues and concrete actions, which is where the operational ROI starts.</p>
              </div>
              <div className="story-card">
                <p className="story-card-label">Future-shaping direction</p>
                <h4>{healthGnnLoaded ? "Graph AI live" : "Graph AI offline"} · {trustSummary?.action_readiness.active_webhooks ?? 0} active controls</h4>
                <p>The same graph, GNN, evidence, and containment model can serve cyber defense, fraud response, and public-integrity operations.</p>
              </div>
            </div>
          </div>

          <ScenarioLauncher onNavigate={(screen) => onNavigate(screen)} />

          <div className="grid-two">
            <div className="panel">
              <div className="panel-header">
                <h3>Top threat entities</h3>
                <span className="muted">{topThreats.length} shown</span>
              </div>
              {topThreats.length === 0 ? (
                <div className="state-box">
                  <Globe size={22} />
                  <p>No threat entities available yet.</p>
                </div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Entity</th>
                      <th>Type</th>
                      <th>Score</th>
                      <th>Stage</th>
                      <th>Severity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topThreats.map((item) => (
                      <tr key={item.entity_key}>
                        <td className="mono" style={{ fontSize: "0.78rem" }}>{item.entity_key}</td>
                        <td className="muted">{item.entity_type}</td>
                        <td>{formatRiskScore(item.score)}</td>
                        <td>{item.kill_chain_stage ?? "—"}</td>
                        <td><span className={`risk-badge ${item.severity.toLowerCase()}`}>{item.severity}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="panel priority-stack">
              <div className="panel-header">
                <h3>Why command is watching</h3>
                <span className="muted">Short national brief</span>
              </div>
              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">Forecast pressure</h4>
                    <p className="priority-card-copy">
                      {forecast.forecast_score != null
                        ? `Projected score ${formatRiskScore(forecast.forecast_score)} / 100 with a ${forecast.trend} posture.`
                        : "Forecast signal is not populated yet for this cycle."}
                    </p>
                  </div>
                  <TrendingUp size={16} color={forecast.trend === "rising" ? "var(--risk-high)" : "var(--accent)"} />
                </div>
              </div>
              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">Top flagged entity</h4>
                    <p className="priority-card-copy">
                      {topThreatLead
                        ? `${topThreatLead.entity_key} is ${topThreatLead.severity.toLowerCase()} risk at ${formatRiskScore(topThreatLead.score)} / 100.`
                        : "No top threat entity has been published yet."}
                    </p>
                  </div>
                  {topThreatLead ? <span className={`risk-badge ${topThreatLead.severity.toLowerCase()}`}>{topThreatLead.severity}</span> : null}
                </div>
              </div>
              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">Integrity exposure</h4>
                    <p className="priority-card-copy">
                      {operationsData.integrityAlerts.length} integrity alerts and KES {operationsData.leakageSummary.suspectedAmountTotal.toLocaleString()} suspected leakage remain in the current review window.
                    </p>
                  </div>
                  <Shield size={16} color="var(--warning)" />
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {view === "network" && (
        <>
          <div className="focus-layout">
            <div className="panel focus-hero focus-hero-accent">
              <p className="focus-kicker">Agency coverage</p>
              <p className="focus-value">{activePartners}/{ALL_AGENCIES.length}</p>
              <p className="focus-copy">
                Agencies with healthy partner presence at the hub. Use this view to show who is online, where freshness is weak, and where federation is already producing shared warning value.
              </p>
              <div className="focus-stat-grid">
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Live partners</div>
                  <div className="focus-stat-value">{activePartners}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Need attention</div>
                  <div className="focus-stat-value">{attentionPartners}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Correlations</div>
                  <div className="focus-stat-value">{correlations.length}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Agency users</div>
                  <div className="focus-stat-value">{sectionUsers}</div>
                </div>
              </div>
              <div className="agency-presence-grid" style={{ marginTop: 18 }}>
                {ALL_AGENCIES.map((code) => {
                  const partner = partners.find((item) => item.partner_id.toUpperCase() === code);
                  const online = onlinePartnerIds.has(code);
                  const color = agencyColor(code);
                  return (
                    <div key={code} className={`agency-presence-card ${online ? "online" : "offline"}`}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontFamily: "JetBrains Mono, monospace", fontWeight: 700, color: online ? color : "var(--ink-muted)" }}>
                          {code}
                        </span>
                        <span className={`status-dot ${online ? "live" : "offline"}`} />
                      </div>
                      <div style={{ fontSize: "0.72rem", opacity: 0.7, marginTop: 4 }}>{agencyName(code)}</div>
                      <div className="muted" style={{ marginTop: 6 }}>
                        {partner
                          ? `${partner.status.replace("_", " ")}${partner.last_seen_at ? ` · ${new Date(partner.last_seen_at).toLocaleDateString("en-KE")}` : ""}`
                          : "Not registered"}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="panel priority-stack">
              <div className="panel-header">
                <h3>Cross-agency moment</h3>
                <span className="muted">What command should point to</span>
              </div>
              {leadCorrelation ? (
                <div className="priority-card">
                  <div className="priority-card-head">
                    <div>
                      <h4 className="priority-card-title">{leadCorrelation.partner_count}-partner match</h4>
                      <p className="priority-card-copy">
                        Hash {leadCorrelation.entity_key_hash.slice(0, 16)}… is shared by {leadCorrelation.partner_ids.join(", ")} at {leadCorrelation.max_confidence.toFixed(2)} max confidence.
                      </p>
                    </div>
                    <span className={`risk-badge ${leadCorrelation.risk_level.toLowerCase()}`}>{leadCorrelation.risk_level}</span>
                  </div>
                </div>
              ) : (
                <div className="priority-card">
                  <h4 className="priority-card-title">No shared warning yet</h4>
                  <p className="priority-card-copy">Once two or more agencies publish the same hash family, the correlation layer will surface it here first.</p>
                </div>
              )}

              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">Coverage by operators</h4>
                    <p className="priority-card-copy">Show that the hub has both partner heartbeat coverage and actual human users in agency workflows.</p>
                  </div>
                  <Users size={16} color="var(--accent)" />
                </div>
                <div className="list" style={{ marginTop: 12 }}>
                  {agencyUserCounts.slice(0, 4).map((item) => (
                    <div key={item.code} className="list-item" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div>
                        <strong>{item.label}</strong>
                        <p className="muted" style={{ marginTop: 2 }}>{agencyName(item.code)}</p>
                      </div>
                      <span className="stat mono">{item.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <details className="panel panel-details" open>
            <summary>
              <span>Cross-agency correlations</span>
              <span className="muted">{correlations.length} active matches</span>
            </summary>
            {correlations.length === 0 ? (
              <div className="state-box">
                <Network size={22} />
                <p>No active cross-agency correlations yet.</p>
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Entity hash</th>
                    <th>Partners</th>
                    <th>Risk</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {correlations.slice(0, 8).map((item) => (
                    <tr key={item.entity_key_hash}>
                      <td className="mono" style={{ fontSize: "0.78rem" }}>{item.entity_key_hash.slice(0, 16)}…</td>
                      <td>{item.partner_count} · <span className="muted">{item.partner_ids.join(", ")}</span></td>
                      <td><span className={`risk-badge ${item.risk_level.toLowerCase()}`}>{item.risk_level}</span></td>
                      <td className="muted">{new Date(item.last_seen).toLocaleDateString("en-KE")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </details>
        </>
      )}

      {view === "readiness" && (
        <>
          <div className="focus-layout">
            <div className={`panel focus-hero ${trustSummary?.overall_status === "fail" ? "focus-hero-danger" : trustSummary?.overall_status === "warn" ? "focus-hero-warning" : "focus-hero-accent"}`}>
              <p className="focus-kicker">Operational readiness</p>
              <p className="focus-value" style={{ color: trustTone }}>{readinessHeadline}</p>
              <p className="focus-copy">{readinessSummary}</p>
              <div className="focus-stat-grid">
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Central users</div>
                  <div className="focus-stat-value">{centralUsers}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Agency users</div>
                  <div className="focus-stat-value">{sectionUsers}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">MFA enrolled</div>
                  <div className="focus-stat-value">{mfaEnabled}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Model state</div>
                  <div className="focus-stat-value">{healthGnnLoaded ? "Live" : "Offline"}</div>
                </div>
              </div>
            </div>

            <div className="panel priority-stack">
              <div className="panel-header">
                <h3>Immediate checks</h3>
                <span className="muted">What leadership should confirm</span>
              </div>
              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">Access and oversight</h4>
                    <p className="priority-card-copy">
                      {lockedCount} locked account{lockedCount === 1 ? "" : "s"}, {mfaEnabled} MFA-enrolled users, and {federationSignedRequired ? "signed federation is enforced." : "federation signing still needs enforcement."}
                    </p>
                  </div>
                  <Shield size={16} color="var(--accent)" />
                </div>
                <div className="priority-card-actions">
                  <button className="ghost" type="button" onClick={() => onNavigate("users")}>
                    Open User Management
                  </button>
                </div>
              </div>
              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">Model and schema health</h4>
                    <p className="priority-card-copy">
                      {schemaContractOk ? "Schema contract is clean and ready for operators." : `${schemaMissingCount} required schema fields are still missing.`} Model version is {healthModelVersion ?? "unknown"}.
                    </p>
                  </div>
                  <Database size={16} color={schemaContractOk ? "var(--accent)" : "var(--risk-critical)"} />
                </div>
                <div className="priority-card-actions">
                  <button className="ghost" type="button" onClick={() => onNavigate("gnn")}>
                    Open GNN Intelligence
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="grid-two">
            <details className="panel panel-details" open>
              <summary>
                <span>Trust and model governance</span>
                <span className="muted">Open deeper AI readiness</span>
              </summary>
              {trustSummary ? (
                <>
                  <div className="list">
                    <div className="list-item">
                      <strong>{trustSummary.action_readiness.active_webhooks}</strong> active containment webhooks
                    </div>
                    <div className="list-item">
                      <strong>{trustSummary.action_readiness.executed_actions_24h}</strong> containment actions in 24h
                    </div>
                    <div className="list-item">
                      <strong>{trustSummary.freshness.threat_intel_source_count}</strong> threat-intel sources contributing
                    </div>
                    <div className="list-item">
                      <strong>{cyberGovernance?.real_ratio != null ? `${Math.round(cyberGovernance.real_ratio * 100)}%` : "—"}</strong> cyber real-signal ratio
                    </div>
                    <div className="list-item">
                      <strong>{corruptionGovernance?.real_ratio != null ? `${Math.round(corruptionGovernance.real_ratio * 100)}%` : "—"}</strong> corruption real-signal ratio
                    </div>
                  </div>
                  <div className="panel-subsection">
                    <h4>Recent drift reports</h4>
                    {driftReports.length === 0 ? (
                      <p className="muted">No drift reports recorded yet.</p>
                    ) : (
                      <div className="list">
                        {driftReports.slice(0, 4).map((item) => (
                          <div key={item.id} className="list-item">
                            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                              <strong>{item.prediction_type}</strong>
                              <span
                                style={{
                                  color:
                                    item.status === "critical" || item.status === "fail"
                                      ? "var(--risk-critical)"
                                      : item.status === "warn"
                                        ? "var(--warning)"
                                        : "var(--accent)",
                                }}
                              >
                                {item.status}
                              </span>
                            </div>
                            <p className="muted" style={{ marginTop: 4 }}>
                              {item.model_version} · score {formatRiskScore(item.drift_score)}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="chip-row" style={{ marginTop: 12 }}>
                    <select value={driftPredictionType} onChange={(event) => setDriftPredictionType(event.target.value as "risk_gnn" | "corruption_risk")}>
                      <option value="risk_gnn">risk_gnn</option>
                      <option value="corruption_risk">corruption_risk</option>
                    </select>
                    <button className="chip active" type="button" disabled={opsBusy} onClick={() => void handleRunDriftCheck()}>
                      Run drift check
                    </button>
                  </div>
                  {driftStatus && <p className="muted" style={{ marginTop: 10 }}>{driftStatus}</p>}
                </>
              ) : (
                <div className="list-item">
                  <Database size={14} />
                  <p className="muted" style={{ margin: 0 }}>Trust summary is unavailable right now.</p>
                </div>
              )}
            </details>

            <details className="panel panel-details" open>
              <summary>
                <span>Resilience operations</span>
                <span className="muted">Open backup and restore evidence</span>
              </summary>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div>
                  <p className="label" style={{ marginBottom: 6 }}>Asset ID</p>
                  <input className="search" value={backupAssetId} onChange={(event) => setBackupAssetId(event.target.value)} />
                </div>
                <div>
                  <p className="label" style={{ marginBottom: 6 }}>Backup ID</p>
                  <input className="search" value={backupId} onChange={(event) => setBackupId(event.target.value)} />
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 10 }}>
                <div>
                  <p className="label" style={{ marginBottom: 6 }}>Backup status</p>
                  <select value={backupStatus} onChange={(event) => setBackupStatus(event.target.value)} style={{ width: "100%" }}>
                    <option value="healthy">healthy</option>
                    <option value="degraded">degraded</option>
                    <option value="failed">failed</option>
                  </select>
                </div>
                <div>
                  <p className="label" style={{ marginBottom: 6 }}>RPO hours</p>
                  <input className="search" value={backupRpoHours} onChange={(event) => setBackupRpoHours(event.target.value)} />
                </div>
                <label className="chip ghost" style={{ alignSelf: "end", justifyContent: "center" }}>
                  <input
                    type="checkbox"
                    checked={backupImmutable}
                    onChange={(event) => setBackupImmutable(event.target.checked)}
                    style={{ marginRight: 8 }}
                  />
                  Immutable
                </label>
              </div>
              <div className="chip-row" style={{ marginTop: 12 }}>
                <button className="chip active" type="button" disabled={opsBusy} onClick={() => void handleBackupAttestation()}>
                  Record backup attestation
                </button>
                <button className="chip ghost" type="button" disabled={opsBusy} onClick={() => void handleRestoreDrill()}>
                  Record restore drill
                </button>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 12 }}>
                <div>
                  <p className="label" style={{ marginBottom: 6 }}>Restore result</p>
                  <select value={restoreSuccess ? "success" : "failed"} onChange={(event) => setRestoreSuccess(event.target.value === "success")} style={{ width: "100%" }}>
                    <option value="success">success</option>
                    <option value="failed">failed</option>
                  </select>
                </div>
                <div>
                  <p className="label" style={{ marginBottom: 6 }}>RTO target</p>
                  <input className="search" value={restoreTargetMinutes} onChange={(event) => setRestoreTargetMinutes(event.target.value)} />
                </div>
                <div>
                  <p className="label" style={{ marginBottom: 6 }}>RTO actual</p>
                  <input className="search" value={restoreActualMinutes} onChange={(event) => setRestoreActualMinutes(event.target.value)} />
                </div>
              </div>
              <textarea
                className="search"
                style={{ marginTop: 10, minHeight: 72, resize: "vertical" }}
                placeholder="Restore drill notes"
                value={restoreNotes}
                onChange={(event) => setRestoreNotes(event.target.value)}
              />
              {resilienceStatus && <p className="muted" style={{ marginTop: 10 }}>{resilienceStatus}</p>}
              <div className="panel-subsection">
                <h4>Recent resilience evidence</h4>
                <div className="list">
                  {backupAttestations.slice(0, 3).map((item) => (
                    <div key={item.id} className="list-item">
                      <strong>{item.asset_id}</strong>
                      <p className="muted" style={{ marginTop: 4 }}>
                        {item.backup_id} · {item.status} · immutable {item.immutable ? "yes" : "no"}
                      </p>
                    </div>
                  ))}
                  {restoreDrills.slice(0, 2).map((item) => (
                    <div key={item.id} className="list-item">
                      <strong>{item.asset_id}</strong>
                      <p className="muted" style={{ marginTop: 4 }}>
                        restore {item.success ? "success" : "failed"} · actual {item.rto_actual_minutes ?? "—"} min
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </details>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Economic integrity</h3>
              <span className="muted">Public-sector snapshot</span>
            </div>
            <div className="story-rail">
              <div className="story-card">
                <p className="story-card-label">Procurement</p>
                <h4>{operationsData.procurementAnomalies.length} anomalies</h4>
                <p>Track tender irregularities before they become payment leakage.</p>
              </div>
              <div className="story-card">
                <p className="story-card-label">Integrity</p>
                <h4>{operationsData.integrityAlerts.length} alerts</h4>
                <p>Use this lane for IFMIS, payroll, and internal control review.</p>
              </div>
            </div>
            <div className="priority-card-actions">
              <button className="ghost" type="button" onClick={() => onNavigate("reports")}>
                Open Reports
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
