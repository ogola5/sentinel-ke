import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Loader,
  RefreshCw,
  Shield,
  ShieldAlert,
} from "lucide-react";

import {
  DEFAULT_DEFENSE_ACTIONS,
  executeContainmentAction,
  fetchBackupAttestations,
  fetchContainmentActions,
  fetchDefenseActionCatalog,
  fetchPlaybookRuns,
  fetchRestoreDrills,
  fetchVulnerabilities,
  fetchWebhookDeliveries,
  fetchWebhooks,
} from "../../api/defense";
import type { Principal } from "../../types/auth";
import type {
  BackupAttestationRecord,
  ContainmentActionRecord,
  IncidentActionExecutionResult,
  PlaybookRun,
  RestoreDrillRecord,
  VulnFinding,
  WebhookDeliveryRecord,
  WebhookRecord,
} from "../../types/defense";
import { shortHash } from "../../utils/formatters";
import { displayEntityLabel, isCanonicalEntityKey } from "../../utils/entityKeys";

function severityClass(s: string): string {
  if (s === "critical") return "critical";
  if (s === "high") return "high";
  if (s === "medium") return "medium";
  return "low";
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function fmtStamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ts = new Date(iso).getTime();
  if (!Number.isFinite(ts)) return iso;
  return new Date(ts).toLocaleString("en-KE", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function deliveryStatusClass(status: string | null | undefined): string {
  if (status === "delivered" || status === "executed") return "delivered";
  if (status === "failed") return "failed";
  return "pending";
}

function humanValue(value: string | null | undefined): string {
  const clean = String(value ?? "").trim();
  if (!clean) return "—";
  return isCanonicalEntityKey(clean) ? displayEntityLabel(clean) : clean;
}

function suggestedActionForEntity(entityKey: string | null): string {
  if (!entityKey) return "block_ip";
  if (entityKey.startsWith("service_id:") || entityKey.startsWith("endpoint:") || entityKey.startsWith("domain:") || entityKey.startsWith("url:")) {
    return "enable_waf_challenge";
  }
  if (entityKey.startsWith("ip:")) return "block_ip";
  if (entityKey.startsWith("device_id:") || entityKey.startsWith("host:")) return "isolate_host";
  if (entityKey.startsWith("account:") || entityKey.startsWith("account_h:") || entityKey.startsWith("user:")) return "revoke_user";
  return "block_ip";
}

interface ConfirmState {
  open: boolean;
  runId: string;
  actionType: string;
  target: string;
}

export default function DefenseCenter({ principal }: { principal: Principal }) {
  const [runs, setRuns] = useState<PlaybookRun[]>([]);
  const [actions, setActions] = useState<ContainmentActionRecord[]>([]);
  const [webhooks, setWebhooks] = useState<WebhookRecord[]>([]);
  const [deliveries, setDeliveries] = useState<WebhookDeliveryRecord[]>([]);
  const [backups, setBackups] = useState<BackupAttestationRecord[]>([]);
  const [restoreDrills, setRestoreDrills] = useState<RestoreDrillRecord[]>([]);
  const [vulnerabilities, setVulnerabilities] = useState<VulnFinding[]>([]);
  const [selectedRun, setSelectedRun] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [actionCatalog, setActionCatalog] = useState(DEFAULT_DEFENSE_ACTIONS);
  const [confirm, setConfirm] = useState<ConfirmState>({ open: false, runId: "", actionType: "", target: "" });
  const [targetInput, setTargetInput] = useState("");
  const [actionTypeInput, setActionTypeInput] = useState("block_ip");
  const [executing, setExecuting] = useState(false);
  const [execResult, setExecResult] = useState<string>("");
  const [visibilityNote, setVisibilityNote] = useState<string | null>(null);
  const canInspectWebhooks = principal.access_level === "central";

  const load = async () => {
    setLoading(true);
    setVisibilityNote(null);

    const sectionCode = principal.section_code && principal.section_code !== "central" ? principal.section_code : undefined;

    const [runRows, actionRows, catalogRows, backupRows, drillRows, vulnRows] = await Promise.all([
      fetchPlaybookRuns(20),
      fetchContainmentActions(100),
      fetchDefenseActionCatalog(),
      fetchBackupAttestations(10, sectionCode),
      fetchRestoreDrills(10, sectionCode),
      fetchVulnerabilities(12),
    ]);

    setRuns(runRows);
    setActions(actionRows);
    setActionCatalog(catalogRows);
    setBackups(backupRows);
    setRestoreDrills(drillRows);
    setVulnerabilities(vulnRows);

    if (canInspectWebhooks) {
      try {
        const [hooks, receipts] = await Promise.all([
          fetchWebhooks({ strict: true }),
          fetchWebhookDeliveries(40, { strict: true }),
        ]);
        setWebhooks(hooks);
        setDeliveries(receipts);
      } catch (err) {
        setWebhooks([]);
        setDeliveries([]);
        setVisibilityNote(err instanceof Error ? err.message : "webhook_registry_unavailable");
      }
    } else {
      setWebhooks([]);
      setDeliveries([]);
      setVisibilityNote("Webhook registry and delivery receipts are visible only to central command users.");
    }

    if (runRows.length > 0) {
      const hasCurrentSelection = selectedRun && runRows.some((run) => run.id === selectedRun);
      if (!hasCurrentSelection) {
        setSelectedRun(runRows[0].id);
      }
    }

    setLoading(false);
  };

  useEffect(() => {
    void load();
  }, []);

  const handleExecute = async () => {
    if (!confirm.runId || !confirm.target) return;
    setExecuting(true);
    try {
      const details: Record<string, unknown> = {};
      if (confirm.actionType === "force_password_reset") {
        details.new_password = prompt("Enter temporary password for target user:") ?? "";
      }
      const result: IncidentActionExecutionResult = await executeContainmentAction(
        confirm.runId,
        confirm.actionType,
        confirm.target,
        details,
      );
      setExecResult(`${result.status} — ${(result.actions ?? []).map((a) => `${a.action_type}:${a.status}`).join(", ")}`);
      await load();
    } catch (e) {
      setExecResult(`Failed: ${e instanceof Error ? e.message : "request_failed"}`);
    } finally {
      setExecuting(false);
      setConfirm({ open: false, runId: "", actionType: "", target: "" });
    }
  };

  const activeRun = runs.find((r) => r.id === selectedRun) ?? null;
  const visibleActions = actions.filter((item) => !selectedRun || item.run_id === selectedRun);
  const selectedAction = actionCatalog.find((item) => item.key === actionTypeInput) ?? actionCatalog[0] ?? DEFAULT_DEFENSE_ACTIONS[0];
  const activeMetadata = (activeRun?.metadata ?? {}) as Record<string, unknown>;
  const activeEntity = typeof activeMetadata.entity_key === "string" ? activeMetadata.entity_key : null;
  const activeSource = typeof activeMetadata.source === "string" ? activeMetadata.source : null;
  const automation = activeMetadata.automation === true;
  const matchingHooks = useMemo(() => {
    if (!canInspectWebhooks || !selectedAction) return [];
    return webhooks.filter((hook) => hook.is_active && hook.action_type === selectedAction.key);
  }, [canInspectWebhooks, selectedAction, webhooks]);

  useEffect(() => {
    if (!activeEntity) return;
    setTargetInput((current) => current.trim() ? current : activeEntity);
    setActionTypeInput((current) => current || suggestedActionForEntity(activeEntity));
  }, [activeEntity]);

  useEffect(() => {
    if (!activeEntity) return;
    const suggested = suggestedActionForEntity(activeEntity);
    if (!actionCatalog.some((item) => item.key === actionTypeInput)) {
      setActionTypeInput(suggested);
      return;
    }
    if (!actionTypeInput || actionTypeInput === "block_ip") {
      setActionTypeInput(suggested);
    }
  }, [actionCatalog, actionTypeInput, activeEntity]);

  const queuedActions = actions.filter((item) => item.status === "queued").length;
  const failedActions = actions.filter((item) => item.status === "failed").length;
  const deliveredCount = deliveries.filter((item) => item.status === "delivered").length;
  const activeHooks = webhooks.filter((item) => item.is_active).length;
  const criticalVulns = vulnerabilities.filter((item) => {
    const severity = item.severity.toLowerCase();
    return severity === "critical" || severity === "high" || item.kev;
  }).length;
  const immutableBackups = backups.filter((item) => item.immutable).length;
  const successfulDrills = restoreDrills.filter((item) => item.success).length;

  return (
    <div>
      <div className="screen-header">
        <div>
          <p className="eyebrow">S6</p>
          <h2 style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Shield size={20} color="var(--danger)" />
            Defense & Containment
          </h2>
          <p className="subtle">
            This screen should show whether containment can be dispatched, whether it landed, and whether the surrounding defense posture is ready.
          </p>
        </div>
        <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={13} /> &nbsp;Refresh
        </button>
      </div>

      <div className="defense-top-grid">
        <div className="metric-card">
          <div className="metric-label">Open incident runs</div>
          <div className="metric-value">{runs.length}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Queued actions</div>
          <div className="metric-value">{queuedActions}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Active hooks</div>
          <div className="metric-value">{activeHooks}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Critical vuln queue</div>
          <div className="metric-value">{criticalVulns}</div>
        </div>
      </div>

      {visibilityNote && (
        <div className="panel defense-note-panel">
          <span className="muted" style={{ fontSize: "0.82rem" }}>{visibilityNote}</span>
        </div>
      )}

      {execResult && (
        <div
          className="panel defense-note-panel"
          style={{
            borderColor: execResult.startsWith("Failed") ? "rgba(255,77,90,.35)" : "rgba(49,255,144,.35)",
          }}
        >
          <span style={{ fontSize: "0.82rem", fontFamily: "JetBrains Mono, monospace" }}>{execResult}</span>
          <button className="btn-ghost" style={{ marginLeft: 12, padding: "2px 8px" }} onClick={() => setExecResult("")}>
            ×
          </button>
        </div>
      )}

      <div className="grid-two defense-console-grid">
        <div className="panel workflow-stage-panel">
          <div className="panel-header">
            <div>
              <h3>Incident runs</h3>
              <p className="muted">Select one run to see what triggered it, what can be dispatched, and what actually happened.</p>
            </div>
            <span className="muted">{runs.length}</span>
          </div>
          {loading ? (
            <div className="state-box">
              <Loader size={20} />
            </div>
          ) : runs.length === 0 ? (
            <div className="state-box">
              <Shield size={24} />
              <p>No incident runs yet</p>
            </div>
          ) : (
            <div className="defense-run-list">
              {runs.map((run) => (
                <button
                  key={run.id}
                  type="button"
                  className={`campaign-card defense-run-card${selectedRun === run.id ? " active" : ""}`}
                  onClick={() => setSelectedRun(run.id)}
                >
                  <div className="campaign-card-main">
                    <p className="label">{run.incident_key}</p>
                    <p className="muted">{run.status} · {run.section_code ?? "unscoped"} · {fmtTime(run.started_at)}</p>
                    <p className="campaign-card-meta">
                      {((run.metadata ?? {}) as Record<string, unknown>).automation === true ? "auto-created" : "manual / investigation-driven"}
                    </p>
                  </div>
                  <div className="campaign-card-side">
                    <span className={`risk-badge ${severityClass(run.severity)}`}>{run.severity}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="workflow-stack">
          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>Selected run brief</h3>
              <span className="muted">{activeRun ? shortHash(activeRun.id) : "No run selected"}</span>
            </div>
            {!activeRun ? (
              <div className="defense-state-banner">
                <strong>Select an incident run</strong>
                <p>This panel should explain what triggered the run and whether you are about to dispatch a real containment step or only review the queue.</p>
              </div>
            ) : (
              <>
                <div className="detail-grid">
                  <div>
                    <p className="label">Incident key</p>
                    <p className="mono">{activeRun.incident_key}</p>
                  </div>
                  <div>
                    <p className="label">Started</p>
                    <p className="stat">{fmtStamp(activeRun.started_at)}</p>
                  </div>
                  <div>
                    <p className="label">Source</p>
                    <p className="stat">{humanValue(activeSource)}</p>
                  </div>
                  <div>
                    <p className="label">Entity / target</p>
                    <p className="mono">{humanValue(activeEntity)}</p>
                  </div>
                  <div>
                    <p className="label">Creation mode</p>
                    <p className="stat">{automation ? "automatic" : "manual / analyst-triggered"}</p>
                  </div>
                  <div>
                    <p className="label">Section</p>
                    <p className="stat">{activeRun.section_code ?? "not pinned"}</p>
                  </div>
                </div>
                <div className="defense-brief-callout">
                  <strong>What this run means</strong>
                  <p>
                    {automation
                      ? "This run was created automatically from model output or automation policy. Verify the target and webhook readiness before treating it as a real enforcement path."
                      : "This run was created from analyst or investigation flow. Use it to dispatch one concrete containment action and verify delivery receipts."}
                  </p>
                </div>
              </>
            )}
          </div>

          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>Execute action</h3>
              <span className="muted">
                {selectedAction ? `${selectedAction.label} · ${matchingHooks.length} matching hooks` : "Select an action"}
              </span>
            </div>
            <div className="detail-grid">
              <div>
                <p className="label" style={{ marginBottom: 6 }}>Action type</p>
                <select
                  value={actionTypeInput}
                  onChange={(e) => setActionTypeInput(e.target.value)}
                  style={{ width: "100%" }}
                >
                  {actionCatalog.map((item) => (
                    <option key={item.key} value={item.key}>{item.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <p className="label" style={{ marginBottom: 6 }}>Target ({selectedAction?.target_hint ?? "entity"})</p>
                <input
                  value={targetInput}
                  onChange={(e) => setTargetInput(e.target.value)}
                  placeholder={selectedAction?.target_hint ?? "Containment target"}
                  style={{ width: "100%" }}
                />
              </div>
            </div>
            <div className="chip-row" style={{ marginTop: 10 }}>
              <span className="chip">{selectedAction?.delivery_mode ?? "internal"}</span>
              <span className="chip">{selectedAction?.continuity_preserving ? "continuity-preserving" : "service-disruptive"}</span>
              <span className="chip">{matchingHooks.length} matching hook{matchingHooks.length === 1 ? "" : "s"}</span>
            </div>
            {selectedAction && (
              <p className="muted" style={{ marginTop: 10 }}>
                {selectedAction.description}
              </p>
            )}
            {selectedAction?.delivery_mode === "webhook" && matchingHooks.length === 0 && (
              <div className="defense-state-banner" style={{ marginTop: 12 }}>
                <strong>No matching webhook is registered for this action</strong>
                <p>The action can still be staged, but last-mile dispatch is not proven until a matching active webhook exists for this section and action type.</p>
              </div>
            )}
            <div className="defense-compose-actions">
              <button
                className="btn-danger"
                disabled={!selectedRun || !targetInput.trim()}
                onClick={() => setConfirm({ open: true, runId: selectedRun, actionType: actionTypeInput, target: targetInput.trim() })}
              >
                <ShieldAlert size={13} /> &nbsp;Execute
              </button>
            </div>
          </div>

          <div className="grid-two defense-lower-grid">
            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Containment history</h3>
                <span className="muted">{visibleActions.length} shown</span>
              </div>
              {visibleActions.length === 0 ? (
                <div className="defense-state-banner">
                  <strong>No persisted containment actions for this run yet</strong>
                  <p>Action history comes from the backend ledger. If this is empty, nothing has actually been recorded for the selected run yet.</p>
                </div>
              ) : (
                <div className="defense-history-list">
                  {visibleActions.map((action) => {
                    const details = action.details_json as { webhook_status?: string; prediction_score?: number; auto_containment?: boolean; dry_run?: boolean };
                    return (
                      <div key={action.id ?? `${action.action_type}:${action.target}:${action.executed_at ?? ""}`} className="campaign-inline-row campaign-inline-risk">
                        <div>
                          <strong>{action.action_type}</strong>
                          <p className="muted mono">{action.target}</p>
                          <p className="muted">
                            {details.auto_containment ? "auto containment" : "operator dispatch"}
                            {details.dry_run ? " · dry run" : ""}
                            {details.prediction_score ? ` · score ${Math.round(details.prediction_score)} / 100` : ""}
                          </p>
                        </div>
                        <div className="campaign-risk-side">
                          <strong>{action.status}</strong>
                          <p className="muted">{details.webhook_status ?? "no webhook status"}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Delivery and hooks</h3>
                <span className="muted">{deliveries.length} receipts</span>
              </div>
              <div className="defense-delivery-summary">
                <div>
                  <p className="label">Delivered</p>
                  <p className="stat">{deliveredCount}</p>
                </div>
                <div>
                  <p className="label">Failed</p>
                  <p className="stat">{failedActions}</p>
                </div>
                <div>
                  <p className="label">Active hooks</p>
                  <p className="stat">{activeHooks}</p>
                </div>
              </div>
              {deliveries.length === 0 ? (
                <div className="defense-state-banner">
                  <strong>No recent delivery receipts</strong>
                  <p>If actions are being queued but deliveries stay empty, the system is not yet proving last-mile dispatch.</p>
                </div>
              ) : (
                <div className="defense-history-list">
                  {deliveries.slice(0, 8).map((delivery) => (
                    <div key={delivery.id} className="campaign-inline-row campaign-inline-risk">
                      <div>
                        <strong>{delivery.action_type}</strong>
                        <p className="muted mono">{delivery.target}</p>
                        <p className="muted">{delivery.section_code ?? "—"} · HTTP {delivery.http_status_code ?? "—"}</p>
                      </div>
                      <div className="campaign-risk-side">
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 6 }}>
                          <span className={`status-dot ${deliveryStatusClass(delivery.status)}`} />
                          <strong>{delivery.status}</strong>
                        </div>
                        <p className="muted">{fmtTime(delivery.last_attempted_at ?? delivery.created_at)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="grid-two defense-lower-grid">
            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Resilience posture</h3>
                <span className="muted">{backups.length} backups · {restoreDrills.length} drills</span>
              </div>
              <div className="defense-delivery-summary">
                <div>
                  <p className="label">Immutable backups</p>
                  <p className="stat">{immutableBackups}</p>
                </div>
                <div>
                  <p className="label">Successful drills</p>
                  <p className="stat">{successfulDrills}</p>
                </div>
              </div>
              <div className="defense-history-list">
                {backups.slice(0, 4).map((backup) => (
                  <div key={backup.id} className="campaign-inline-row">
                    <div>
                      <strong>{backup.asset_id}</strong>
                      <p className="muted">{backup.backup_id} · {backup.storage_tier ?? "storage unspecified"}</p>
                    </div>
                    <div className="campaign-risk-side">
                      <strong>{backup.status}</strong>
                      <p className="muted">{backup.immutable ? "immutable" : "mutable"} · {fmtTime(backup.attested_at)}</p>
                    </div>
                  </div>
                ))}
                {backups.length === 0 && (
                  <div className="defense-state-banner">
                    <strong>No backup attestations loaded</strong>
                    <p>This lane should consume `/v1/defense/backups/attest` so operators can prove recoverability, not just containment.</p>
                  </div>
                )}
              </div>
            </div>

            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Vulnerability queue</h3>
                <span className="muted">{vulnerabilities.length} findings</span>
              </div>
              <div className="defense-history-list">
                {vulnerabilities.slice(0, 6).map((finding) => (
                  <div key={finding.id} className="campaign-inline-row campaign-inline-risk">
                    <div>
                      <strong>{finding.cve_id}</strong>
                      <p className="muted">{finding.asset_id} · {finding.source}</p>
                    </div>
                    <div className="campaign-risk-side">
                      <strong>{finding.severity}</strong>
                      <p className="muted">{finding.kev ? "KEV" : "non-KEV"} · score {Math.round(finding.risk_score)}</p>
                    </div>
                  </div>
                ))}
                {vulnerabilities.length === 0 && (
                  <div className="defense-state-banner">
                    <strong>No vulnerability findings available</strong>
                    <p>The defense screen should also show exposure and recovery state, not only webhook execution history.</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {confirm.open && (
        <div className="modal-overlay">
          <div className="modal-box">
            <h3>
              <AlertTriangle size={16} color="var(--danger)" style={{ marginRight: 8, verticalAlign: "middle" }} />
              Confirm containment action
            </h3>
            <div className="modal-body">
              This will dispatch a containment action through the backend execution path.
              <br /><br />
              <strong>Action:</strong> <span className="mono">{confirm.actionType}</span>
              <br />
              <strong>Target:</strong> <span className="mono">{confirm.target}</span>
              <br />
              <strong>Incident:</strong> <span className="mono">{activeRun?.incident_key ?? confirm.runId}</span>
            </div>
            <div className="modal-actions">
              <button className="btn-ghost" onClick={() => setConfirm({ open: false, runId: "", actionType: "", target: "" })}>
                Cancel
              </button>
              <button className="btn-danger" onClick={() => void handleExecute()} disabled={executing}>
                {executing ? <Loader size={13} /> : <ShieldAlert size={13} />}
                &nbsp;Confirm & Dispatch
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
