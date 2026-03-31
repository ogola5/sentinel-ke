import { useEffect, useState } from "react";
import {
  Zap, CheckCircle, Loader, Copy, RefreshCw,
  Link2, Radio, Shield, Users, Globe, Info, AlertTriangle,
  ChevronDown, ChevronUp, Terminal, Play,
} from "lucide-react";
import { apiCreateUser, apiListUsers } from "../../api/auth";
import { startDemoScenario } from "../../api/ai";
import { resolveApiBase } from "../../api/endpoints";
import { registerFederationPartner, type PartnerRegistrationResult } from "../../api/federation";
import type { ScreenId } from "../../app/navigation";
import { DEMO_SCENARIOS, type DemoScenarioCard, type DemoScenarioId } from "../../demo/scenarios";
import { KENYA_AGENCIES, agencyColor } from "../../types/auth";
import type { AuthUser } from "../../types/auth";

// ── Per-agency test account spec ──────────────────────────────────────────────
const AGENCY_SPECS = Object.entries(KENYA_AGENCIES).map(([code, meta]) => ({
  code,
  name: meta.name,
  color: meta.color,
  username: `${code.toLowerCase()}_test`,
  role: code === "EACC" || code === "OAG" ? "auditor" : "analyst",
}));

// ── Default password for all test accounts (can be changed) ──────────────────
const DEFAULT_TEST_PASSWORD = "Sentinel@Test2025!";

// ── Connection method tabs ────────────────────────────────────────────────────
type ConnTab = "ingest" | "federation" | "edge" | "scoping";

type AgencyOnboardingProps = {
  onNavigate?: (screen: ScreenId) => void;
};

const FEDERATION_DEMO_PARTNERS = [
  { partner_id: "safaricom-ke", partner_name: "Safaricom PLC", partner_type: "telco" },
  { partner_id: "kcb-bank-ke", partner_name: "KCB Bank Kenya", partner_type: "bank" },
  { partner_id: "equity-bank-ke", partner_name: "Equity Bank Kenya", partner_type: "bank" },
  { partner_id: "ke-cirt", partner_name: "KE-CIRT / National Response", partner_type: "government" },
] as const;

const FEDERATION_DEMO_IDS: DemoScenarioId[] = [
  "federated_vpn",
  "federated_sim_swap",
  "federated_malware",
];

function copyText(text: string) {
  void navigator.clipboard.writeText(text);
}

