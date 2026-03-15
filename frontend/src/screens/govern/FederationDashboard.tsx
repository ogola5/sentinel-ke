import { useEffect, useState } from "react";
import { Globe, RefreshCw, Loader, Network, Link2, AlertTriangle } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import {
  fetchEdgeSyncStatus,
  fetchFederationCorrelations,
  fetchFederationPartners,
  fetchFederationPatterns,
} from "../../api/federation";
import type {
  FederationCorrelation,
  FederationEdgeSyncStatus,
  FederationPartner,
  FederationPattern,
} from "../../types/federation";

function riskClass(level: string): string {
  const l = level.toLowerCase();
  if (l === "critical") return "critical";
  if (l === "high") return "high";
  if (l === "medium") return "medium";
  return "low";
}

function shortHash(h: string): string {
  return h.length > 16 ? `${h.slice(0, 8)}…${h.slice(-6)}` : h;
}

function sectorColor(sector: string): string {
  const s = sector.toLowerCase();
  if (s === "telco") return "var(--info)";
  if (s === "bank" || s === "financial") return "var(--warning)";
  if (s === "gov" || s === "government") return "var(--accent)";
  return "var(--risk-unknown)";
}

function partnerStatusTone(status: FederationPartner["status"]): string {
  if (status === "online") return "var(--accent)";
  if (status === "stale") return "var(--warning)";
  if (status === "offline") return "var(--risk-high)";
  return "var(--risk-unknown)";
}

function partnerStatusSurface(status: FederationPartner["status"]): { background: string; border: string } {
  if (status === "online") {
    return { background: "rgba(49,255,144,.12)", border: "rgba(49,255,144,.3)" };
  }
  if (status === "stale") {
    return { background: "rgba(255,159,10,.12)", border: "rgba(255,159,10,.3)" };
  }
  if (status === "offline") {
    return { background: "rgba(255,69,58,.12)", border: "rgba(255,69,58,.3)" };
  }
  return { background: "rgba(136,183,155,.1)", border: "rgba(136,183,155,.2)" };
}

function partnerFreshnessLabel(partner: FederationPartner): string {
  if (partner.last_heartbeat_at) {
    return `Heartbeat ${new Date(partner.last_heartbeat_at).toLocaleString()}`;
  }
  if (partner.last_seen_at) {
    return `Seen ${new Date(partner.last_seen_at).toLocaleString()}`;
  }
  return "No heartbeat yet";
}

