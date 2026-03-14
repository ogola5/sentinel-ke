import { useEffect, useState } from "react";
import { Shield, ShieldAlert, RefreshCw, Loader, Webhook, AlertTriangle, CheckCircle, XCircle, Clock } from "lucide-react";
import {
  fetchPlaybookRuns,
  executeContainmentAction,
  fetchWebhooks,
  fetchWebhookDeliveries,
} from "../../api/defense";
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

interface ConfirmState {
  open: boolean;
  runId: string;
  actionType: string;
  target: string;
}

export default function DefenseCenter() {
  const [runs, setRuns] = useState<PlaybookRun[]>([]);
  const [actions, setActions] = useState<ContainmentActionRecord[]>([]);
  const [webhooks, setWebhooks] = useState<WebhookRecord[]>([]);
  const [deliveries, setDeliveries] = useState<WebhookDeliveryRecord[]>([]);
  const [selectedRun, setSelectedRun] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [confirm, setConfirm] = useState<ConfirmState>({ open: false, runId: "", actionType: "", target: "" });
  const [targetInput, setTargetInput] = useState("");
  const [actionTypeInput, setActionTypeInput] = useState("block_ip");
  const [executing, setExecuting] = useState(false);
  const [execResult, setExecResult] = useState<string>("");

  const load = async () => {
    setLoading(true);
    const [r, w, d] = await Promise.all([fetchPlaybookRuns(20), fetchWebhooks(), fetchWebhookDeliveries(40)]);
    setRuns(r);
    setWebhooks(w);
    setDeliveries(d);
    if (r.length > 0 && !selectedRun) {
      setSelectedRun(r[0].id);
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
      const mappedActions: ContainmentActionRecord[] = (result.actions ?? []).map((a, idx) => ({
        id: `${confirm.runId}-${Date.now()}-${idx}`,
        run_id: confirm.runId,
        section_code: activeRun?.section_code ?? null,
        action_type: a.action_type,
        target: a.target,
        status: a.status === "executed" ? "executed" : "failed",
        executed_at: new Date().toISOString(),
        details_json: a.details ?? {},
      }));
      setActions((prev) => [...mappedActions, ...prev].slice(0, 100));
      setExecResult(`${result.status} — ${mappedActions.map((a) => `${a.action_type}:${a.status}`).join(", ")}`);
      const refreshedRuns = await fetchPlaybookRuns(20);
      setRuns(refreshedRuns);
      const newDeliveries = await fetchWebhookDeliveries(40);
      setDeliveries(newDeliveries);
    } catch (e) {
      setExecResult(`Failed: ${e instanceof Error ? e.message : "request_failed"}`);
    } finally {
      setExecuting(false);
      setConfirm({ open: false, runId: "", actionType: "", target: "" });
    }
  };

  const activeRun = runs.find((r) => r.id === selectedRun);

  return (
    <div>
      <div className="screen-header">
        <h2>
          <Shield size={20} color="var(--danger)" />
          Defense & Containment Center
          <span className="subtitle">— block_ip · isolate_host · webhook dispatch</span>
        </h2>
        <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={13} /> &nbsp;Refresh
        </button>
      </div>

      <div className="panel workflow-guide-panel" style={{ background: "rgba(var(--danger-rgb), 0.08)", borderColor: "rgba(var(--danger-rgb), 0.24)", marginBottom: 12 }}>
        <div className="panel-header">
          <h3>How to use this page</h3>
          <span className="muted">Act only after the incident run is clear</span>
        </div>
        <div className="detail-grid">
          <div>
            <p className="label">Step 1</p>
            <p>Select one incident run from the left. Do not execute actions without a run.</p>
          </div>
          <div>
            <p className="label">Step 2</p>
            <p>Choose the action and target carefully. This page is for verified response, not exploration.</p>
          </div>
          <div>
            <p className="label">Step 3</p>
            <p>Check execution results and the webhook delivery log before closing the incident.</p>
          </div>
        </div>
        <div className="chip-row" style={{ marginTop: 12 }}>
          <span className="chip">Select run</span>
          <span className="chip">Execute action</span>
          <span className="chip">Confirm webhook receipt</span>
        </div>
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

      <div className="workflow-summary-banner" style={{ marginBottom: 18 }}>
        <div>
          <strong>Current selected run</strong>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            {activeRun ? `${activeRun.incident_key} · ${activeRun.severity} · ${activeRun.status}` : "Select an incident run from the left first."}
          </p>
        </div>
        <div>
          <div className="label">Next move</div>
          <div>{activeRun ? "Choose the safest action and verify delivery receipts." : "Choose an incident run before any action."}</div>
        </div>
      </div>

      <div className="pane-layout">
        {/* Left: Playbook runs */}
        <div className="pane-left">
          <div className="panel-header" style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
            <h3>1. Choose Incident Run</h3>
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
              <h3>2. Execute Containment Action</h3>
              <span className="muted">{activeRun ? activeRun.incident_key : "Select an incident run"}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr auto", gap: 10, alignItems: "end" }}>
              <div>
                <p className="label" style={{ marginBottom: 6 }}>Action type</p>
                <select
                  value={actionTypeInput}
                  onChange={(e) => setActionTypeInput(e.target.value)}
                  style={{ width: "100%" }}
                >
                  <option value="block_ip">block_ip</option>
                  <option value="isolate_host">isolate_host</option>
                  <option value="revoke_user">revoke_user</option>
                  <option value="force_password_reset">force_password_reset</option>
                </select>
              </div>
              <div>
                <p className="label" style={{ marginBottom: 6 }}>Target (IP / hostname / user)</p>
                <input
                  value={targetInput}
                  onChange={(e) => setTargetInput(e.target.value)}
                  placeholder="e.g. 192.168.1.50 or host-web-01"
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
          </div>

          {/* Containment actions table */}
          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>3. Execution Results (session)</h3>
              <span className="muted">{actions.length} actions captured</span>
            </div>
            {actions.length === 0 ? (
              <div className="state-box" style={{ padding: 24 }}>
                <p>No actions executed in this session yet.</p>
                <p className="muted" style={{ fontSize: "0.8rem" }}>
                  Use the webhook delivery log below for persistent forensic history.
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
                  {actions.map((a) => {
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
                            <span className={`status-dot ${wh.webhook_status === "delivered" ? "delivered" : wh.webhook_status === "failed" ? "failed" : "pending"}`} />
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
              <h3>4. Webhook Delivery Log</h3>
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
                        <span className={`status-dot ${d.status}`} />
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
