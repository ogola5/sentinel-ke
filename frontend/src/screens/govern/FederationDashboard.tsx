import { useEffect, useMemo, useState } from "react";
import { Globe, RefreshCw, Loader, Network, Link2, AlertTriangle, Play, Radio } from "lucide-react";
import ArchitectureFlow from "../../app/ArchitectureFlow";
import { startDemoScenario } from "../../api/ai";
import {
  fetchEdgeSyncStatus,
  fetchFederationCorrelations,
  fetchFederationPartners,
  fetchFederationPatterns,
} from "../../api/federation";
import type { ScreenId } from "../../app/navigation";
import { DEMO_SCENARIOS, type DemoScenarioCard, type DemoScenarioId } from "../../demo/scenarios";
import type {
  FederationCorrelation,
  FederationEdgeSyncStatus,
  FederationPartner,
  FederationPattern,
} from "../../types/federation";

type FederationDashboardProps = {
  onNavigate?: (screen: ScreenId) => void;
};

const FEDERATION_DEMO_IDS: DemoScenarioId[] = [
  "federated_vpn",
  "federated_sim_swap",
  "federated_malware",
];

const SCREEN_LABELS: Record<ScreenId, string> = {
  command: "Command",
  live: "Live Feed",
  graph: "Threat Graph",
  investigate: "Investigate",
  campaigns: "Campaigns",
  cases: "Cases",
  defense: "Defense",
  ops: "Dashboard",
  reports: "Reports",
  timeline: "Service Indicators",
  infra: "Infra Correlation",
  gnn: "GNN Intelligence",
  crypto: "Crypto Posture",
  corruption: "Corruption Intel",
  federation: "Federation",
  audit: "Audit",
  exec: "Crisis Brief",
  onboard: "Agency Onboarding",
  users: "User Management",
};

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

function partnerNamesFor(partnerIds: string[], partners: FederationPartner[]): string {
  const names = partnerIds.map((partnerId) => (
    partners.find((partner) => partner.partner_id === partnerId)?.partner_name ?? partnerId
  ));
  return names.join(", ");
}

function correlationStory(
  correlation: FederationCorrelation,
  partners: FederationPartner[],
): { headline: string; detail: string } {
  const families = new Set((correlation.fraud_families ?? []).map((value) => value.toLowerCase()));
  const flags = new Set((correlation.all_risk_flags ?? []).map((value) => value.toLowerCase()));
  const seenIn = partnerNamesFor(correlation.partner_ids, partners);
  if (families.has("vpn_reuse") || flags.has("shared_access_infrastructure")) {
    return {
      headline: "Shared VPN exit across partners",
      detail: `The same masked access infrastructure is being seen by ${seenIn}. This is the national signal that one institution would miss alone.`,
    };
  }
  if (families.has("sim_swap") || flags.has("sim_swap_velocity") || flags.has("shared_actor_hash")) {
    return {
      headline: "Same SIM-swap actor across telco and banks",
      detail: `The same actor fingerprint is visible across ${seenIn}, linking telco takeover, bank access, and downstream wallet movement into one chain.`,
    };
  }
  if (families.has("malware_c2") || flags.has("shared_malware_ioc") || flags.has("c2_domain")) {
    return {
      headline: "Shared malware IOC across banks and CERT",
      detail: `The same malware infrastructure is touching ${seenIn}, which is why the hub can raise one national warning rather than three disconnected sightings.`,
    };
  }
  return {
    headline: "Cross-agency warning match",
    detail: `A shared warning pattern is visible across ${seenIn}. The hub only sees the correlation metadata, not each partner's raw telemetry.`,
  };
}