export default function FederationDashboard() {
  const [partners, setPartners] = useState<FederationPartner[]>([]);
  const [patterns, setPatterns] = useState<FederationPattern[]>([]);
  const [correlations, setCorrelations] = useState<FederationCorrelation[]>([]);
  const [edgeSync, setEdgeSync] = useState<FederationEdgeSyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPartner, setSelectedPartner] = useState<string>("");

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, pt, c, edge] = await Promise.all([
        fetchFederationPartners({ strict: true }),
        fetchFederationPatterns(60, { strict: true }),
        fetchFederationCorrelations(20, { strict: true }),
        fetchEdgeSyncStatus(),
      ]);
      setPartners(p);
      setPatterns(pt);
      setCorrelations(c);
      setEdgeSync(edge);
      setSelectedPartner((current) => (
        current && p.some((item) => item.partner_id === current) ? current : (p[0]?.partner_id ?? "")
      ));
    } catch (err) {
      setPartners([]);
      setPatterns([]);
      setCorrelations([]);
      setEdgeSync(null);
      setError(err instanceof Error ? err.message : "federation_data_load_failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const patternsByPartner = partners.map((p) => ({
    name: p.partner_name.split(" ")[0],
    patterns: patterns.filter((pt) => pt.partner_id === p.partner_id).length,
    partner_id: p.partner_id,
  }));

  const selectedPartnerPatterns = patterns.filter((pt) => pt.partner_id === selectedPartner);
  const activePartners = partners.filter((p) => p.status === "online").length;
  const stalePartners = partners.filter((p) => p.status === "stale").length;
  const offlinePartners = partners.filter((p) => p.status === "offline").length;
  const totalPatterns = patterns.length;
  const criticalCorrelations = correlations.filter((c) => c.risk_level.toLowerCase() === "critical").length;

  return (
    <div>
      <div className="screen-header">
        <h2>
          <Globe size={20} color="var(--accent)" />
          Federation Intelligence Network
          <span className="subtitle">— cross-partner threat correlation · privacy-preserving HMAC</span>
        </h2>
        <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader size={13} /> : <RefreshCw size={13} />}
          &nbsp;Refresh
        </button>
      </div>

      {error && (
        <div className="panel" style={{ marginBottom: 16, borderColor: "rgba(255,69,58,.28)", background: "rgba(255,69,58,.08)" }}>
          <div className="info-note" style={{ color: "var(--risk-high)" }}>
            <AlertTriangle size={13} style={{ flexShrink: 0 }} />
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Metric bar */}
      <div className="metric-grid" style={{ gridTemplateColumns: "repeat(6, 1fr)" }}>
        <div className="metric-card accent">
          <div className="metric-label">Active partners</div>
          <div className="metric-value">{activePartners}</div>
          <div className="metric-sub">{partners.length} registered</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Stale partners</div>
          <div className="metric-value" style={{ color: stalePartners > 0 ? "var(--warning)" : "var(--accent)" }}>{stalePartners}</div>
          <div className="metric-sub">Heartbeat aging out</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Offline partners</div>
          <div className="metric-value" style={{ color: offlinePartners > 0 ? "var(--risk-high)" : "var(--accent)" }}>{offlinePartners}</div>
          <div className="metric-sub">No recent partner signal</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Pattern submissions</div>
          <div className="metric-value">{totalPatterns}</div>
          <div className="metric-sub">Anonymised entity patterns</div>
        </div>
        <div className="metric-card info">
          <div className="metric-label">Cross-partner matches</div>
          <div className="metric-value">{correlations.length}</div>
          <div className="metric-sub">Same entity across 2+ partners</div>
        </div>
        <div className={`metric-card ${criticalCorrelations > 0 ? "danger" : ""}`}>
          <div className="metric-label">Critical correlations</div>
          <div className="metric-value">{criticalCorrelations}</div>
          <div className="metric-sub">Risk level = CRITICAL</div>
        </div>
      </div>

      {loading ? (
        <div className="state-box">
          <Loader size={24} />
          <p>Loading federation data…</p>
        </div>
      ) : partners.length === 0 ? (
        <div className="panel">
          <div className="state-box">
            <Network size={32} />
            <p>No federation partners registered yet.</p>
            <p>POST /v1/federation/register to onboard a partner edge agent.</p>
          </div>
        </div>
      ) : (
        <>
          {edgeSync?.is_edge_node && (
            <div className="panel" style={{ marginBottom: 16, borderColor: "rgba(var(--info-rgb), 0.24)", background: "rgba(var(--info-rgb), 0.07)" }}>
              <div className="panel-header">
                <h3>Local edge sync state</h3>
                <span className="muted">{edgeSync.partner_id}</span>
              </div>
              <div className="detail-grid">
                <div>
                  <strong>Status</strong>
                  <p className="muted" style={{ marginTop: 4 }}>
                    {edgeSync.status ?? "unknown"} · {edgeSync.total_pushed ?? 0} total pushes
                  </p>
                </div>
                <div>
                  <strong>Last sync</strong>
                  <p className="muted" style={{ marginTop: 4 }}>
                    {edgeSync.last_synced_at ? new Date(edgeSync.last_synced_at).toLocaleString() : "No sync recorded yet"}
                  </p>
                </div>
                <div>
                  <strong>Last error</strong>
                  <p className="muted" style={{ marginTop: 4 }}>{edgeSync.last_error ?? "None"}</p>
                </div>
              </div>
            </div>
          )}

          {/* Partner cards */}
          <div className="partner-grid">
            {partners.map((p) => {
              const statusSurface = partnerStatusSurface(p.status);
              return (
              <div
                key={p.partner_id}
                className={`partner-card ${p.status === "online" ? "active-partner" : ""}`}
                onClick={() => setSelectedPartner(p.partner_id)}
                style={{ cursor: "pointer", opacity: p.status === "offline" ? 0.55 : 1 }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <div className="partner-name">{p.partner_name}</div>
                    <div className="partner-id">{p.partner_id}</div>
                  </div>
                  <span
                    className="risk-badge"
                    style={{
                      background: statusSurface.background,
                      color: partnerStatusTone(p.status),
                      border: `1px solid ${statusSurface.border}`,
                    }}
                  >
                    {p.status.replace("_", " ")}
                  </span>
                </div>

                <div style={{ display: "inline-block" }}>
                  <span
                    className="risk-badge info"
                    style={{ fontSize: "0.65rem", background: "transparent", border: `1px solid ${sectorColor(p.sector)}20`, color: sectorColor(p.sector) }}
                  >
                    {p.sector.toUpperCase()}
                  </span>
                </div>

                <div className="partner-stats">
                  <div className="partner-stat">
                    <span>{patterns.filter((pt) => pt.partner_id === p.partner_id).length}</span>
                    patterns
                  </div>
                  <div className="partner-stat">
                    <span>{p.run_count ?? 0}</span>
                    runs
                  </div>
                </div>

                <div className="list" style={{ marginTop: 12 }}>
                  <div className="list-item" style={{ padding: 0, border: 0 }}>
                    <strong>Freshness</strong>
                    <p className="muted" style={{ marginTop: 4 }}>{partnerFreshnessLabel(p)}</p>
                  </div>
                  <div className="list-item" style={{ padding: 0, border: 0 }}>
                    <strong>Model and source</strong>
                    <p className="muted" style={{ marginTop: 4 }}>
                      {p.model_version ?? "No heartbeat version yet"} · {p.data_source ?? "unknown source"}
                    </p>
                  </div>
                  <div className="list-item" style={{ padding: 0, border: 0 }}>
                    <strong>Last run</strong>
                    <p className="muted" style={{ marginTop: 4 }}>
                      {p.last_run_status ?? "unknown"} · publish {p.last_publish_status ?? "unknown"}
                      {p.hub_reachable == null ? "" : ` · hub ${p.hub_reachable ? "reachable" : "unreachable"}`}
                    </p>
                  </div>
                </div>
              </div>
              );
            })}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            {/* Pattern submission chart */}
            <div className="panel">
              <div className="panel-header">
                <h3>Patterns by Partner</h3>
              </div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={patternsByPartner} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--ink-muted)" }} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--ink-muted)" }} />
                  <Tooltip
                    contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                  />
                  <Bar dataKey="patterns" fill="var(--accent)" opacity={0.8} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Selected partner patterns */}
            <div className="panel">
              <div className="panel-header">
                <h3>Recent patterns</h3>
                <span className="muted">{selectedPartner}</span>
              </div>
              <div style={{ overflowY: "auto", maxHeight: 200 }}>
                {selectedPartnerPatterns.length === 0 ? (
                  <div className="state-box" style={{ padding: 24 }}>
                    <p>No patterns for this partner</p>
                  </div>
                ) : (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Entity hash</th>
                        <th>Type</th>
                        <th>Confidence</th>
                        <th>Flags</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedPartnerPatterns.slice(0, 10).map((pt) => (
                        <tr key={pt.id}>
                          <td>
                            <span className="mono" style={{ fontSize: "0.75rem" }}>{shortHash(pt.entity_key_hash)}</span>
                          </td>
                          <td className="muted" style={{ fontSize: "0.78rem" }}>{pt.pattern_type}</td>
                          <td>
                            <div className="score-bar-wrap">
                              <div className="score-bar-track">
                                <div
                                  className="score-bar-fill"
                                  style={{
                                    width: `${pt.confidence * 100}%`,
                                    background: pt.confidence >= 0.7 ? "var(--risk-high)" : "var(--accent)",
                                  }}
                                />
                              </div>
                              <span style={{ fontSize: "0.75rem", minWidth: 30 }}>{pt.confidence.toFixed(2)}</span>
                            </div>
                          </td>
                          <td>
                            {pt.risk_flags.slice(0, 2).map((f) => (
                              <span key={f} className="risk-badge medium" style={{ fontSize: "0.62rem", marginRight: 2 }}>
                                {f.replace(/_/g, " ")}
                              </span>
                            ))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          {/* Cross-partner correlations */}
          <div className="panel">
            <div className="panel-header">
              <h3>
                <Link2 size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />
                Cross-Partner Correlations
              </h3>
              <span className="muted">Same entity_key_hash seen across multiple partners</span>
            </div>
            {correlations.length === 0 ? (
              <div className="state-box" style={{ padding: 24 }}>
                <Network size={22} />
                <p>No correlations found yet. Partners must use the same NATIONAL_SALT for entity hashing.</p>
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Entity hash</th>
                    <th>Partners</th>
                    <th>Partner IDs</th>
                    <th>Max confidence</th>
                    <th>Risk level</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {correlations.map((c) => (
                    <tr key={c.entity_key_hash}>
                      <td>
                        <span className="mono" style={{ fontSize: "0.78rem" }}>{shortHash(c.entity_key_hash)}</span>
                      </td>
                      <td>
                        <span style={{ fontWeight: 700, color: c.partner_count >= 3 ? "var(--danger)" : "var(--warning)" }}>
                          {c.partner_count}
                        </span>
                      </td>
                      <td className="muted" style={{ fontSize: "0.75rem" }}>{c.partner_ids.join(", ")}</td>
                      <td>
                        <span style={{ color: c.max_confidence >= 0.7 ? "var(--risk-high)" : "var(--accent)" }}>
                          {c.max_confidence.toFixed(2)}
                        </span>
                      </td>
                      <td>
                        <span className={`risk-badge ${riskClass(c.risk_level)}`}>{c.risk_level}</span>
                      </td>
                      <td className="muted" style={{ fontSize: "0.76rem" }}>
                        {new Date(c.last_seen).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Architecture note */}
          <div className="panel" style={{ borderColor: "rgba(79,195,247,.2)", marginTop: 0 }}>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
              <AlertTriangle size={15} color="var(--info)" style={{ marginTop: 2, flexShrink: 0 }} />
              <p style={{ fontSize: "0.8rem", opacity: 0.7, lineHeight: 1.6 }}>
                <strong>Privacy model:</strong> Edge agents hash entity identifiers with the shared{" "}
                <span className="mono">NATIONAL_SALT</span> before sending to the hub. Raw phone numbers, account
                numbers and IPs never leave the partner's premises. The hub sees only HMAC-SHA256 digests — correlation
                is possible because all partners use the same salt.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
