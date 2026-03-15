import { useEffect, useState } from "react";
import {
  Zap, CheckCircle, Loader, Copy, RefreshCw,
  Link2, Radio, Shield, Users, Globe, Info, AlertTriangle,
  ChevronDown, ChevronUp, Terminal,
} from "lucide-react";
import { apiCreateUser, apiListUsers } from "../../api/auth";
import { resolveApiBase } from "../../api/endpoints";
import { registerFederationPartner, type PartnerRegistrationResult } from "../../api/federation";
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

export default function AgencyOnboarding() {
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

  const API_BASE = resolveApiBase() || "http://localhost:8000";

  return (
    <div>
      <div className="screen-header">
        <h2>
          <Zap size={20} color="var(--accent)" />
          Agency Onboarding &amp; Setup
          <span className="subtitle">— test accounts · connection guide · solo dev workflow</span>
        </h2>
        <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader size={13} /> : <RefreshCw size={13} />} &nbsp;Refresh
        </button>
      </div>

      {/* ── How it works overview ── */}
      <div className="panel" style={{ marginBottom: 16, borderColor: "rgba(49,255,144,.2)", background: "rgba(49,255,144,.03)" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
          <Info size={15} color="var(--accent)" style={{ marginTop: 2, flexShrink: 0 }} />
          <div style={{ fontSize: "0.84rem", lineHeight: 1.7 }}>
            <strong>Architecture:</strong> Sentinel-KE is a single hub. Each agency logs in with their
            own account scoped to their <span className="mono-inline">section_code</span> — they see only
            their data. The Central Command account sees everything across all agencies.
            As a solo developer you can create test accounts here, switch between them, and simulate
            each agency's perspective without running separate instances.
          </div>
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
            <div style={{ marginTop: 16, padding: "14px 16px", background: "rgba(255,255,255,.03)", borderRadius: 10, border: "1px solid var(--line)" }}>
              <p style={{ fontSize: "0.8rem", marginBottom: 8, fontWeight: 600 }}>To test each agency:</p>
              <ol style={{ fontSize: "0.78rem", lineHeight: 1.8, margin: 0, paddingLeft: 20, opacity: 0.75 }}>
                <li>Click <strong>Logout</strong> (bottom of sidebar)</li>
                <li>On the login screen, enter the agency username manually (for example <span className="mono-inline">kps_test</span>)</li>
                <li>Password: <span className="mono-inline">{DEFAULT_TEST_PASSWORD}</span> (unless you changed it)</li>
                <li>You will see only <strong>that agency&apos;s data</strong> — scoped by section_code</li>
                <li>Log out, log back in as <strong>admin</strong> to see everything</li>
              </ol>
            </div>
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
                    The simplest integration. {sel.name} ({sel.code}) sends security events directly
                    to the Sentinel-KE Ingest API. No additional infrastructure needed.
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
                </div>
              )}

              {connTab === "federation" && (
                <div>
                  <p style={{ fontSize: "0.83rem", marginBottom: 14, opacity: 0.75, lineHeight: 1.6 }}>
                    Federation allows {sel.name} to share <strong>privacy-preserving pattern hashes</strong> with
                    the hub — raw identifiers (phone numbers, account numbers) never leave the agency&apos;s premises.
                    This enables cross-agency threat correlation.
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
                </div>
              )}

              {connTab === "edge" && (
                <div>
                  <p style={{ fontSize: "0.83rem", marginBottom: 14, opacity: 0.75, lineHeight: 1.6 }}>
                    For agencies with their own SOC infrastructure, deploy a lightweight Sentinel Edge Agent
                    that runs locally and forwards normalised events to the hub. Add this to the
                    agency&apos;s <span className="mono-inline">docker-compose.yml</span>:
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
                </div>
              )}

              {connTab === "scoping" && (
                <div>
                  <p style={{ fontSize: "0.83rem", marginBottom: 14, opacity: 0.75, lineHeight: 1.6 }}>
                    Understanding how data scoping works is critical for multi-agency deployments.
                  </p>
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
              As a solo developer you won&apos;t have real agency feeds. Use the backend&apos;s built-in
              bootstrap route to populate the platform with realistic Kenyan security scenarios and write usable predictions in one flow.
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