export default function FederationDashboard({ onNavigate }: FederationDashboardProps) {
  const [partners, setPartners] = useState<FederationPartner[]>([]);
  const [patterns, setPatterns] = useState<FederationPattern[]>([]);
  const [correlations, setCorrelations] = useState<FederationCorrelation[]>([]);
  const [edgeSync, setEdgeSync] = useState<FederationEdgeSyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPartner, setSelectedPartner] = useState<string>("");
  const [busyScenario, setBusyScenario] = useState<DemoScenarioId | null>(null);
  const [demoStatus, setDemoStatus] = useState<string | null>(null);
  const [demoTone, setDemoTone] = useState<"info" | "success" | "error">("info");

  const federationScenarios = useMemo(
    () => DEMO_SCENARIOS.filter((scenario) => FEDERATION_DEMO_IDS.includes(scenario.id)),
    [],
  );

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

  const runScenario = async (scenario: DemoScenarioCard) => {
    setBusyScenario(scenario.id);
    setDemoTone("info");
    setDemoStatus(null);
    try {
      const result = await startDemoScenario(scenario.id);
      setDemoTone("success");
      setDemoStatus(`${scenario.label} accepted. Refreshing partner and correlation state now.`);
      await load();
      setDemoStatus(
        `${scenario.label} accepted. ${result.message ?? "Partner telemetry and correlation state refreshed."}`,
      );
    } catch (err) {
      setDemoTone("error");
      setDemoStatus(
        `${scenario.label} failed: ${err instanceof Error ? err.message : "scenario_start_failed"}`,
      );
    } finally {
      setBusyScenario(null);
    }
  };

  const selectedPartnerPatterns = patterns.filter((pt) => pt.partner_id === selectedPartner);
  const activePartners = partners.filter((p) => p.status === "online").length;
  const stalePartners = partners.filter((p) => p.status === "stale").length;
  const offlinePartners = partners.filter((p) => p.status === "offline").length;
  const totalPatterns = patterns.length;
  const attentionPartners = stalePartners + offlinePartners;
  const leadCorrelation = correlations[0] ?? null;
  const leadCorrelationStory = leadCorrelation ? correlationStory(leadCorrelation, partners) : null;
  const selectedPartnerRecord = partners.find((item) => item.partner_id === selectedPartner) ?? null;

  return (
    <div>
      <div className="screen-header">
        <div>
          <p className="eyebrow">S15</p>
          <h2 style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Globe size={20} color="var(--accent)" />
            Federation Network
          </h2>
          <p className="subtle">See how partner edges share hashes, how the hub correlates them, and where warnings go next.</p>
        </div>
        <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader size={13} /> : <RefreshCw size={13} />}
          &nbsp;Refresh
        </button>
      </div>

      <ArchitectureFlow
        label="Federation flow"
        title="How agencies share without exposing raw data"
        summary="Raw telemetry stays at the partner edge. The hub only receives hashed warning patterns and correlation metadata."
        steps={[
          { stage: "Agency edge", title: "Local raw telemetry", detail: "VPN, fraud, malware, or service signals stay inside the partner perimeter.", tone: "info" },
          { stage: "Hash", title: "Pattern digest only", detail: "The edge publishes hashes, scores, and warning families rather than raw identifiers.", tone: "accent" },
          { stage: "Hub", title: "Cross-agency correlation", detail: "The hub measures partner freshness and finds shared threat patterns.", tone: "warning" },
          { stage: "Warning", title: "Return to local action", detail: "Partners receive warning envelopes and resolve them back to local entities on the edge.", tone: "danger" },
        ]}
      />

      <div className="panel workflow-stage-panel" style={{ marginBottom: 16 }}>
        <div className="panel-header">
          <h3>Live federation controls</h3>
          <span className="muted">Make the shared national signal appear, then open the proof screen</span>
        </div>
        <div className="workflow-summary-banner" style={{ marginBottom: 14 }}>
          <div>
            <strong>1. Launch a shared signal</strong>
            <span className="muted">Use VPN, SIM-swap, or malware to make multiple partners light up together.</span>
          </div>
          <div>
            <strong>2. Refresh is automatic</strong>
            <span className="muted">This screen reloads partners, patterns, and correlations after the replay is accepted.</span>
          </div>
          <div>
            <strong>3. Then pivot</strong>
            <span className="muted">Open Threat Graph, Investigate, or Live Feed to show the supporting local evidence.</span>
          </div>
        </div>

        {demoStatus && (
          <div className={`scenario-status scenario-status-${demoTone}`} style={{ marginBottom: 14 }}>
            {demoStatus}
          </div>
        )}

        <div className="scenario-launcher-grid">
          {federationScenarios.map((scenario) => {
            const running = busyScenario === scenario.id;
            return (
              <article key={scenario.id} className="scenario-card">
                <div className="scenario-card-head">
                  <div>
                    <p className="eyebrow" style={{ marginBottom: 6 }}>Federation scenario</p>
                    <h4>{scenario.label}</h4>
                    <p className="muted" style={{ marginTop: 6 }}>{scenario.summary}</p>
                  </div>
                  <div className="scenario-card-icon">
                    <Radio size={18} />
                  </div>
                </div>
                <div className="scenario-screen-row">
                  <span className="scenario-screen-chip">This screen: shared match</span>
                  <span className="scenario-screen-chip">Then {SCREEN_LABELS[scenario.followUpScreen]}</span>
                </div>
                <div className="scenario-detail-block">
                  <strong>What to point at</strong>
                  <p className="muted">{scenario.expectedOutput}</p>
                </div>
                <div className="scenario-action-row">
                  <button type="button" className="ghost" onClick={() => void runScenario(scenario)} disabled={busyScenario != null}>
                    {running ? <Loader size={13} className="spin" /> : <Play size={13} />}
                    &nbsp;Simulate now
                  </button>
                  {onNavigate && (
                    <button type="button" className="ghost" onClick={() => onNavigate(scenario.followUpScreen)}>
                      Open {SCREEN_LABELS[scenario.followUpScreen]}
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </div>

      {error && (
        <div className="panel" style={{ marginBottom: 16, borderColor: "rgba(255,69,58,.28)", background: "rgba(255,69,58,.08)" }}>
          <div className="info-note" style={{ color: "var(--risk-high)" }}>
            <AlertTriangle size={13} style={{ flexShrink: 0 }} />
            <span>{error}</span>
          </div>
        </div>
      )}

      {edgeSync?.is_edge_node && (
        <details className="panel panel-details" open style={{ marginBottom: 16, borderColor: "rgba(var(--info-rgb), 0.24)", background: "rgba(var(--info-rgb), 0.07)" }}>
          <summary>
            <span>Local edge sync state</span>
            <span className="muted">{edgeSync.partner_id}</span>
          </summary>
          <div className="detail-grid" style={{ marginTop: 12 }}>
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
        </details>
      )}

      {loading ? (
        <div className="state-box">
          <Loader size={24} />
          <p>Loading federation data…</p>
        </div>
      ) : partners.length === 0 ? (
        <div className="panel">
          <div className="state-box">
            <Network size={32} />
            {edgeSync?.is_edge_node ? (
              <>
                <p>This edge node is connected locally, but the national partner roster is reviewed from the central hub.</p>
                <p>Use the hub Federation workspace to show all agencies and cross-agency matches.</p>
              </>
            ) : (
              <>
                <p>No federation partners registered yet.</p>
                <p>POST /v1/federation/register to onboard a partner edge agent.</p>
              </>
            )}
          </div>
        </div>
      ) : (
        <>
          <div className="focus-layout">
            <div className="panel focus-hero focus-hero-accent">
              <p className="focus-kicker">Federated posture</p>
              <p className="focus-value">{activePartners} live partners</p>
              <p className="focus-copy">
                Agencies keep raw telemetry locally. The hub only sees warning hashes, partner freshness, and correlation strength. This is the national proof surface for privacy-preserving intelligence sharing.
              </p>
              <div className="focus-stat-grid">
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Registered</div>
                  <div className="focus-stat-value">{partners.length}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Need attention</div>
                  <div className="focus-stat-value" style={{ color: attentionPartners > 0 ? "var(--warning)" : "var(--accent)" }}>
                    {attentionPartners}
                  </div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Patterns</div>
                  <div className="focus-stat-value">{totalPatterns}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Matches</div>
                  <div className="focus-stat-value">{correlations.length}</div>
                </div>
              </div>
              {leadCorrelation && (
                <div className="priority-card" style={{ marginTop: 18 }}>
                  <div className="priority-card-head">
                    <div>
                      <h4 className="priority-card-title">
                        {leadCorrelationStory?.headline ?? "Current cross-agency proof"}
                      </h4>
                      <p className="priority-card-copy">
                        {leadCorrelationStory?.detail} Hash {shortHash(leadCorrelation.entity_key_hash)} is shared by {leadCorrelation.partner_count} partners with {leadCorrelation.max_confidence.toFixed(2)} max confidence.
                      </p>
                    </div>
                    <span className={`risk-badge ${riskClass(leadCorrelation.risk_level)}`}>{leadCorrelation.risk_level}</span>
                  </div>
                </div>
              )}
            </div>

            <div className="panel priority-stack">
              <div className="panel-header">
                <h3>Who sees what</h3>
                <span className="muted">The privacy boundary, made explicit</span>
              </div>
              <div className="visibility-grid">
                <div className="visibility-card">
                  <h4>Agency edge sees</h4>
                  <p>Raw accounts, raw phones, raw hostnames, local telemetry, local evidence, and local response controls.</p>
                </div>
                <div className="visibility-card">
                  <h4>Hub sees</h4>
                  <p>Hashes, warning families, confidence, partner freshness, and cross-agency matches, but not raw identifiers.</p>
                </div>
              </div>
              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">{selectedPartnerRecord?.partner_name ?? "Selected partner"}</h4>
                    <p className="priority-card-copy">
                      {selectedPartnerRecord
                        ? `${partnerFreshnessLabel(selectedPartnerRecord)} · ${selectedPartnerRecord.model_version ?? "no model heartbeat yet"} · ${selectedPartnerRecord.data_source ?? "unknown source"}`
                        : "Select a partner to review its latest warning flow."}
                    </p>
                  </div>
                  {selectedPartnerRecord ? (
                    <span className="risk-badge" style={{ color: partnerStatusTone(selectedPartnerRecord.status), borderColor: `${partnerStatusTone(selectedPartnerRecord.status)}55` }}>
                      {selectedPartnerRecord.status.replace("_", " ")}
                    </span>
                  ) : null}
                </div>
              </div>
            </div>
          </div>

          <details className="panel panel-details" open>
            <summary>
              <span>Partner heartbeat roster</span>
              <span className="muted">{partners.length} partner edges</span>
            </summary>
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
                    </div>
                  </div>
                );
              })}
            </div>
          </details>

          <details className="panel panel-details">
            <summary>
              <span>Recent patterns</span>
              <span className="muted">{selectedPartner || "No partner selected"}</span>
            </summary>
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
                        <td className="muted" style={{ fontSize: "0.78rem" }}>{pt.fraud_family ?? pt.pattern_type}</td>
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
          </details>

          <details className="panel panel-details">
            <summary>
              <span>
                <Link2 size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />
                Cross-partner correlations
              </span>
              <span className="muted">{correlations.length} matches</span>
            </summary>
            {correlations.length === 0 ? (
              <div className="state-box" style={{ padding: 24 }}>
                <Network size={22} />
                <p>No correlations found yet. Partners must use the same NATIONAL_SALT for entity hashing.</p>
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Story</th>
                    <th>Entity hash</th>
                    <th>Partners</th>
                    <th>Seen in</th>
                    <th>Max confidence</th>
                    <th>Risk level</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {correlations.map((c) => {
                    const story = correlationStory(c, partners);
                    return (
                    <tr key={c.entity_key_hash}>
                      <td style={{ minWidth: 260 }}>
                        <strong>{story.headline}</strong>
                        <p className="muted" style={{ marginTop: 4, fontSize: "0.74rem" }}>
                          {story.detail}
                        </p>
                      </td>
                      <td>
                        <span className="mono" style={{ fontSize: "0.78rem" }}>{shortHash(c.entity_key_hash)}</span>
                      </td>
                      <td>
                        <span style={{ fontWeight: 700, color: c.partner_count >= 3 ? "var(--danger)" : "var(--warning)" }}>
                          {c.partner_count}
                        </span>
                      </td>
                      <td className="muted" style={{ fontSize: "0.75rem" }}>{partnerNamesFor(c.partner_ids, partners)}</td>
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
                    );
                  })}
                </tbody>
              </table>
            )}
          </details>

          <details className="panel panel-details" style={{ borderColor: "rgba(79,195,247,.2)", marginTop: 0 }}>
            <summary>
              <span>Privacy model</span>
              <span className="muted">How correlation stays privacy-preserving</span>
            </summary>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-start", marginTop: 12 }}>
              <AlertTriangle size={15} color="var(--info)" style={{ marginTop: 2, flexShrink: 0 }} />
              <p style={{ fontSize: "0.8rem", opacity: 0.7, lineHeight: 1.6 }}>
                <strong>Privacy model:</strong> Edge agents hash entity identifiers with the shared <span className="mono">NATIONAL_SALT</span> before publishing. Raw phone numbers, account numbers, emails, and IPs stay with the partner. The hub only correlates matching digests and warning metadata.
              </p>
            </div>
          </details>
        </>
      )}
    </div>
  );
}
