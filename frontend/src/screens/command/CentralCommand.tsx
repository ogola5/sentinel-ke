import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  Database,
  Globe,
  Loader,
  Network,
  Radio,
  RefreshCw,
  Shield,
  TrendingUp,
  Users,
} from "lucide-react";

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

function CommandStat({
  label,
  value,
  icon,
  tone,
}: {
  label: string;
  value: number | string;
  icon: ReactNode;
  tone?: string;
}) {
  return (
    <div className="metric-card">
      <div className="metric-label" style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {icon}
        {label}
      </div>
      <div className="metric-value" style={{ color: tone }}>{value}</div>
    </div>
  );
}

export default function CentralCommand({
  operationsData,
  activeCampaignCount,
  activeEventCount,
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
  const blockedGuardrails = operationsData.guardrailDecisions.filter((item) => item.decision === "block");
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
  const cyberGovernance = trustSummary?.model_governance?.find((item) => item.prediction_type === "risk_gnn") ?? null;
  const corruptionGovernance = trustSummary?.model_governance?.find((item) => item.prediction_type === "corruption_risk") ?? null;
  const hasPlatformHealth = Object.keys(healthPlatformStatus).length > 0;
  const schemaContractOk = hasPlatformHealth && healthPlatformStatus.schema_contract_ok === true;
  const schemaMissingCount = Number(healthPlatformStatus.schema_missing_count ?? 0);
  const federationSignedRequired = hasPlatformHealth && healthPlatformStatus.federation_signed_requests_required === true;
  const legalAnchorIntegrity = hasPlatformHealth ? String(healthPlatformStatus.legal_anchor_integrity ?? "unknown") : "unknown";
  const legalAnchorModes =
    healthPlatformStatus.legal_anchor_modes && typeof healthPlatformStatus.legal_anchor_modes === "object"
      ? (healthPlatformStatus.legal_anchor_modes as Record<string, unknown>)
      : {};
  const viewGuide =
    view === "brief"
      ? {
          title: "How to use National Brief",
          steps: [
            "Start with the national threat level banner.",
            "Open only one queue that needs attention first.",
            "Move to Campaigns, Operations, or GNN only after the brief is clear.",
          ],
        }
      : view === "network"
        ? {
            title: "How to use Agency Network",
            steps: [
              "Check which agencies are active first.",
              "Review cross-agency correlations second.",
              "Use this page to coordinate, not to do deep entity analysis.",
            ],
          }
        : {
            title: "How to use Readiness",
            steps: [
              "Check identity and model readiness first.",
              "Record backup or restore evidence in Resilience operations.",
              "Run a drift check when governance looks stale or risky.",
            ],
          };

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
            A lean national view: first understand the threat level, then the network, then readiness.
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

      <div
        className="panel"
        style={{
          borderColor: nationalThreat.color,
          background: `${nationalThreat.color}10`,
        }}
      >
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div>
            <p className="label">National threat level</p>
            <p style={{ fontSize: "2.2rem", fontWeight: 800, color: nationalThreat.color, margin: "2px 0" }}>
              {nationalThreat.level}
            </p>
            <p className="muted">{nationalThreat.note}</p>
          </div>

          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginLeft: "auto" }}>
            <CommandStat label="Campaigns" value={activeCampaignCount} icon={<Radio size={13} />} tone="var(--warning)" />
            <CommandStat label="Live events" value={activeEventCount} icon={<Activity size={13} />} tone="var(--info)" />
            <CommandStat label="High-risk AI queue" value={highRiskPredictions.length} icon={<AlertTriangle size={13} />} tone="var(--risk-high)" />
            <CommandStat label="Cross-agency hits" value={correlations.length} icon={<Network size={13} />} tone="var(--accent)" />
          </div>
        </div>
      </div>

      <div className="panel" style={{ background: "rgba(var(--info-rgb), 0.08)", borderColor: "rgba(var(--info-rgb), 0.22)" }}>
        <div className="panel-header">
          <h3>{viewGuide.title}</h3>
          <span className="muted">Keep this workspace calm and sequential</span>
        </div>
        <div className="list">
          {viewGuide.steps.map((item, index) => (
            <div key={item} className="list-item">
              <strong>Step {index + 1}</strong>
              <p className="muted" style={{ marginTop: 4 }}>{item}</p>
            </div>
          ))}
        </div>
      </div>

      {view === "brief" && (
        <>
          <div className="metric-grid">
            <CommandStat
              label="Forecast"
              value={forecast.forecast_score != null ? `${formatRiskScore(forecast.forecast_score)} / 100` : "No forecast"}
              icon={<TrendingUp size={13} />}
              tone={forecast.trend === "rising" ? "var(--risk-high)" : "var(--accent)"}
            />
            <CommandStat
              label="Critical campaign queue"
              value={threatSummaryData.campaign_risk.critical}
              icon={<AlertTriangle size={13} />}
              tone="var(--risk-critical)"
            />
            <CommandStat
              label="Leakage alerts"
              value={operationsData.leakageSummary.totalAlerts}
              icon={<Shield size={13} />}
              tone="var(--warning)"
            />
            <CommandStat
              label="Guardrail blocks"
              value={blockedGuardrails.length}
              icon={<Shield size={13} />}
              tone="var(--risk-critical)"
            />
          </div>

          <div className="grid-two">
            <div className="panel">
              <div className="panel-header">
                <h3>What needs attention first</h3>
                <span className="muted">One queue at a time</span>
              </div>
              <div className="list">
                <div className="list-item">
                  <p style={{ fontWeight: 600, marginBottom: 4 }}>AI high-risk review queue</p>
                  <p className="muted">
                    {highRiskPredictions.length} entities are above the operational review threshold.
                  </p>
                  <button className="ghost" type="button" onClick={() => onNavigate("gnn")}>
                    Open GNN Intelligence
                  </button>
                </div>
                <div className="list-item">
                  <p style={{ fontWeight: 600, marginBottom: 4 }}>Campaign escalation</p>
                  <p className="muted">
                    {threatSummaryData.campaign_risk.critical} critical and {threatSummaryData.campaign_risk.high} high campaign indicators are active.
                  </p>
                  <button className="ghost" type="button" onClick={() => onNavigate("campaigns")}>
                    Open Campaigns
                  </button>
                </div>
                <div className="list-item">
                  <p style={{ fontWeight: 600, marginBottom: 4 }}>Operational integrity</p>
                  <p className="muted">
                    {operationsData.integrityAlerts.length} integrity alerts and KES{" "}
                    {operationsData.leakageSummary.suspectedAmountTotal.toLocaleString()} suspected leakage in the current window.
                  </p>
                  <button className="ghost" type="button" onClick={() => onNavigate("ops")}>
                    Open Operations
                  </button>
                </div>
              </div>
            </div>

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
          </div>
        </>
      )}

      {view === "network" && (
        <>
          <div className="panel">
            <div className="panel-header">
              <h3>Agency network status</h3>
              <span className="muted">{onlinePartnerIds.size} / {ALL_AGENCIES.length} active partners</span>
            </div>
            <div className="agency-presence-grid">
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

          <div className="grid-two">
            <div className="panel">
              <div className="panel-header">
                <h3>Cross-agency correlations</h3>
                <span className="muted">{correlations.length} active matches</span>
              </div>
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
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3>Partner coverage</h3>
                <span className="muted">Active user footprint</span>
              </div>
              <div className="list">
                {agencyUserCounts.length === 0 ? (
                  <div className="state-box">
                    <Users size={22} />
                    <p>No active agency users found.</p>
                  </div>
                ) : (
                  agencyUserCounts.slice(0, 8).map((item) => (
                    <div key={item.code} className="list-item" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div>
                        <p style={{ fontWeight: 600, marginBottom: 2 }}>{item.label}</p>
                        <p className="muted">{agencyName(item.code)}</p>
                      </div>
                      <span className="stat mono">{item.count}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {view === "readiness" && (
        <div className="grid-three">
          <div className="panel">
            <div className="panel-header">
              <h3>Identity readiness</h3>
              <span className="muted">People and access</span>
            </div>
            <div className="list">
              <div className="list-item"><strong>{centralUsers}</strong> central users</div>
              <div className="list-item"><strong>{sectionUsers}</strong> agency users</div>
              <div className="list-item"><strong>{mfaEnabled}</strong> MFA-enrolled users</div>
              <div className="list-item"><strong>{lockedCount}</strong> locked accounts</div>
            </div>
            <button className="ghost" type="button" onClick={() => onNavigate("users")}>
              Open User Management
            </button>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Model readiness</h3>
              <span className="muted">AI and explainability</span>
            </div>
            <div className="list">
              <div className="list-item"><strong>{healthGnnLoaded ? "Loaded" : "Offline"}</strong> primary GNN artifact</div>
              <div className="list-item"><strong>{healthModelVersion ?? "—"}</strong> active model version</div>
              <div className="list-item"><strong>{operationsData.predictions.length}</strong> predictions in current operational snapshot</div>
              <div className="list-item"><strong>{highRiskPredictions.length}</strong> predictions above operational threshold</div>
            </div>
            <button className="ghost" type="button" onClick={() => onNavigate("gnn")}>
              Open GNN Intelligence
            </button>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>AI trust and operations</h3>
              <span className="muted">Freshness, governance, response, resilience</span>
            </div>
            {trustSummary ? (
              <>
                <div className="list">
                  <div className="list-item">
                    <strong style={{ color: trustTone }}>{trustSummary.overall_status.toUpperCase()}</strong>
                    <p className="muted" style={{ marginTop: 4 }}>{trustSummary.headline}</p>
                  </div>
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
                    <strong>{trustSummary.resilience.backup_attestations_30d}</strong> backup attestations in 30d
                  </div>
                  <div className="list-item">
                    <strong>{cyberGovernance?.real_ratio != null ? `${Math.round(cyberGovernance.real_ratio * 100)}%` : "—"}</strong> cyber real-signal ratio
                  </div>
                  <div className="list-item">
                    <strong>{corruptionGovernance?.real_ratio != null ? `${Math.round(corruptionGovernance.real_ratio * 100)}%` : "—"}</strong> corruption real-signal ratio
                  </div>
                  <div className="list-item">
                    <strong>{(cyberGovernance?.feedback_override_count ?? 0) + (corruptionGovernance?.feedback_override_count ?? 0)}</strong> analyst feedback overrides in model runs
                  </div>
                </div>
                <div className="panel-subsection">
                  <h4>Trust checks</h4>
                  <div className="list">
                    {trustSummary.checks.slice(0, 4).map((item) => (
                      <div key={item.label} className="list-item">
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                          <strong>{item.label}</strong>
                          <span style={{ color: item.status === "pass" ? "var(--accent)" : item.status === "fail" ? "var(--risk-critical)" : "var(--warning)" }}>
                            {item.status.toUpperCase()}
                          </span>
                        </div>
                        <p className="muted" style={{ marginTop: 4 }}>{item.detail}</p>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="panel-subsection">
                  <h4>Model data realism</h4>
                  <div className="list">
                    {[cyberGovernance, corruptionGovernance].filter(Boolean).map((item) => (
                      <div key={item?.prediction_type} className="list-item">
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                          <strong>{item?.prediction_type}</strong>
                          <span>{item?.status?.toUpperCase()}</span>
                        </div>
                        <p className="muted" style={{ marginTop: 4 }}>
                          Real ratio {item?.real_ratio != null ? `${Math.round(item.real_ratio * 100)}%` : "—"} ·
                          Avg per-node real signal {item?.avg_real_signal_ratio != null ? ` ${Math.round(item.avg_real_signal_ratio * 100)}%` : " —"} ·
                          Feedback overrides {item?.feedback_override_count ?? 0}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <div className="list-item">
                <Database size={14} />
                <p className="muted" style={{ margin: 0 }}>Trust summary is unavailable right now.</p>
              </div>
            )}
            <button className="ghost" type="button" onClick={() => onNavigate("reports")}>
              Open Reports
            </button>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Platform integrity</h3>
              <span className="muted">Schema, federation auth, evidence anchoring</span>
            </div>
            <div className="list">
              <div className="list-item">
                <strong style={{ color: schemaContractOk ? "var(--accent)" : "var(--risk-critical)" }}>
                  {!hasPlatformHealth ? "Schema status loading" : schemaContractOk ? "Schema clean" : "Schema drift detected"}
                </strong>
                <p className="muted" style={{ marginTop: 4 }}>
                  {!hasPlatformHealth
                    ? "Waiting for platform health data."
                    : schemaContractOk
                      ? "No required columns are missing on startup health checks."
                      : `${schemaMissingCount} required columns are missing.`}
                </p>
              </div>
              <div className="list-item">
                <strong>
                  {!hasPlatformHealth
                    ? "Federation policy loading"
                    : federationSignedRequired
                      ? "Signed federation requests required"
                      : "Unsigned partner requests still allowed"}
                </strong>
                <p className="muted" style={{ marginTop: 4 }}>
                  Edge payloads must include HMAC signatures before the hub accepts them.
                </p>
              </div>
              <div className="list-item">
                <strong>
                  {legalAnchorIntegrity === "live"
                    ? "Live evidence anchoring"
                    : legalAnchorIntegrity === "simulated"
                      ? "Simulated evidence anchoring"
                      : legalAnchorIntegrity === "disabled"
                        ? "Evidence anchoring disabled"
                        : legalAnchorIntegrity === "partial"
                          ? "Partial evidence anchoring"
                          : "Anchoring status unknown"}
                </strong>
                <p className="muted" style={{ marginTop: 4 }}>
                  MinIO {String(legalAnchorModes.minio ?? "unknown")} · immudb {String(legalAnchorModes.immudb ?? "unknown")}
                </p>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Resilience operations</h3>
              <span className="muted">Record backup and restore evidence</span>
            </div>
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
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Model drift operations</h3>
              <span className="muted">Run and inspect drift governance</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, alignItems: "end" }}>
              <div>
                <p className="label" style={{ marginBottom: 6 }}>Prediction type</p>
                <select value={driftPredictionType} onChange={(event) => setDriftPredictionType(event.target.value as "risk_gnn" | "corruption_risk")} style={{ width: "100%" }}>
                  <option value="risk_gnn">risk_gnn</option>
                  <option value="corruption_risk">corruption_risk</option>
                </select>
              </div>
              <button className="chip active" type="button" disabled={opsBusy} onClick={() => void handleRunDriftCheck()}>
                Run drift check
              </button>
            </div>
            {driftStatus && <p className="muted" style={{ marginTop: 10 }}>{driftStatus}</p>}
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
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Economic integrity</h3>
              <span className="muted">Public-sector risk</span>
            </div>
            <div className="list">
              <div className="list-item"><strong>{operationsData.procurementAnomalies.length}</strong> procurement anomalies</div>
              <div className="list-item"><strong>{operationsData.integrityAlerts.length}</strong> integrity alerts</div>
              <div className="list-item"><strong>{operationsData.leakageSummary.totalAlerts}</strong> leakage alerts</div>
              <div className="list-item">
                <strong>KES {operationsData.leakageSummary.suspectedAmountTotal.toLocaleString()}</strong> suspected amount
              </div>
            </div>
            <button className="ghost" type="button" onClick={() => onNavigate("reports")}>
              Open Reports
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