function CodeBlock({ code, label }: { code: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const handle = () => {
    copyText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };
  return (
    <div style={{ position: "relative", marginBottom: 14 }}>
      {label && <p className="label" style={{ marginBottom: 6 }}>{label}</p>}
      <pre className="code-block">{code}</pre>
      <button type="button" className="code-copy-btn" onClick={handle}>
        {copied ? <CheckCircle size={12} color="var(--accent)" /> : <Copy size={12} />}
      </button>
    </div>
  );
}

// ── Status badge per agency row ───────────────────────────────────────────────
interface AgencyRowState {
  code: string;
  exists: boolean;
  user: AuthUser | null;
  creating: boolean;
  done: boolean;
  error: string;
  password: string;
}

export default function AgencyOnboarding({ onNavigate }: AgencyOnboardingProps) {
  const [rows, setRows] = useState<AgencyRowState[]>(
    AGENCY_SPECS.map((s) => ({
      code: s.code, exists: false, user: null,
      creating: false, done: false, error: "", password: DEFAULT_TEST_PASSWORD,
    })),
  );
  const [loading, setLoading]       = useState(true);
  const [bulkCreating, setBulkCreating] = useState(false);
  const [bulkDone, setBulkDone]     = useState(false);
  const [connTab, setConnTab]       = useState<ConnTab>("ingest");
  const [selectedAgency, setSelectedAgency] = useState(AGENCY_SPECS[0].code);
  const [expandedSection, setExpandedSection] = useState<string | null>("accounts");
  const [registering, setRegistering]   = useState(false);
  const [regResult, setRegResult]       = useState<PartnerRegistrationResult | null>(null);
  const [regError, setRegError]         = useState("");
  const [demoPartnerBusy, setDemoPartnerBusy] = useState(false);
  const [demoPartnerStatus, setDemoPartnerStatus] = useState<string | null>(null);
  const [demoScenarioBusy, setDemoScenarioBusy] = useState<DemoScenarioId | null>(null);
  const [demoScenarioStatus, setDemoScenarioStatus] = useState<string | null>(null);
  const [demoScenarioTone, setDemoScenarioTone] = useState<"info" | "success" | "error">("info");
  const federationScenarios = DEMO_SCENARIOS.filter((scenario) => FEDERATION_DEMO_IDS.includes(scenario.id));

  const load = async () => {
    setLoading(true);
    try {
      const result = await apiListUsers();
      const userMap = new Map(result.items.map((u) => [u.section_code ?? "", u]));
      setRows((prev) =>
        prev.map((r) => {
          const u = userMap.get(r.code) ?? null;
          return { ...r, exists: u !== null, user: u, done: u !== null };
        }),
      );
    } catch {
      // silently continue — list may fail if not admin
    }
    setLoading(false);
  };

  useEffect(() => { void load(); }, []);

  const createOne = async (code: string, password: string) => {
    const spec = AGENCY_SPECS.find((s) => s.code === code);
    if (!spec) return;
    setRows((prev) => prev.map((r) => r.code === code ? { ...r, creating: true, error: "" } : r));
    try {
      const u = await apiCreateUser({
        username: spec.username,
        display_name: `${spec.name} — Test Account`,
        password,
        role: spec.role,
        access_level: "section",
        section_code: code,
      });
      setRows((prev) =>
        prev.map((r) => r.code === code ? { ...r, creating: false, done: true, exists: true, user: u, password } : r),
      );
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail ?? String(err);
      const msg = detail === "username_conflict" ? "Account already exists." : detail;
      setRows((prev) => prev.map((r) => r.code === code ? { ...r, creating: false, error: msg } : r));
    }
  };

  const createAll = async () => {
    setBulkCreating(true);
    const pending = rows.filter((r) => !r.exists);
    for (const r of pending) {
      await createOne(r.code, r.password);
    }
    setBulkCreating(false);
    setBulkDone(true);
  };

  const allExist = rows.every((r) => r.exists);
  const pendingCount = rows.filter((r) => !r.exists).length;

  const toggle = (section: string) =>
    setExpandedSection((p) => (p === section ? null : section));

  const sel = AGENCY_SPECS.find((s) => s.code === selectedAgency)!;

  const handleRegisterPartner = async () => {
    setRegistering(true);
    setRegError("");
    setRegResult(null);
    try {
      const result = await registerFederationPartner({
        partner_id:   sel.code.toLowerCase(),
        partner_name: sel.name,
        partner_type: "government",
      });
      setRegResult(result);
    } catch (err) {
      setRegError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setRegistering(false);
    }
  };

  const handleRegisterDemoPartners = async () => {
    setDemoPartnerBusy(true);
    setDemoPartnerStatus(null);
    const outcomes: string[] = [];
    try {
      for (const partner of FEDERATION_DEMO_PARTNERS) {
        try {
          await registerFederationPartner(partner);
          outcomes.push(`${partner.partner_name} registered`);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          if (message.toLowerCase().includes("already registered")) {
            outcomes.push(`${partner.partner_name} already present`);
            continue;
          }
          throw err;
        }
      }
      setDemoPartnerStatus(outcomes.join(" · "));
    } catch (err) {
      setDemoPartnerStatus(err instanceof Error ? err.message : "demo_partner_registration_failed");
    } finally {
      setDemoPartnerBusy(false);
    }
  };

  const handleDemoScenario = async (scenario: DemoScenarioCard) => {
    setDemoScenarioBusy(scenario.id);
    setDemoScenarioStatus(null);
    setDemoScenarioTone("info");
    try {
      const result = await startDemoScenario(scenario.id);
      setDemoScenarioTone("success");
      setDemoScenarioStatus(`${scenario.label} accepted. ${result.message ?? "Shared partner activity refreshed."}`);
    } catch (err) {
      setDemoScenarioTone("error");
      setDemoScenarioStatus(
        `${scenario.label} failed: ${err instanceof Error ? err.message : "scenario_start_failed"}`,
      );
    } finally {
      setDemoScenarioBusy(null);
    }
  };

  const API_BASE =
    resolveApiBase() ||
    (typeof window !== "undefined" ? `${window.location.origin}/v1` : "/v1");

  return (
    <div>
      <div className="screen-header">
        <div>
          <p className="eyebrow">S14</p>
          <h2 style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Zap size={20} color="var(--accent)" />
            Agency Onboarding
          </h2>
          <p className="subtle">Accounts, integration paths, source data, and test workflow.</p>
        </div>
        <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader size={13} /> : <RefreshCw size={13} />} &nbsp;Refresh
        </button>
      </div>

      <div className="panel workflow-stage-panel" style={{ marginBottom: 16 }}>
        <div className="panel-header">
          <h3>Federation onboarding and activation</h3>
          <span className="muted">Bring partners online, then activate a shared national signal</span>
        </div>
        <div className="workflow-summary-banner" style={{ marginBottom: 14 }}>
          <div>
            <strong>1. Register federation partners</strong>
            <span className="muted">Creates the bank, telco, and national-response partner roster used by the federation scenarios.</span>
          </div>
          <div>
            <strong>2. Activate a shared signal</strong>
            <span className="muted">Use VPN, SIM-swap, or malware to make partner activity appear across the hub.</span>
          </div>
          <div>
            <strong>3. Show the result</strong>
            <span className="muted">Open Command Agency Network or Federation to show online partners and shared warning matches.</span>
          </div>
        </div>

        <div className="scenario-action-row" style={{ marginBottom: 14, flexWrap: "wrap" }}>
          <button type="button" className="btn-accent" onClick={() => void handleRegisterDemoPartners()} disabled={demoPartnerBusy}>
            {demoPartnerBusy ? <Loader size={13} className="spin" /> : <Radio size={13} />}
            &nbsp;Register federation partners
          </button>
          {onNavigate && (
            <>
              <button type="button" className="ghost" onClick={() => onNavigate("command")}>
                Open Command
              </button>
              <button type="button" className="ghost" onClick={() => onNavigate("federation")}>
                Open Federation
              </button>
            </>
          )}
        </div>

        {demoPartnerStatus && (
          <div className="scenario-status scenario-status-info" style={{ marginBottom: 14 }}>
            {demoPartnerStatus}
          </div>
        )}

        {demoScenarioStatus && (
          <div className={`scenario-status scenario-status-${demoScenarioTone}`} style={{ marginBottom: 14 }}>
            {demoScenarioStatus}
          </div>
        )}

        <div className="scenario-launcher-grid">
          {federationScenarios.map((scenario) => (
            <article key={scenario.id} className="scenario-card">
              <div className="scenario-card-head">
                <div>
                  <p className="eyebrow" style={{ marginBottom: 6 }}>Federation flow</p>
                  <h4>{scenario.label}</h4>
                  <p className="muted" style={{ marginTop: 6 }}>{scenario.summary}</p>
                </div>
                <div className="scenario-card-icon">
                  <Globe size={18} />
                </div>
              </div>
              <div className="scenario-detail-block">
                <strong>Expected result</strong>
                <p className="muted">{scenario.expectedOutput}</p>
              </div>
              <div className="scenario-action-row">
                <button
                  type="button"
                  className="ghost"
                  onClick={() => void handleDemoScenario(scenario)}
                  disabled={demoScenarioBusy != null}
                >
                  {demoScenarioBusy === scenario.id ? <Loader size={13} className="spin" /> : <Play size={13} />}
                  &nbsp;Activate now
                </button>
                {onNavigate && (
                  <button type="button" className="ghost" onClick={() => onNavigate("federation")}>
                    Open Federation
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      </div>

      {/* ════════════════════════════════════════════════
          SECTION 1 — Agency Test Accounts
          ════════════════════════════════════════════════ */}
      <div className="panel" style={{ marginBottom: 16 }}>
        <div
          className="collapsible-header"
          onClick={() => toggle("accounts")}
          style={{ cursor: "pointer" }}
        >
          <h3><Users size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />Agency Test Accounts</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="muted">{rows.filter((r) => r.exists).length} / {rows.length} created</span>
            {expandedSection === "accounts" ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
        </div>

        {expandedSection === "accounts" && (
          <>
            {/* Bulk action */}
            {!allExist && (
              <div style={{ display: "flex", gap: 12, alignItems: "center", margin: "14px 0 16px" }}>
                <button
                  type="button"
                  className="btn-accent"
                  onClick={() => void createAll()}
                  disabled={bulkCreating || allExist}
                >
                  {bulkCreating
                    ? <><Loader size={13} className="spin" /> &nbsp;Creating {pendingCount} accounts…</>
                    : <><Zap size={13} /> &nbsp;Create All {pendingCount} Missing Accounts</>
                  }
                </button>
                {bulkDone && (
                  <span style={{ color: "var(--accent)", fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 6 }}>
                    <CheckCircle size={14} /> All agency accounts ready
                  </span>
                )}
                <span className="muted" style={{ fontSize: "0.78rem" }}>
                  Default password: <span className="mono-inline">{DEFAULT_TEST_PASSWORD}</span>
                </span>
              </div>
            )}
            {allExist && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--accent)", margin: "14px 0 16px", fontSize: "0.84rem" }}>
                <CheckCircle size={15} /> All agency test accounts exist. You can log in as any agency.
              </div>
            )}

            {/* Per-agency rows */}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {AGENCY_SPECS.map((spec) => {
                const row = rows.find((r) => r.code === spec.code)!;
                return (
                  <div key={spec.code} className={`agency-row ${row.exists ? "exists" : "missing"}`}>
                    {/* Agency identity */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 200 }}>
                      <span
                        style={{
                          fontFamily: "JetBrains Mono, monospace",
                          fontWeight: 700,
                          fontSize: "0.85rem",
                          color: agencyColor(spec.code),
                          minWidth: 50,
                        }}
                      >
                        {spec.code}
                      </span>
                      <span style={{ fontSize: "0.78rem", opacity: 0.65 }}>{spec.name}</span>
                    </div>

                    {/* Credentials */}
                    <div style={{ display: "flex", gap: 10, alignItems: "center", flex: 1, flexWrap: "wrap" }}>
                      <span className="mono-inline" style={{ fontSize: "0.75rem" }}>{spec.username}</span>
                      <span className="muted" style={{ fontSize: "0.72rem" }}>role: {spec.role}</span>
                    </div>

                    {/* Status / action */}
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {row.exists ? (
                        <span style={{ display: "flex", alignItems: "center", gap: 5, color: "var(--accent)", fontSize: "0.8rem" }}>
                          <CheckCircle size={14} /> Ready
                        </span>
                      ) : row.creating ? (
                        <Loader size={14} className="spin" />
                      ) : row.error ? (
                        <span style={{ color: "var(--danger)", fontSize: "0.78rem" }}>{row.error}</span>
                      ) : (
                        <button
                          type="button"
                          className="btn-ghost"
                          style={{ padding: "4px 12px", fontSize: "0.78rem" }}
                          onClick={() => void createOne(spec.code, row.password)}
                        >
                          Create
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Login instructions */}
            <details className="collapsible-panel" style={{ marginTop: 16 }}>
              <summary>
                <span>How to test an agency account</span>
                <span className="muted">Login, verify scoped view, switch back to admin</span>
              </summary>
              <ol style={{ fontSize: "0.78rem", lineHeight: 1.8, margin: 0, paddingLeft: 20, opacity: 0.75 }}>
                <li>Click <strong>Logout</strong> from the sidebar.</li>
                <li>Enter the agency username manually, for example <span className="mono-inline">kps_test</span>.</li>
                <li>Use <span className="mono-inline">{DEFAULT_TEST_PASSWORD}</span> unless you changed it.</li>
                <li>Confirm the user sees only that agency&apos;s section-scoped data.</li>
                <li>Log back in as <strong>admin</strong> to return to the central view.</li>
              </ol>
            </details>
          </>
        )}
      </div>

      {/* ════════════════════════════════════════════════
          SECTION 2 — Agency Connection Guide
          ════════════════════════════════════════════════ */}
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="collapsible-header" onClick={() => toggle("connect")} style={{ cursor: "pointer" }}>
          <h3><Link2 size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />How Agencies Connect Their Systems</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="muted">4 integration methods</span>
            {expandedSection === "connect" ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
        </div>

        {expandedSection === "connect" && (
          <>
            <div className="workflow-summary-banner" style={{ margin: "14px 0 16px" }}>
              <div>
                <strong>Direct ingest</strong>
                <span className="muted">Use this when the agency can send canonical events to the hub. The hub receives the event stream and does the graph, scoring, and workflow centrally.</span>
              </div>
              <div>
                <strong>Federation</strong>
                <span className="muted">Use this when raw data must stay inside the agency. The local edge scores entities and sends only hashed high-risk patterns to the hub.</span>
              </div>
              <div>
                <strong>Best data source</strong>
                <span className="muted">Connect to event streams, APIs, SIEM exports, webhooks, or scheduled JSON/CSV drops first. Read-only database access is the fallback, not the default.</span>
              </div>
            </div>

            <div className="info-note" style={{ marginBottom: 16 }}>
              <Info size={13} style={{ flexShrink: 0 }} />
              <span>
                Think in terms of <span className="mono-inline">events over time</span>, not entire databases. Send auth, transaction, SIM swap, WAF, malware, service health, and audit events incrementally with their <span className="mono-inline">occurred_at</span> time. Sentinel-KE is strongest when agencies stream or batch new events continuously instead of dumping whole tables.
              </span>
            </div>

            {/* Agency selector */}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "14px 0 16px" }}>
              {AGENCY_SPECS.map((s) => (
                <button
                  key={s.code}
                  type="button"
                  className={`preset-btn ${selectedAgency === s.code ? "active" : ""}`}
                  onClick={() => setSelectedAgency(s.code)}
                >
                  {s.code}
                </button>
              ))}
            </div>

            {/* Method tabs */}
            <div className="conn-tabs">
              {([
                { id: "ingest",     label: "Direct Ingest API",       icon: <Radio size={13} /> },
                { id: "federation", label: "Federation Partner",       icon: <Globe size={13} /> },
                { id: "edge",       label: "Edge Agent (Docker)",      icon: <Terminal size={13} /> },
                { id: "scoping",    label: "Data Scoping Explained",   icon: <Shield size={13} /> },
              ] as const).map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`conn-tab ${connTab === t.id ? "active" : ""}`}
                  onClick={() => setConnTab(t.id)}
                >
                  {t.icon} {t.label}
                </button>
              ))}
            </div>

            <div style={{ marginTop: 16 }}>
              {connTab === "ingest" && (
                <div>
                  <p style={{ fontSize: "0.83rem", marginBottom: 14, opacity: 0.75, lineHeight: 1.6 }}>
                    Simplest path: {sel.name} sends canonical events straight to the ingest API. This is best when the agency already has a SIEM, webhook, event bus, or scheduled export job and is comfortable letting the hub process the raw operational events.
                  </p>
                  <CodeBlock
                    label="Send a security event"
                    code={`curl -X POST ${API_BASE}/v1/ingest/event \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: $INGEST_API_KEY" \\
  -d '{
    "event_type": "LOGIN_EVENT",
    "occurred_at": "2026-03-15T08:30:00Z",
    "classification": "RESTRICTED",
    "payload": {
      "service_id": "${sel.code.toLowerCase()}-auth",
      "endpoint": "/login",
      "status_code": 401,
      "user_id": "user-abc123",
      "ip": "41.89.10.24",
      "attempts": 12,
      "section_code": "${sel.code}"
    },
    "anchors": {
      "service_id": "${sel.code.toLowerCase()}-auth",
      "endpoint": "/login",
      "ip": "41.89.10.24"
    }
  }'`}
                  />
                  <CodeBlock
                    label="Send a bulk batch"
                    code={`curl -X POST ${API_BASE}/v1/ingest/batch \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: $INGEST_API_KEY" \\
  -d '[
    {
      "event_type": "LOGIN_EVENT",
      "occurred_at": "2026-03-15T08:30:00Z",
      "payload": { "service_id": "${sel.code.toLowerCase()}-auth", "endpoint": "/login", "status_code": 401, "section_code": "${sel.code}" },
      "anchors": { "service_id": "${sel.code.toLowerCase()}-auth", "endpoint": "/login" }
    }
  ]'`}
                  />
                  <div className="info-note">
                    <Info size={13} style={{ flexShrink: 0 }} />
                    <span>
                      Find your <span className="mono-inline">INGEST_API_KEY</span> in your <span className="mono-inline">.env</span> file.
                      Use the canonical envelope: <span className="mono-inline">event_type</span>, <span className="mono-inline">occurred_at</span>, <span className="mono-inline">payload</span>, and <span className="mono-inline">anchors</span>.
                      Put <span className="mono-inline">section_code: "{sel.code}"</span> inside the payload so the event remains attributable to {sel.name}.
                    </span>
                  </div>
                  <div className="info-note" style={{ marginTop: 10 }}>
                    <Radio size={13} style={{ flexShrink: 0 }} />
                    <span>
                      Preferred upstream sources: SIEM auth logs, core banking transaction feeds, telco SIM-swap feeds, WAF / DDoS logs, EDR / DFIR alerts, service health monitors, and audit exports. Use direct database reads only when the agency cannot expose an event stream or export job safely.
                    </span>
                  </div>
                </div>
              )}

              {connTab === "federation" && (
                <div>
                  <p style={{ fontSize: "0.83rem", marginBottom: 14, opacity: 0.75, lineHeight: 1.6 }}>
                    Federation shares privacy-preserving pattern hashes with the hub for cross-agency correlation. Use this when the agency wants to keep raw customer, account, host, or transaction data local and only expose high-risk scored patterns.
                  </p>

                  {/* ── Live register button ── */}
                  <div className="info-note" style={{ marginBottom: 16 }}>
                    <p className="label" style={{ marginBottom: 8 }}>Register {sel.name} as a federation partner</p>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={() => void handleRegisterPartner()}
                      disabled={registering || !!regResult}
                    >
                      {registering && <Loader size={12} className="spin" />}
                      {regResult ? <CheckCircle size={12} color="var(--accent)" /> : <Globe size={12} />}
                      {regResult ? "Registered — copy credentials below" : registering ? "Registering…" : `Register ${sel.code}`}
                    </button>
                    {regError && <p className="text-danger" style={{ marginTop: 8, fontSize: "0.8rem" }}>{regError}</p>}
                    {regResult && (
                      <div style={{ marginTop: 12 }}>
                        <p className="label" style={{ color: "var(--warning)", marginBottom: 6 }}>
                          ⚠ Copy these now — the API key cannot be retrieved again
                        </p>
                        <CodeBlock label="Paste into the agency station .env" code={
                          Object.entries(regResult.edge_agent_env)
                            .map(([k, v]) => `${k}=${v}`)
                            .join("\n")
                        } />
                        <CodeBlock label="Correlation salt" code={regResult.correlation_salt} />
                      </div>
                    )}
                  </div>

                  <CodeBlock
                    label="Step 1 — Register as a federation partner (curl alternative)"
                    code={`curl -X POST ${API_BASE}/v1/federation/register \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer <CENTRAL_ACCESS_TOKEN>" \\
  -d '{
    "partner_id": "${sel.code.toLowerCase()}",
    "partner_name": "${sel.name}",
    "partner_type": "government",
    "webhook_url": "https://${sel.code.toLowerCase()}-soc.go.ke/sentinel/webhook",
    "webhook_secret": "your-shared-secret-here"
  }'`}
                  />
                  <CodeBlock
                    label="Step 2 — Submit anonymised entity patterns"
                    code={`BODY='{
  "partner_id": "${sel.code.toLowerCase()}",
  "schema_version": "1.0",
  "window_start": "2026-03-15T08:00:00Z",
  "window_end": "2026-03-15T09:00:00Z",
  "gnn_model_version": "edge-gnn-v1",
  "high_risk_entities": [
    {
      "entity_key_hash": "HMAC-SHA256(phone_h:+254700000111, NATIONAL_SALT)",
      "entity_type": "phone_h",
      "risk_score": 0.87,
      "uncertainty": 0.12,
      "fraud_family": "sim_swap_chain",
      "chain_score": 0.76,
      "risk_flags": ["AML_FLAG", "VELOCITY_SPIKE"]
    }
  ],
  "summary": {
    "total_entities_scored": 120,
    "high_risk_count": 4,
    "mean_risk_score": 0.18
  }
}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$PARTNER_API_KEY" -hex | sed 's/^.* //')

curl -X POST ${API_BASE}/v1/federation/patterns \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: $PARTNER_API_KEY" \\
  -H "X-Sentinel-Signature: sha256=$SIG" \\
  -d "$BODY"`}
                  />
                  <div className="info-note">
                    <Info size={13} style={{ flexShrink: 0 }} />
                    <span>
                      The <span className="mono-inline">NATIONAL_SALT</span> must be shared securely with each partner,
                      and every federation submission must include a valid <span className="mono-inline">X-Sentinel-Signature</span>.
                      The hub correlates on <span className="mono-inline">entity_key_hash</span>, not on raw identifiers.
                    </span>
                  </div>
                  <div className="info-note" style={{ marginTop: 10 }}>
                    <Shield size={13} style={{ flexShrink: 0 }} />
                    <span>
                      In federation mode the agency usually installs a local Sentinel-KE edge or a thin forwarding worker. That local node reads the agency data, scores it locally, hashes the entity keys, and pushes only high-risk pattern summaries to the hub.
                    </span>
                  </div>
                </div>
              )}

              {connTab === "edge" && (
                <div>
                  <p style={{ fontSize: "0.83rem", marginBottom: 14, opacity: 0.75, lineHeight: 1.6 }}>
                    Use the edge agent when an agency needs a local install. This is the right model when data residency, local scoring, or sensitive transaction handling means the full raw stream should stay inside the agency.
                  </p>
                  <CodeBlock
                    label="docker-compose.yml (add to agency's stack)"
                    code={`sentinel-edge:
  image: sentinelke/edge-agent:latest
  environment:
    PARTNER_ID: "${sel.code.toLowerCase()}"
    PARTNER_NAME: "${sel.name}"
    HUB_URL: "${API_BASE}"
    HUB_API_KEY: "\${PARTNER_API_KEY}"
    NATIONAL_SALT: "\${NATIONAL_SALT_FROM_HUB}"
    HMAC_SALT: "\${GENERATE_UNIQUE_HMAC_SALT}"
    DATA_SOURCE: "demo"
    RUN_INTERVAL_S: "300"
    RETRAIN_EVERY: "12"
  restart: unless-stopped`}
                  />
                  <CodeBlock
                    label="Alternative: HTTP Forwarder (no Kafka needed)"
                    code={`# Point any SIEM/log forwarder to:
POST ${API_BASE}/v1/ingest/event
X-API-Key: <INGEST_API_KEY>
# with section_code: "${sel.code}" in every event body`}
                  />
                  <div className="info-note">
                    <AlertTriangle size={13} style={{ flexShrink: 0 }} color="var(--warning)" />
                    <span>
                      The edge agent Docker image is <em>not yet published</em> — this shows the intended
                      deployment pattern. The live registration flow now returns a copy-paste <span className="mono-inline">.env</span> block
                      with the exact keys the edge agent reads. For now, use the direct ingest API or write a simple forwarder
                      script that calls <span className="mono-inline">POST /v1/ingest/event</span>.
                    </span>
                  </div>
                  <div className="info-note" style={{ marginTop: 10 }}>
                    <Terminal size={13} style={{ flexShrink: 0 }} />
                    <span>
                      You do not normally install Sentinel-KE by attaching directly to every agency database. Prefer a feed from the agency&apos;s source systems: auth logs, transactions, SIM management, WAF, SIEM, DFIR, or scheduled exports. Only use read-only database extraction when there is no safer event interface.
                    </span>
                  </div>
                </div>
              )}

              {connTab === "scoping" && (
                <div>
                  <p style={{ fontSize: "0.83rem", marginBottom: 14, opacity: 0.75, lineHeight: 1.6 }}>
                    Section users stay inside one agency. Central users see the full national view. The important design question is not just who can log in, but which data model is being used: direct ingest or federation.
                  </p>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
                    <div className="scope-card">
                      <div className="scope-card-title" style={{ color: "var(--info)" }}>Direct ingest to hub</div>
                      <ul style={{ fontSize: "0.78rem", lineHeight: 1.9, margin: "8px 0 0", paddingLeft: 18 }}>
                        <li>Hub receives canonical raw events</li>
                        <li>Best for command visibility and faster rollout</li>
                        <li>Works well for time-series event streams</li>
                        <li>Examples: transactions, logins, WAF, service health, DFIR</li>
                      </ul>
                    </div>
                    <div className="scope-card">
                      <div className="scope-card-title" style={{ color: "var(--accent)" }}>Federation / edge mode</div>
                      <ul style={{ fontSize: "0.78rem", lineHeight: 1.9, margin: "8px 0 0", paddingLeft: 18 }}>
                        <li>Agency keeps raw sensitive data locally</li>
                        <li>Hub receives hashes, scores, and warning metadata</li>
                        <li>Best for sovereign multi-agency correlation</li>
                        <li>Examples: phone, account, host, supplier, entity matches</li>
                      </ul>
                    </div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
                    <div className="scope-card">
                      <div className="scope-card-title" style={{ color: "var(--info)" }}>Section Access (Agency)</div>
                      <ul style={{ fontSize: "0.78rem", lineHeight: 1.9, margin: "8px 0 0", paddingLeft: 18 }}>
                        <li>User has <span className="mono-inline">access_level: "section"</span></li>
                        <li>Assigned a <span className="mono-inline">section_code</span> (e.g. "KPS")</li>
                        <li>Sees <strong>only</strong> their agency&apos;s events, campaigns, and reports</li>
                        <li>Cannot see other agencies&apos; data or federation details</li>
                        <li>Cannot create users or access User Management</li>
                      </ul>
                    </div>
                    <div className="scope-card">
                      <div className="scope-card-title" style={{ color: "var(--accent)" }}>Central Access (Command)</div>
                      <ul style={{ fontSize: "0.78rem", lineHeight: 1.9, margin: "8px 0 0", paddingLeft: 18 }}>
                        <li>User has <span className="mono-inline">access_level: "central"</span></li>
                        <li>No <span className="mono-inline">section_code</span> restriction</li>
                        <li>Sees <strong>all agencies&apos;</strong> data in one view</li>
                        <li>Can access Federation Dashboard</li>
                        <li>Can create and manage user accounts</li>
                        <li>Has access to National Command Centre</li>
                      </ul>
                    </div>
                  </div>
                  <CodeBlock
                    label="Create a section-scoped (agency) account"
                    code={`POST ${API_BASE}/v1/auth/users
Authorization: Bearer <central-admin-token>

{
  "username": "${sel.code.toLowerCase()}_analyst_01",
  "password": "SecurePass@2025!",
  "role": "analyst",
  "access_level": "section",
  "section_code": "${sel.code}"
}`}
                  />
                  <CodeBlock
                    label="Create a central command account"
                    code={`POST ${API_BASE}/v1/auth/users
Authorization: Bearer <central-admin-token>

{
  "username": "central_soc_01",
  "password": "SecurePass@2025!",
  "role": "admin",
  "access_level": "central"
}`}
                  />
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* ════════════════════════════════════════════════
          SECTION 3 — Demo Data
          ════════════════════════════════════════════════ */}
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="collapsible-header" onClick={() => toggle("demo")} style={{ cursor: "pointer" }}>
          <h3><Terminal size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />Generate Demo Data for Testing</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="muted">Synthetic events + GNN training data</span>
            {expandedSection === "demo" ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
        </div>

        {expandedSection === "demo" && (
          <div style={{ marginTop: 14 }}>
            <p style={{ fontSize: "0.83rem", marginBottom: 14, opacity: 0.75, lineHeight: 1.6 }}>
              Use bootstrap to seed realistic scenarios and write predictions in one flow.
            </p>
            <CodeBlock
              label="Bootstrap cyber demo data end to end"
              code={`curl -X POST ${API_BASE}/v1/demo/bootstrap \\
  -H "Authorization: Bearer <CENTRAL_ACCESS_TOKEN>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "domain": "cyber",
    "scenario": "ddos_vpn_fraud",
    "epochs": 25,
    "cyber_runs": 10,
    "benign_per_run": 100,
    "seed_sources": true
  }'`}
            />
            <CodeBlock
              label="Bootstrap corruption demo data end to end"
              code={`curl -X POST ${API_BASE}/v1/demo/bootstrap \\
  -H "Authorization: Bearer <CENTRAL_ACCESS_TOKEN>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "domain": "corruption",
    "epochs": 25,
    "corruption_runs": 10,
    "benign_per_run": 100
  }'`}
            />
            <CodeBlock
              label="Bootstrap both domains in one run"
              code={`curl -X POST ${API_BASE}/v1/demo/bootstrap \\
  -H "Authorization: Bearer <CENTRAL_ACCESS_TOKEN>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "domain": "all",
    "scenario": "ddos_vpn_fraud",
    "epochs": 25,
    "cyber_runs": 10,
    "corruption_runs": 10,
    "benign_per_run": 100,
    "seed_sources": true
  }'`}
            />
            <div className="info-note">
              <Info size={13} style={{ flexShrink: 0 }} />
              <span>
                Use a central access token for bootstrap. The background job replays demo scenarios, seeds training data, and writes predictions.
                After bootstrap, return to the main dashboard and click <strong>Resync</strong>, then open <strong>GNN Intelligence</strong> to confirm the latest written run.
              </span>
            </div>
          </div>
        )}
      </div>

      {/* ════════════════════════════════════════════════
          SECTION 4 — Solo Dev Workflow Summary
          ════════════════════════════════════════════════ */}
      <div className="panel" style={{ borderColor: "rgba(192,132,252,.2)", background: "rgba(192,132,252,.03)" }}>
        <div className="collapsible-header" onClick={() => toggle("workflow")} style={{ cursor: "pointer" }}>
          <h3><Zap size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />Solo Developer Testing Workflow</h3>
          {expandedSection === "workflow" ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>

        {expandedSection === "workflow" && (
          <div style={{ marginTop: 14 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {[
                { num: "①", text: "Log in as admin (bootstrap credentials from .env)", color: "var(--accent)" },
                { num: "②", text: 'Go to COMMAND → Agency Onboarding → click "Create All Test Accounts"', color: "var(--accent)" },
                { num: "③", text: "Run the demo bootstrap command above so events, graph data, and predictions are written together", color: "var(--info)" },
                { num: "④", text: "Log out → enter kps_test on the login screen → enter test password → see KPS-only view", color: "var(--info)" },
                { num: "⑤", text: "Log out → enter dci_test → see DCI data — each agency is isolated", color: "var(--info)" },
                { num: "⑥", text: "Log in as admin → see everything across all agencies (Central Command)", color: "var(--accent)" },
                { num: "⑦", text: "Test containment: log in as an operator account → go to Defense Center → execute block_ip", color: "var(--warning)" },
                { num: "⑧", text: "Test federation: register mock partners via the curl commands above, then check Federation Network", color: "var(--warning)" },
              ].map((step) => (
                <div key={step.num} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: "1.1rem", color: step.color, flexShrink: 0, lineHeight: 1.3 }}>
                    {step.num}
                  </span>
                  <span style={{ fontSize: "0.83rem", lineHeight: 1.6, opacity: 0.8 }}>{step.text}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
