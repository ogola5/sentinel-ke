import { useEffect, useState } from "react";
import { Shield, ShieldAlert, RefreshCw, Loader, Webhook, AlertTriangle, CheckCircle, XCircle, Clock } from "lucide-react";
import {
  DEFAULT_DEFENSE_ACTIONS,
  fetchContainmentActions,
  fetchPlaybookRuns,
  fetchDefenseActionCatalog,
  executeContainmentAction,
  fetchWebhooks,
  fetchWebhookDeliveries,
} from "../../api/defense";
import type { Principal } from "../../types/auth";
import type {
  PlaybookRun,
  ContainmentActionRecord,
  IncidentActionExecutionResult,
  WebhookRecord,
  WebhookDeliveryRecord,
} from "../../types/defense";

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
  return `${Math.floor(diff / 3600)}h ago`;
}

function deliveryStatusClass(status: string | null | undefined): string {
  if (status === "delivered" || status === "executed") return "delivered";
  if (status === "failed") return "failed";
  return "pending";
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
    const [runRows, actionRows, catalogRows] = await Promise.all([
      fetchPlaybookRuns(20),
      fetchContainmentActions(100),
      fetchDefenseActionCatalog(),
    ]);
    setRuns(runRows);
    setActions(actionRows);
    setActionCatalog(catalogRows);
    if (canInspectWebhooks) {
      try {
        const [w, d] = await Promise.all([
          fetchWebhooks({ strict: true }),
          fetchWebhookDeliveries(40, { strict: true }),
        ]);
        setWebhooks(w);
        setDeliveries(d);
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
    if (runRows.length > 0 && !selectedRun) {
      setSelectedRun(runRows[0].id);
    }
    setLoading(false);
  };

  useEffect(() => {
    void load();
  }, []);

  const selectRun = async (id: string) => {
    setSelectedRun(id);
  };

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

  const activeRun = runs.find((r) => r.id === selectedRun);
  const visibleActions = actions.filter((item) => !selectedRun || item.run_id === selectedRun);
  const selectedAction = actionCatalog.find((item) => item.key === actionTypeInput) ?? actionCatalog[0] ?? DEFAULT_DEFENSE_ACTIONS[0];

  return (
    <div>
      <div className="screen-header">
        <div>
          <p className="eyebrow">S13</p>
          <h2 style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Shield size={20} color="var(--danger)" />
            Defense & Containment
          </h2>
          <p className="subtle">Choose a run, dispatch an action, verify delivery.</p>
        </div>
        <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={13} /> &nbsp;Refresh
        </button>
      </div>

      <div className="metric-grid" style={{ marginBottom: 18 }}>
        <div className="metric-card">
          <div className="metric-label">Incident runs</div>
          <div className="metric-value">{runs.length}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Active webhooks</div>
          <div className="metric-value">{webhooks.filter((item) => item.is_active).length}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Recent deliveries</div>
          <div className="metric-value">{deliveries.length}</div>
        </div>
      </div>

      {visibilityNote && (
        <div className="panel" style={{ marginBottom: 12, borderColor: "rgba(255,159,10,.3)" }}>
          <span className="muted" style={{ fontSize: "0.82rem" }}>{visibilityNote}</span>
        </div>
      )}

      {execResult && (
        <div
          className="panel"
          style={{
            marginBottom: 12,
            borderColor: execResult.startsWith("Failed") ? "rgba(255,77,90,.35)" : "rgba(49,255,144,.35)",
            padding: "10px 16px",
          }}
        >
          <span style={{ fontSize: "0.82rem", fontFamily: "JetBrains Mono, monospace" }}>{execResult}</span>
          <button className="btn-ghost" style={{ marginLeft: 12, padding: "2px 8px" }} onClick={() => setExecResult("")}>
            ×
          </button>
        </div>
      )}

      <div className="pane-layout">
        {/* Left: Playbook runs */}
        <div className="pane-left">
          <div className="panel-header" style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
            <h3>Incident runs</h3>
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
            runs.map((r) => (
              <div
                key={r.id}
                className={`pane-item ${selectedRun === r.id ? "active" : ""}`}
                onClick={() => void selectRun(r.id)}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <h4 style={{ fontSize: "0.82rem" }}>{r.incident_key}</h4>
                  <span className={`risk-badge ${severityClass(r.severity)}`}>{r.severity}</span>
                </div>
                <div className="pane-meta">
                  <span className={`status-dot ${r.status === "running" ? "live" : r.status === "completed" ? "delivered" : "failed"}`} />
                  {r.status}
                  {r.section_code && <span>· {r.section_code}</span>}
                </div>
                <div className="pane-meta" style={{ marginTop: 4 }}>
                  <Clock size={10} />
                  {fmtTime(r.started_at)}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Right: actions + webhooks */}
        <div className="pane-right">
          {/* Execute action panel */}
          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>Execute action</h3>
              <span className="muted">
                {activeRun ? `${activeRun.incident_key} · ${activeRun.severity} · ${activeRun.status}` : "Select an incident run"}
              </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr auto", gap: 10, alignItems: "end" }}>
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
              <button
                className="btn-danger"
                disabled={!selectedRun || !targetInput.trim()}
                onClick={() =>
                  setConfirm({ open: true, runId: selectedRun, actionType: actionTypeInput, target: targetInput.trim() })
                }
              >
                <ShieldAlert size={13} /> &nbsp;Execute
              </button>
            </div>
            {selectedAction && (
              <p className="muted" style={{ marginTop: 10 }}>
                {selectedAction.description}
                {selectedAction.continuity_preserving ? " Keeps the service path available where possible." : " Use when targeted containment is worth service disruption."}
              </p>
            )}
          </div>

          {/* Containment actions table */}
          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>Containment history</h3>
              <span className="muted">{visibleActions.length} shown</span>
            </div>
            {visibleActions.length === 0 ? (
              <div className="state-box" style={{ padding: 24 }}>
                <p>No persisted containment actions for this run yet.</p>
                <p className="muted" style={{ fontSize: "0.8rem" }}>
                  Action history now comes from the backend ledger, not this browser session.
                </p>
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Target</th>
                    <th>Status</th>
                    <th>Webhook status</th>
                    <th>Executed</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleActions.map((a) => {
                    const wh = a.details_json as { webhook_status?: string };
                    return (
                      <tr key={a.id ?? `${a.action_type}:${a.target}:${a.executed_at ?? ""}`}>
                        <td>
                          <span className="mono" style={{ fontSize: "0.8rem" }}>{a.action_type}</span>
                        </td>
                        <td>
                          <span className="mono" style={{ fontSize: "0.8rem" }}>{a.target}</span>
                        </td>
                        <td>
                          <span className={`risk-badge ${a.status === "executed" ? "low" : a.status === "failed" ? "critical" : "medium"}`}>
                            {a.status}
                          </span>
                        </td>
                        <td>
                          {wh.webhook_status ? (
                            <span className={`status-dot ${deliveryStatusClass(wh.webhook_status)}`} />
                          ) : (
                            <span className="muted">—</span>
                          )}
                          &nbsp;
                          <span className="muted" style={{ fontSize: "0.78rem" }}>{wh.webhook_status ?? "n/a"}</span>
                        </td>
                        <td className="muted" style={{ fontSize: "0.78rem" }}>{fmtTime(a.executed_at ?? null)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* Webhook registry */}
          {/* Delivery audit log */}
          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>Delivery log</h3>
              <span className="muted">{deliveries.length} recent</span>
            </div>
            {deliveries.length === 0 ? (
              <div className="state-box" style={{ padding: 24 }}>
                <p>No deliveries yet.</p>
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Target</th>
                    <th>Section</th>
                    <th>HTTP</th>
                    <th>Status</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {deliveries.map((d) => (
                    <tr key={d.id}>
                      <td><span className="mono" style={{ fontSize: "0.78rem" }}>{d.action_type}</span></td>
                      <td><span className="mono" style={{ fontSize: "0.78rem" }}>{d.target}</span></td>
                      <td className="muted" style={{ fontSize: "0.78rem" }}>{d.section_code ?? "—"}</td>
                      <td className="muted" style={{ fontSize: "0.78rem" }}>{d.http_status_code ?? "—"}</td>
                      <td>
                        <span className={`status-dot ${deliveryStatusClass(d.status)}`} />
                        &nbsp;
                        <span className="muted" style={{ fontSize: "0.78rem" }}>{d.status}</span>
                      </td>
                      <td className="muted" style={{ fontSize: "0.76rem" }}>{fmtTime(d.last_attempted_at ?? d.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <details className="collapsible-panel">
              <summary>
                <span>Webhook registry</span>
                <span className="muted">{webhooks.length} registered hooks</span>
              </summary>
              {webhooks.length === 0 ? (
                <div className="state-box" style={{ padding: 24 }}>
                  <Webhook size={22} />
                  <p>No webhooks registered. POST /v1/defense/webhooks to register a partner endpoint.</p>
                </div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Section</th>
                      <th>Action type</th>
                      <th>URL</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {webhooks.map((w) => (
                      <tr key={w.id}>
                        <td>{w.section_code}</td>
                        <td><span className="mono" style={{ fontSize: "0.78rem" }}>{w.action_type}</span></td>
                        <td className="muted" style={{ fontSize: "0.76rem", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>{w.webhook_url}</td>
                        <td>
                          {w.is_active ? (
                            <span style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--accent)", fontSize: "0.8rem" }}>
                              <CheckCircle size={13} /> Active
                            </span>
                          ) : (
                            <span style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--danger)", fontSize: "0.8rem" }}>
                              <XCircle size={13} /> Inactive
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </details>
          </div>
        </div>
      </div>

      {/* Confirm modal */}
      {confirm.open && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <h3>
              <AlertTriangle size={16} color="var(--danger)" style={{ marginRight: 8, verticalAlign: "middle" }} />
              Confirm containment action
            </h3>
            <div className="modal-body">
              This will dispatch a signed webhook to the partner's firewall / EDR system.
              <br /><br />
              <strong>Action:</strong>&nbsp;
              <span className="mono">{confirm.actionType}</span>
              <br />
              <strong>Target:</strong>&nbsp;
              <span className="mono">{confirm.target}</span>
              <br />
              <strong>Incident:</strong>&nbsp;
              <span className="mono">{activeRun?.incident_key ?? confirm.runId}</span>
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
