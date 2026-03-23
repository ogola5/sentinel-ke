import { useState } from "react";
import {
  Shield, Eye, EyeOff, Loader, AlertTriangle,
  Lock, ChevronDown, ChevronUp, Terminal, Info,
  ArrowRight, FileLock2, KeyRound, Mail, Network, Radar, ShieldCheck,
  Sparkles, Workflow,
} from "lucide-react";
import { apiLogin, saveSession } from "../../api/auth";
import { LOGIN_NOTICE_KEY } from "../../api/auth";
import { KENYA_AGENCIES } from "../../types/auth";
import type { Principal } from "../../types/auth";

interface Props {
  onLogin: (principal: Principal) => void;
}

// Quick-fill presets for solo dev testing
const DEV_PRESETS = [
  { label: "Admin",   username: "admin",      hint: "Bootstrap admin — full central access" },
  { label: "KPS",     username: "kps_test",   hint: "Kenya Police Service analyst" },
  { label: "DCI",     username: "dci_test",   hint: "Directorate of Criminal Investigations" },
  { label: "EACC",    username: "eacc_test",  hint: "Ethics & Anti-Corruption Commission" },
  { label: "KRA",     username: "kra_test",   hint: "Kenya Revenue Authority" },
  { label: "ODPP",    username: "odpp_test",  hint: "Office of Director of Public Prosecutions" },
  { label: "CBK",     username: "cbk_test",   hint: "Central Bank of Kenya" },
  { label: "NIS",     username: "nis_test",   hint: "National Intelligence Service" },
  { label: "OAG",     username: "oag_test",   hint: "Office of the Auditor General" },
];

const showDevLoginAids =
  String(import.meta.env.VITE_ENABLE_DEV_LOGIN_AIDS ?? "").trim().toLowerCase() === "true";

