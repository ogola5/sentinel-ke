import { useEffect, useState } from "react";
import { FileText, RefreshCw, Loader, CheckCircle, XCircle, Clock } from "lucide-react";
import { fetchWebhookDeliveries } from "../../api/defense";
import type { WebhookDeliveryRecord } from "../../types/defense";

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-KE", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function fmtAgo(iso: string | null): string {
  if (!iso) return "—";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function AuditLog() {
  const [deliveries, setDeliveries] = useState<WebhookDeliveryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [filterAction, setFilterAction] = useState<string>("all");
  const [selected, setSelected] = useState<WebhookDeliveryRecord | null>(null);

  const load = async () => {
    setLoading(true);
    const d = await fetchWebhookDeliveries(100);
    setDeliveries(d);
    setLoading(false);
  };

  useEffect(() => {
    void load();
  }, []);

  const statuses = ["all", ...Array.from(new Set(deliveries.map((d) => d.status)))];
  const actions  = ["all", ...Array.from(new Set(deliveries.map((d) => d.action_type)))];

  const filtered = deliveries.filter((d) => {
    if (filterStatus !== "all" && d.status !== filterStatus) return false;
    if (filterAction !== "all" && d.action_type !== filterAction) return false;
    return true;
  });

  const delivered = deliveries.filter((d) => d.status === "delivered").length;
  const failed    = deliveries.filter((d) => d.status === "failed").length;
  const pending   = deliveries.filter((d) => d.status === "pending").length;

  return (
    <div>
      <div className="screen-header">
        <h2>
          <FileText size={20} color="var(--ink-muted)" />
          Audit Log
          <span className="subtitle">— webhook deliveries · containment history · forensic trail</span>
        </h2>
        <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader size={13} /> : <RefreshCw size={13} />}
          &nbsp;Refresh
        </button>
      </div>

      {/* Summary metrics */}
      <div className="metric-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: 16 }}>
        <div className="metric-card">
          <div className="metric-label">Total records</div>
          <div className="metric-value">{deliveries.length}</div>
          <div className="metric-sub">Webhook dispatch attempts</div>
        </div>
        <div className="metric-card accent">
          <div className="metric-label">Delivered</div>
          <div className="metric-value">{delivered}</div>
          <div className="metric-sub">2xx from partner</div>
        </div>
        <div className="metric-card danger">
          <div className="metric-label">Failed</div>
          <div className="metric-value">{failed}</div>
          <div className="metric-sub">Error or timeout</div>
        </div>
        <div className="metric-card warn">
          <div className="metric-label">Pending</div>
          <div className="metric-value">{pending}</div>
          <div className="metric-sub">In-flight</div>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 12, alignItems: "center" }}>
        <div>
          <p className="label" style={{ marginBottom: 4 }}>Status</p>
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <p className="label" style={{ marginBottom: 4 }}>Action type</p>
          <select value={filterAction} onChange={(e) => setFilterAction(e.target.value)}>
            {actions.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <span className="muted" style={{ fontSize: "0.8rem", marginTop: 18 }}>
          {filtered.length} of {deliveries.length} records
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: selected ? "1fr 340px" : "1fr", gap: 16 }}>
        {/* Main log table */}
        <div className="panel">
          {loading ? (
            <div className="state-box">
              <Loader size={22} />
              <p>Loading audit records…</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="state-box">
              <FileText size={28} />
              <p>No webhook delivery records yet.</p>
              <p style={{ fontSize: "0.8rem" }}>Execute a containment action to generate audit entries.</p>
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Target</th>
                    <th>Section</th>
                    <th>Status</th>
                    <th>HTTP</th>
                    <th>Attempts</th>
                    <th>When</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((d) => (
                    <tr
                      key={d.id}
                      style={{ cursor: "pointer", background: selected?.id === d.id ? "rgba(49,255,144,.06)" : undefined }}
                      onClick={() => setSelected(d.id === selected?.id ? null : d)}
                    >
                      <td>
                        <span className="mono" style={{ fontSize: "0.78rem" }}>{d.action_type}</span>
                      </td>
                      <td>
                        <span className="mono" style={{ fontSize: "0.78rem" }}>{d.target}</span>
                      </td>
                      <td className="muted" style={{ fontSize: "0.76rem" }}>{d.section_code ?? "—"}</td>
                      <td>
                        <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                          <span className={`status-dot ${d.status}`} />
                          <span style={{ fontSize: "0.78rem" }}>{d.status}</span>
                        </span>
                      </td>
                      <td>
                        {d.http_status_code != null ? (
                          <span
                            style={{
                              fontSize: "0.78rem",
                              fontFamily: "JetBrains Mono, monospace",
                              color: d.http_status_code < 300 ? "var(--accent)" : "var(--danger)",
                            }}
                          >
                            {d.http_status_code}
                          </span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="muted" style={{ fontSize: "0.78rem" }}>{d.attempt_count}</td>
                      <td>
                        <span className="muted" style={{ fontSize: "0.76rem" }}>
                          <Clock size={10} style={{ verticalAlign: "middle", marginRight: 3 }} />
                          {fmtAgo(d.last_attempted_at ?? d.created_at)}
                        </span>
                      </td>
                      <td>
                        {d.status === "delivered" ? (
                          <CheckCircle size={13} color="var(--accent)" />
                        ) : d.status === "failed" ? (
                          <XCircle size={13} color="var(--danger)" />
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Detail panel */}
        {selected && (
          <div className="panel" style={{ alignSelf: "start" }}>
            <div className="panel-header">
              <h3>Record detail</h3>
              <button className="btn-ghost" style={{ padding: "2px 8px" }} onClick={() => setSelected(null)}>×</button>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: "0.82rem" }}>
              <Row label="ID" value={selected.id} mono />
              <Row label="Action type" value={selected.action_type} mono />
              <Row label="Target" value={selected.target} mono />
              <Row label="Section code" value={selected.section_code ?? "—"} />
              <Row label="Webhook URL" value={selected.webhook_url} mono small />
              <Row label="Status" value={selected.status} />
              <Row label="HTTP status" value={selected.http_status_code?.toString() ?? "—"} mono />
              <Row label="Attempts" value={selected.attempt_count.toString()} />
              <Row label="Last attempted" value={fmtDateTime(selected.last_attempted_at)} />
              <Row label="Delivered at" value={fmtDateTime(selected.delivered_at)} />
              <Row label="Created at" value={fmtDateTime(selected.created_at)} />
              {selected.error_message && (
                <div>
                  <p className="label">Error</p>
                  <p style={{ color: "var(--danger)", fontFamily: "JetBrains Mono, monospace", fontSize: "0.75rem", wordBreak: "break-all", marginTop: 4 }}>
                    {selected.error_message}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, mono, small }: { label: string; value: string; mono?: boolean; small?: boolean }) {
  return (
    <div>
      <p className="label" style={{ marginBottom: 2 }}>{label}</p>
      <p
        style={{
          fontFamily: mono ? "JetBrains Mono, monospace" : undefined,
          fontSize: small ? "0.72rem" : "0.82rem",
          wordBreak: "break-all",
        }}
      >
        {value}
      </p>
    </div>
  );
}
