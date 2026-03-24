import { useState } from "react";
import {
  Shield, Eye, EyeOff, Loader, AlertTriangle,
  Lock, ChevronDown, ChevronUp, Terminal, Info,
  ArrowRight, FileLock2, KeyRound, Mail, Network, Radar, ShieldCheck,
  Sparkles, Workflow, X, Globe2, Users2,
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
  const [authPanelOpen, setAuthPanelOpen] = useState(false);
  const [requestName, setRequestName] = useState("");
  const [requestEmail, setRequestEmail] = useState("");
  const [requestAgency, setRequestAgency] = useState("KPS");
  const [requestRole, setRequestRole] = useState("analyst");
  const [requestAccessLevel, setRequestAccessLevel] = useState<"section" | "central">("section");
  const [requestPurpose, setRequestPurpose] = useState("");
  const [requestStatus, setRequestStatus] = useState("");
  const [activeOverview, setActiveOverview] = useState<"cyber" | "fraud" | "federation" | "trust">("cyber");
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
  const overviewModes = {
    cyber: {
      title: "Cyber operations",
      summary: "Graph-native detection for DDoS, hostile infrastructure reuse, login abuse, and campaign escalation.",
      bullets: ["Entity scoring with confidence and uncertainty", "GNN + path risk + anomaly fusion", "Cases, reports, and governed containment"],
      icon: <Radar size={18} />,
    },
    fraud: {
      title: "Fraud and financial risk",
      summary: "Track SIM swap chains, mule movement, mobile-money abuse, and high-risk transaction narratives in one loop.",
      bullets: ["Scenario simulation and short-horizon forecasting", "Analyst feedback improves future training", "Shared workflow across cyber and fraud teams"],
      icon: <Workflow size={18} />,
    },
    federation: {
      title: "Federated intelligence",
      summary: "Agencies correlate high-risk patterns without moving raw identifiers into a central public pool.",
      bullets: ["Partner freshness and status visibility", "Privacy-preserving matching path", "Cross-agency campaign awareness"],
      icon: <Network size={18} />,
    },
    trust: {
      title: "Operational trust",
      summary: "The platform exposes controls up front: MFA, RBAC, auditability, provenance, and explainability.",
      bullets: ["Controlled provisioning only", "Scoped visibility by role and agency", "Evidence export and review-ready reporting"],
      icon: <ShieldCheck size={18} />,
    },
  } as const;

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
      <div className="ke-bar" aria-hidden="true">
        <span className="ke-bar-segment black" />
        <span className="ke-bar-segment white" />
        <span className="ke-bar-segment red" />
        <span className="ke-bar-segment white" />
        <span className="ke-bar-segment green" />
      </div>

      <div className="landing-shell">
        <nav className="landing-nav">
          <div className="login-brand">
            <div className="login-brand-icon landing-brand-icon">
              <Shield size={34} color="var(--accent)" />
            </div>
            <div>
              <div className="login-brand-title">SENTINEL-KE</div>
              <div className="login-brand-sub">
                Sovereign national intelligence for cyber defense, fraud detection, and public-sector resilience
              </div>
            </div>
          </div>

          <div className="landing-nav-links">
            <a href="#capabilities">Capabilities</a>
            <a href="#security">Security</a>
            <a href="#access-request">Access</a>
            <button type="button" className="landing-btn landing-nav-btn" onClick={() => setAuthPanelOpen(true)}>
              Secure login
            </button>
          </div>
        </nav>

        <section className="landing-hero">
          <div className="landing-topline">
            <Sparkles size={14} />
            <span>Sovereign AI for Kenyan operations</span>
          </div>

          <div className="landing-hero-layout">
            <div className="landing-hero-copy">
              <h1 className="landing-title">
                AI-guided cyber and fraud operations, built for Kenya.
              </h1>
              <p className="landing-lede">
                Sentinel-KE turns fragmented events into one operational loop: detect, explain, coordinate, and act.
                It is designed for sovereign security teams that need trust, speed, and clear evidence.
              </p>

              <div className="landing-cta-row">
                <button type="button" className="landing-btn primary" onClick={() => setAuthPanelOpen(true)}>
                  Enter secure workspace <ArrowRight size={15} />
                </button>
                <a className="landing-btn secondary" href="#access-request">
                  Request controlled access
                </a>
              </div>

              <div className="landing-highlight-row">
                <div className="landing-highlight-chip">GNN intelligence</div>
                <div className="landing-highlight-chip">Fraud and cyber</div>
                <div className="landing-highlight-chip">MFA and RBAC</div>
              </div>
            </div>

            <div className="landing-visual-panel" aria-hidden="true">
              <div className="landing-radar-stage">
                <div className="landing-radar-ring ring-one" />
                <div className="landing-radar-ring ring-two" />
                <div className="landing-radar-ring ring-three" />
                <div className="landing-radar-sweep" />
                <div className="landing-radar-node node-one" />
                <div className="landing-radar-node node-two" />
                <div className="landing-radar-node node-three" />
                <div className="landing-radar-node node-four" />
                <div className="landing-radar-core">
                  <Shield size={24} />
                </div>
              </div>

              <div className="landing-visual-stack">
                <article className="landing-visual-card accent">
                  <span className="landing-visual-label">Live posture</span>
                  <strong>Explainable graph scoring</strong>
                  <p>Risk, confidence, uncertainty, and path context in one analyst view.</p>
                </article>
                <article className="landing-visual-card danger">
                  <span className="landing-visual-label">Threat flow</span>
                  <strong>Detect → explain → act</strong>
                  <p>Campaigns, reports, and governed response without breaking chain-of-trust.</p>
                </article>
              </div>
            </div>
          </div>
        </section>

        <section className="landing-section-block" id="capabilities">
          <div className="landing-section-heading compact">
            <span className="landing-section-kicker">Overview</span>
            <h2>Explore the platform by mission lens</h2>
            <p>Start with the brief. Open only the part you need.</p>
          </div>

          <div className="landing-mode-tabs" role="tablist" aria-label="Platform overview">
            {(Object.entries(overviewModes) as Array<[keyof typeof overviewModes, (typeof overviewModes)[keyof typeof overviewModes]]>).map(([key, item]) => (
              <button
                key={key}
                type="button"
                className={`landing-mode-tab ${activeOverview === key ? "active" : ""}`}
                onClick={() => setActiveOverview(key)}
              >
                {item.icon}
                <span>{item.title}</span>
              </button>
            ))}
          </div>

          <div className="landing-mode-panel">
            <div className="landing-mode-panel-icon">
              {overviewModes[activeOverview].icon}
            </div>
            <div className="landing-mode-panel-copy">
              <h3>{overviewModes[activeOverview].title}</h3>
              <p>{overviewModes[activeOverview].summary}</p>
              <div className="landing-mode-bullets">
                {overviewModes[activeOverview].bullets.map((bullet) => (
                  <span key={bullet} className="landing-mode-bullet">{bullet}</span>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="landing-section-block" id="security">
          <div className="landing-section-heading compact">
            <span className="landing-section-kicker">Trust Layer</span>
            <h2>Controls that matter before the first click</h2>
          </div>

          <div className="landing-security-grid compact">
            <article className="landing-security-card">
              <div className="landing-security-head"><KeyRound size={16} /><span>MFA and identity assurance</span></div>
              <p>Controlled login, MFA, and stronger trust checks for sensitive actions.</p>
            </article>
            <article className="landing-security-card">
              <div className="landing-security-head"><FileLock2 size={16} /><span>RBAC and scoped visibility</span></div>
              <p>Central and section users see only the screens and actions they should.</p>
            </article>
            <article className="landing-security-card">
              <div className="landing-security-head"><ShieldCheck size={16} /><span>Session and audit control</span></div>
              <p>Session continuity, revocation, and auditable decisions built into the workflow.</p>
            </article>
          </div>

          <div className="landing-pillars">
            <div className="landing-pillar"><Globe2 size={15} /><span>Sovereign local-first deployment model</span></div>
            <div className="landing-pillar"><Users2 size={15} /><span>Central and agency-scoped operating modes</span></div>
            <div className="landing-pillar"><ShieldCheck size={15} /><span>Governed containment and evidence export</span></div>
          </div>
        </section>

        <section className="landing-access-grid" id="access-request">
          <div className="login-card request-card">
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
              <span>How access is provisioned</span>
            </div>
            <ul className="landing-access-list">
              <li>Accounts are created by a central administrator. There is no public self-registration.</li>
              <li>TOTP MFA can be demonstrated after enrollment from the secure workspace.</li>
              <li>RBAC separates central, section, admin, analyst, operator, and auditor capabilities.</li>
              <li>Sessions use access and refresh tokens with revocation on resets and MFA state changes.</li>
            </ul>

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

            <div className="landing-cta-row" style={{ marginTop: 16 }}>
              <button type="button" className="landing-btn primary" onClick={() => setAuthPanelOpen(true)}>
                Open secure login <ArrowRight size={15} />
              </button>
            </div>
          </div>
        </section>
      </div>

      {authPanelOpen && (
        <div className="landing-auth-backdrop" onClick={() => !loading && setAuthPanelOpen(false)}>
          <aside className="landing-auth-modal" id="secure-access" onClick={(event) => event.stopPropagation()}>
            <div className="landing-auth-modal-head">
              <div className="classification-ribbon">
                OFFICIAL · GOVERNMENT CLASSIFIED · AUTHORISED USERS ONLY
              </div>
              <button
                type="button"
                className="landing-close-btn"
                onClick={() => !loading && setAuthPanelOpen(false)}
                aria-label="Close secure sign-in"
              >
                <X size={16} />
              </button>
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
      )}
    </div>
  );
}