export default function LoginScreen({ onLogin }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otpCode, setOtpCode]   = useState("");
  const [showOtp, setShowOtp]   = useState(false);
  const [showPwd, setShowPwd]   = useState(false);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState("");
  const [step, setStep]         = useState<"credentials" | "mfa">("credentials");
  const [guideOpen, setGuideOpen] = useState(false);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [requestName, setRequestName] = useState("");
  const [requestEmail, setRequestEmail] = useState("");
  const [requestAgency, setRequestAgency] = useState("KPS");
  const [requestRole, setRequestRole] = useState("analyst");
  const [requestAccessLevel, setRequestAccessLevel] = useState<"section" | "central">("section");
  const [requestPurpose, setRequestPurpose] = useState("");
  const [requestStatus, setRequestStatus] = useState("");
  const [loginNotice, setLoginNotice] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem(LOGIN_NOTICE_KEY) ?? "";
  });

  const agencyCodes = Object.keys(KENYA_AGENCIES);
  const accessDeskEmail = String(import.meta.env.VITE_ACCESS_REQUEST_EMAIL ?? "access@sentinel-ke.local").trim();

  const guessAgency = () => {
    const u = username.toLowerCase();
    for (const code of agencyCodes) {
      if (u.includes(code.toLowerCase())) return code;
    }
    return null;
  };

  const agency = guessAgency();
  const agencyLabel = agency ? KENYA_AGENCIES[agency]?.name : null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;
    setLoading(true);
    setError("");
    try {
      const session = await apiLogin(
        username.trim(),
        password,
        step === "mfa" ? otpCode.trim() : undefined,
      );
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(LOGIN_NOTICE_KEY);
      }
      saveSession(session);
      onLogin(session.principal);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail ?? String(err);
      if (detail === "mfa_code_required") {
        setStep("mfa");
        setError("Enter your 6-digit authenticator code.");
      } else if (detail === "invalid_mfa_code") {
        setError("Invalid MFA code. Try again.");
      } else if (detail === "account_locked") {
        setError("Account is locked. Contact your administrator.");
      } else if (detail === "invalid_credentials") {
        setError("Invalid username or password.");
      } else {
        setError(detail || "Login failed. Check your connection and try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  const applyPreset = (p: typeof DEV_PRESETS[0]) => {
    setUsername(p.username);
    setActivePreset(p.username);
    setError("");
  };

  const buildAccessRequest = () => {
    const agencyName = KENYA_AGENCIES[requestAgency]?.name ?? requestAgency;
    return [
      "Sentinel-KE access request",
      "",
      `Name: ${requestName.trim() || "<full name>"}`,
      `Work email: ${requestEmail.trim() || "<work email>"}`,
      `Agency: ${agencyName}`,
      `Requested role: ${requestRole}`,
      `Access level: ${requestAccessLevel}`,
      `Operational purpose: ${requestPurpose.trim() || "<mission need>"}`,
      "",
      "Expected controls:",
      "- Central provisioning only",
      "- TOTP MFA on activation",
      "- RBAC by role and section/central scope",
      "- Session tokens revoked on password reset / MFA state change",
    ].join("\n");
  };

  const handleRequestAccess = (event: React.FormEvent) => {
    event.preventDefault();
    if (!requestName.trim() || !requestEmail.trim()) {
      setRequestStatus("Provide your full name and official work email to prepare the request.");
      return;
    }
    const subject = encodeURIComponent(`Sentinel-KE access request · ${requestAgency} · ${requestRole}`);
    const body = encodeURIComponent(buildAccessRequest());
    if (typeof window !== "undefined") {
      window.location.href = `mailto:${accessDeskEmail}?subject=${subject}&body=${body}`;
    }
    setRequestStatus(`Draft opened for ${accessDeskEmail}. Accounts are provisioned centrally and MFA is completed during activation.`);
  };

  const handleCopyRequest = async () => {
    try {
      await navigator.clipboard.writeText(buildAccessRequest());
      setRequestStatus(`Request copied. Send it to ${accessDeskEmail} for controlled account provisioning.`);
    } catch {
      setRequestStatus("Clipboard access failed. Use the email button to open a ready-made access request.");
    }
  };

  return (
    <div className="login-root">
      <div className="ke-bar">
        <div style={{ flex: 1, background: "#006600" }} />
        <div style={{ flex: 1, background: "#BB0000" }} />
        <div style={{ flex: 1, background: "#000000" }} />
        <div style={{ flex: 1, background: "#FFFFFF" }} />
      </div>

      <div className="landing-shell">
        <section className="landing-hero">
          <div className="landing-topline">
            <Sparkles size={14} />
            <span>Sovereign cyber, fraud, and integrity intelligence for Kenya</span>
          </div>

          <div className="login-brand">
            <div className="login-brand-icon landing-brand-icon">
              <Shield size={36} color="var(--accent)" />
            </div>
            <div>
              <div className="login-brand-title">SENTINEL-KE</div>
              <div className="login-brand-sub">
                National Cyber &amp; Economic Intelligence Platform
              </div>
            </div>
          </div>

          <div className="landing-hero-copy">
            <h1 className="landing-title">
              Explainable graph intelligence for national cyber defense, fraud detection, and public-sector resilience.
            </h1>
            <p className="landing-lede">
              Sentinel-KE brings together multi-source events, graph-based GNN scoring, privacy-preserving federation,
              governed containment, and exportable evidence into one operational workflow. It is built for officers who
              need to answer five questions fast: what is happening, why it matters, how sure we are, what to do next,
              and what evidence supports that decision.
            </p>
          </div>

          <div className="landing-cta-row">
            <a className="landing-btn primary" href="#secure-access">
              Enter secure workspace <ArrowRight size={15} />
            </a>
            <a className="landing-btn secondary" href="#access-request">
              Request controlled access
            </a>
          </div>
          <div className="landing-stat-grid">
            <article className="landing-stat-card accent">
              <div className="landing-stat-label">Explainable GNN</div>
              <div className="landing-stat-value">Graph-based risk</div>
              <p>Entity scoring with confidence, uncertainty, path risk, and human-readable trust cues.</p>
            </article>
            <article className="landing-stat-card info">
              <div className="landing-stat-label">Federated by design</div>
              <div className="landing-stat-value">Cross-agency coordination</div>
              <p>Partners can correlate high-risk entities without dumping raw identifiers into a central pool.</p>
            </article>
            <article className="landing-stat-card success">
              <div className="landing-stat-label">Governed response</div>
              <div className="landing-stat-value">Action with controls</div>
              <p>Containment, evidence bundles, STIX export, audit trails, and access controls in one loop.</p>
            </article>
          </div>

          <div className="landing-section-grid">
            <article className="landing-story-card">
              <div className="landing-story-icon"><Radar size={18} /></div>
              <div>
                <h3>1. Ingest and normalize</h3>
                <p>Security telemetry, public threat intelligence, and sector signals are normalized into one canonical event model.</p>
              </div>
            </article>
            <article className="landing-story-card">
              <div className="landing-story-icon"><Network size={18} /></div>
              <div>
                <h3>2. Build relationship context</h3>
                <p>The platform turns those signals into graph features so risk is understood in context, not as isolated alerts.</p>
              </div>
            </article>
            <article className="landing-story-card">
              <div className="landing-story-icon"><Workflow size={18} /></div>
              <div>
                <h3>3. Guide action and reporting</h3>
                <p>Analysts move from entity explanation to campaign, case, report, and governed containment without leaving the workflow.</p>
              </div>
            </article>
          </div>

          <div className="landing-security-grid">
            <article className="landing-security-card">
              <div className="landing-security-head"><KeyRound size={16} /><span>MFA and identity assurance</span></div>
              <p>Secure sign-in supports username/password plus authenticator codes, with sensitive operations gated behind stronger trust checks.</p>
            </article>
            <article className="landing-security-card">
              <div className="landing-security-head"><FileLock2 size={16} /><span>RBAC and scoped visibility</span></div>
              <p>Central and section users see different screens, actions, and reports, reducing overexposure of sensitive workflows.</p>
            </article>
            <article className="landing-security-card">
              <div className="landing-security-head"><ShieldCheck size={16} /><span>Session and audit control</span></div>
              <p>Access/refresh sessions, revocation on password or MFA changes, and audit-backed actions support accountable operations.</p>
            </article>
          </div>

          <div className="agency-register landing-agencies">
            <p className="label" style={{ marginBottom: 10 }}>
              Example participating agencies
            </p>
            <div className="agency-chips agency-chips-left">
              {agencyCodes.map((code) => (
                <span key={code} className="agency-chip" title={KENYA_AGENCIES[code].name}>
                  {code}
                </span>
              ))}
              <span className="agency-chip central" title="Central Command">CENTRAL</span>
            </div>
          </div>
        </section>

        <aside className="landing-auth-column" id="secure-access">
          <div className="classification-ribbon">
            OFFICIAL · GOVERNMENT CLASSIFIED · AUTHORISED USERS ONLY
          </div>

          {agencyLabel && (
            <div className="agency-hint">
              <span className="status-dot live" />
              &nbsp;{agencyLabel}
            </div>
          )}

          {loginNotice && (
            <div className="agency-hint" style={{ borderColor: "rgba(var(--accent-rgb), 0.35)", background: "rgba(var(--accent-rgb), 0.08)" }}>
              <Info size={13} />
              <span style={{ marginLeft: 8 }}>{loginNotice}</span>
              <button
                type="button"
                className="btn-ghost"
                style={{ marginLeft: "auto", padding: "2px 8px" }}
                onClick={() => {
                  setLoginNotice("");
                  if (typeof window !== "undefined") {
                    window.localStorage.removeItem(LOGIN_NOTICE_KEY);
                  }
                }}
              >
                ×
              </button>
            </div>
          )}

          <div className="login-card">
            <div className="login-card-header">
              <Lock size={14} color="var(--ink-muted)" />
              <span>{step === "mfa" ? "Two-Factor Authentication" : "Secure Sign-In"}</span>
            </div>

            <form onSubmit={(e) => void handleSubmit(e)} autoComplete="off" spellCheck={false}>
              {step === "credentials" ? (
                <>
                  <div className="login-field">
                    <label className="label">Username</label>
                    <input
                      className="login-input"
                      type="text"
                      value={username}
                      onChange={(e) => { setUsername(e.target.value); setActivePreset(null); }}
                      placeholder="Enter your assigned username"
                      autoFocus
                      disabled={loading}
                    />
                  </div>
                  <div className="login-field">
                    <label className="label">Password</label>
                    <div style={{ position: "relative" }}>
                      <input
                        className="login-input"
                        type={showPwd ? "text" : "password"}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="••••••••••••"
                        disabled={loading}
                        style={{ paddingRight: 40 }}
                      />
                      <button type="button" className="pwd-toggle" onClick={() => setShowPwd((p) => !p)} tabIndex={-1}>
                        {showPwd ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <div className="login-field">
                  <label className="label">Authenticator Code</label>
                  <div style={{ position: "relative" }}>
                    <input
                      className="login-input mono"
                      type={showOtp ? "text" : "password"}
                      value={otpCode}
                      onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                      placeholder="000000"
                      maxLength={6}
                      autoFocus
                      disabled={loading}
                      style={{ letterSpacing: "0.3em", paddingRight: 40 }}
                    />
                    <button type="button" className="pwd-toggle" onClick={() => setShowOtp((p) => !p)} tabIndex={-1}>
                      {showOtp ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                  <p className="muted" style={{ fontSize: "0.75rem", marginTop: 6 }}>
                    Open your authenticator app and enter the 6-digit code.
                  </p>
                </div>
              )}

              {error && (
                <div className="login-error">
                  <AlertTriangle size={13} />
                  <span>{error}</span>
                </div>
              )}

              <button type="submit" className="login-btn" disabled={loading || !username.trim() || !password.trim()}>
                {loading
                  ? <><Loader size={14} className="spin" /> &nbsp;Authenticating…</>
                  : step === "mfa" ? "Verify & Continue" : "Sign In"
                }
              </button>

              {step === "mfa" && (
                <button type="button" className="btn-ghost" style={{ width: "100%", marginTop: 8, fontSize: "0.8rem" }}
                  onClick={() => { setStep("credentials"); setOtpCode(""); setError(""); }}>
                  ← Back to credentials
                </button>
              )}
            </form>
          </div>

          <div className="login-card request-card" id="access-request">
            <div className="login-card-header">
              <Mail size={14} color="var(--ink-muted)" />
              <span>Request Controlled Access</span>
            </div>

            <form onSubmit={handleRequestAccess} className="request-form">
              <div className="request-grid">
                <div className="login-field">
                  <label className="label">Full name</label>
                  <input
                    className="login-input"
                    type="text"
                    value={requestName}
                    onChange={(event) => setRequestName(event.target.value)}
                    placeholder="Official full name"
                  />
                </div>
                <div className="login-field">
                  <label className="label">Work email</label>
                  <input
                    className="login-input"
                    type="email"
                    value={requestEmail}
                    onChange={(event) => setRequestEmail(event.target.value)}
                    placeholder="name@agency.go.ke"
                  />
                </div>
                <div className="login-field">
                  <label className="label">Agency</label>
                  <select value={requestAgency} onChange={(event) => setRequestAgency(event.target.value)}>
                    {agencyCodes.map((code) => (
                      <option key={code} value={code}>{code} · {KENYA_AGENCIES[code].name}</option>
                    ))}
                  </select>
                </div>
                <div className="login-field">
                  <label className="label">Requested role</label>
                  <select value={requestRole} onChange={(event) => setRequestRole(event.target.value)}>
                    <option value="analyst">Analyst</option>
                    <option value="operator">Operator</option>
                    <option value="auditor">Auditor</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <div className="login-field">
                  <label className="label">Access scope</label>
                  <select
                    value={requestAccessLevel}
                    onChange={(event) => setRequestAccessLevel(event.target.value as "section" | "central")}
                  >
                    <option value="section">Section / agency scope</option>
                    <option value="central">Central command scope</option>
                  </select>
                </div>
                <div className="login-field request-grid-span">
                  <label className="label">Operational purpose</label>
                  <textarea
                    className="login-input request-textarea"
                    value={requestPurpose}
                    onChange={(event) => setRequestPurpose(event.target.value)}
                    placeholder="Why access is required, what systems will be onboarded, and which operational workflow you need."
                  />
                </div>
              </div>

              {requestStatus && (
                <div className="landing-note">
                  <Info size={13} />
                  <span>{requestStatus}</span>
                </div>
              )}

              <div className="request-actions">
                <button type="submit" className="login-btn">
                  Email access request
                </button>
                <button type="button" className="btn-ghost" onClick={() => void handleCopyRequest()}>
                  Copy request text
                </button>
              </div>
            </form>
          </div>

          <div className="landing-access-model">
            <div className="landing-access-head">
              <ShieldCheck size={16} />
              <span>Security model in force</span>
            </div>
            <ul className="landing-access-list">
              <li>Accounts are created by a central administrator. There is no public self-registration.</li>
              <li>TOTP MFA is supported and can be demonstrated after enrollment from the authenticated workspace.</li>
              <li>Role-based access separates central, section, admin, analyst, operator, and auditor capabilities.</li>
              <li>Session continuity uses access and refresh tokens, with revocation on resets and MFA state changes.</li>
            </ul>
          </div>

          {showDevLoginAids && (
            <>
              <div className="setup-guide-toggle" onClick={() => setGuideOpen((p) => !p)}>
                <Terminal size={13} />
                <span>First time? Developer setup guide</span>
                {guideOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              </div>

              {guideOpen && (
                <div className="setup-guide-panel">
                  <div className="setup-step">
                    <div className="setup-step-num">1</div>
                    <div>
                      <p className="setup-step-title">Log in as Bootstrap Admin</p>
                      <p className="setup-step-body">
                        Your backend auto-created an admin account on first start.
                        Find the credentials in your <span className="mono-inline">render-backend.env</span> or <span className="mono-inline">.env</span> file:
                      </p>
                      <div className="env-box">
                        <span className="env-key">AUTH_BOOTSTRAP_ADMIN_USERNAME</span>=<span className="env-val">admin</span><br />
                        <span className="env-key">AUTH_BOOTSTRAP_ADMIN_PASSWORD</span>=<span className="env-val">{"<your value>"}</span>
                      </div>
                      <button type="button" className="login-btn-outline" style={{ marginTop: 8 }}
                        onClick={() => applyPreset({ label: "Admin", username: "admin", hint: "" })}>
                        Fill username → admin
                      </button>
                    </div>
                  </div>

                  <div className="setup-step">
                    <div className="setup-step-num">2</div>
                    <div>
                      <p className="setup-step-title">Create Agency Test Accounts</p>
                      <p className="setup-step-body">
                        After logging in as admin, go to <strong>COMMAND → Agency Onboarding</strong>.
                        Click <strong>"Create All Test Accounts"</strong> to auto-generate one account per agency.
                        Their credentials will be displayed so you can test each login.
                      </p>
                    </div>
                  </div>

                  <div className="setup-step">
                    <div className="setup-step-num">3</div>
                    <div>
                      <p className="setup-step-title">Test Agency Logins</p>
                      <p className="setup-step-body">
                        Click any agency below to pre-fill the username, then enter the password you set in Step 2:
                      </p>
                      <div className="preset-grid">
                        {DEV_PRESETS.slice(1).map((p) => (
                          <button
                            key={p.username}
                            type="button"
                            className={`preset-btn ${activePreset === p.username ? "active" : ""}`}
                            onClick={() => applyPreset(p)}
                            title={p.hint}
                          >
                            {p.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="setup-step">
                    <div className="setup-step-num">4</div>
                    <div>
                      <p className="setup-step-title">How Agencies Connect Their Systems</p>
                      <p className="setup-step-body">
                        Real agencies send data to Sentinel-KE via the Ingest API:
                      </p>
                      <div className="env-box">
                        POST /v1/ingest/event<br />
                        X-API-Key: <span className="env-val">{"<INGEST_API_KEY>"}</span><br />
                        {"{"} "section_code": "KPS", "event_type": "...", ... {"}"}
                      </div>
                      <p className="setup-step-body" style={{ marginTop: 8 }}>
                        For federation (privacy-preserving cross-agency matching):
                      </p>
                      <div className="env-box">
                        POST /v1/federation/register<br />
                        {"{"} "partner_id": "KPS", "partner_name": "Kenya Police Service",<br />
                        &nbsp; "sector": "gov", "webhook_url": "https://kps-soc.go.ke/webhook" {"}"}
                      </div>
                      <p className="setup-step-body" style={{ marginTop: 8 }}>
                        Go to <strong>COMMAND → Agency Onboarding</strong> for the full connection guide per agency.
                      </p>
                    </div>
                  </div>

                  <div className="setup-info-box">
                    <Info size={13} style={{ flexShrink: 0, marginTop: 1 }} />
                    <span>
                      Accounts are created by a central admin — there is no public self-registration.
                      This keeps the platform access-controlled to authorised government personnel only.
                    </span>
                  </div>
                </div>
              )}
            </>
          )}

          <div className="agency-register">
            <p className="label" style={{ textAlign: "center", marginBottom: 10 }}>
              Participating agencies
            </p>
            <div className="agency-chips">
              {agencyCodes.map((code) => (
                <span
                  key={code}
                  className={`agency-chip ${activePreset?.startsWith(code.toLowerCase()) ? "active-chip" : ""}`}
                  title={KENYA_AGENCIES[code].name}
                  onClick={showDevLoginAids ? () => applyPreset({ label: code, username: `${code.toLowerCase()}_test`, hint: KENYA_AGENCIES[code].name }) : undefined}
                  style={{ cursor: showDevLoginAids ? "pointer" : "default" }}
                >
                  {code}
                </span>
              ))}
              <span className="agency-chip central" title="Central Command"
                onClick={showDevLoginAids ? () => applyPreset({ label: "Admin", username: "admin", hint: "Central admin" }) : undefined}
                style={{ cursor: showDevLoginAids ? "pointer" : "default" }}>
                CENTRAL
              </span>
            </div>
            <p className="muted" style={{ textAlign: "center", fontSize: "0.68rem", marginTop: 8 }}>
              {showDevLoginAids ? "Click an agency to pre-fill the username" : "Access is provisioned centrally for authorised personnel only"}
            </p>
          </div>

          <p className="login-footer">
            Sentinel-KE is a restricted government system. Unauthorised access is a criminal
            offence under the Kenya Computer Misuse &amp; Cybercrimes Act, 2018.
          </p>
        </aside>
      </div>
    </div>
  );
}
