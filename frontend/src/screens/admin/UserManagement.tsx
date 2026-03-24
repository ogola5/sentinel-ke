import { useEffect, useState } from "react";
import { Users, RefreshCw, Loader, UserPlus, CheckCircle, XCircle, Shield, AlertTriangle, Eye, EyeOff } from "lucide-react";
import { apiListUsers, apiCreateUser, apiAdminResetPassword } from "../../api/auth";
import { KENYA_AGENCIES, agencyName } from "../../types/auth";
import type { AuthUser } from "../../types/auth";

function roleBadgeClass(role: string): string {
  if (role === "admin")    return "critical";
  if (role === "operator") return "high";
  if (role === "analyst")  return "info";
  return "low";
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-KE", { day: "numeric", month: "short", year: "numeric" });
}

const AGENCY_CODES = ["", ...Object.keys(KENYA_AGENCIES)];
const ROLES = ["analyst", "operator", "admin", "auditor"];

export default function UserManagement() {
  const [users, setUsers]         = useState<AuthUser[]>([]);
  const [loading, setLoading]     = useState(true);
  const [filterSection, setFilterSection] = useState("");
  const [filterRole, setFilterRole]       = useState("");
  const [selected, setSelected]           = useState<AuthUser | null>(null);

  // Create user form
  const [showCreate, setShowCreate] = useState(false);
  const [newUsername, setNewUsername]     = useState("");
  const [newDisplay, setNewDisplay]       = useState("");
  const [newPassword, setNewPassword]     = useState("");
  const [newRole, setNewRole]             = useState("analyst");
  const [newAccess, setNewAccess]         = useState<"section" | "central">("section");
  const [newSection, setNewSection]       = useState("");
  const [creating, setCreating]           = useState(false);
  const [createError, setCreateError]     = useState("");
  const [createSuccess, setCreateSuccess] = useState("");
  const [showPwd, setShowPwd]             = useState(false);

  // Reset password
  const [resetTarget, setResetTarget] = useState<AuthUser | null>(null);
  const [resetPwd, setResetPwd]       = useState("");
  const [resetting, setResetting]     = useState(false);
  const [resetMsg, setResetMsg]       = useState("");

  const load = async () => {
    setLoading(true);
    const result = await apiListUsers().catch(() => ({ items: [] as AuthUser[], total: 0 }));
    setUsers(result.items);
    setLoading(false);
  };

  useEffect(() => { void load(); }, []);

  const filtered = users.filter((u) => {
    if (filterSection && u.section_code !== filterSection) return false;
    if (filterRole && u.role !== filterRole) return false;
    return true;
  });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUsername.trim() || !newPassword.trim()) return;
    if (newAccess === "section" && !newSection) {
      setCreateError("Select an agency for section-level access.");
      return;
    }
    setCreating(true);
    setCreateError("");
    setCreateSuccess("");
    try {
      await apiCreateUser({
        username: newUsername.trim(),
        display_name: newDisplay.trim() || undefined,
        password: newPassword,
        role: newRole,
        access_level: newAccess,
        section_code: newAccess === "section" ? newSection : undefined,
      });
      setCreateSuccess(`User "${newUsername.trim()}" created successfully.`);
      setNewUsername(""); setNewDisplay(""); setNewPassword(""); setNewSection(""); setNewRole("analyst"); setNewAccess("section");
      await load();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail ?? String(err);
      setCreateError(detail === "username_conflict" ? "That username already exists." : detail);
    } finally {
      setCreating(false);
    }
  };

  const handleReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetTarget || resetPwd.length < 12) return;
    setResetting(true);
    setResetMsg("");
    try {
      await apiAdminResetPassword(resetTarget.username, resetPwd);
      setResetMsg(`Password reset for ${resetTarget.username}. All sessions revoked.`);
      setResetPwd("");
    } catch (err: unknown) {
      setResetMsg(`Failed: ${(err as { detail?: string })?.detail ?? "unknown_error"}`);
    } finally {
      setResetting(false);
    }
  };

  const activeCount  = users.filter((u) => u.is_active).length;
  const mfaCount     = users.filter((u) => u.mfa_enabled).length;
  const lockedCount  = users.filter((u) => u.locked_until).length;

  return (
    <div>
      <div className="screen-header">
        <div>
          <p className="eyebrow">S16</p>
          <h2 style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Users size={20} color="var(--info)" />
            User Management
          </h2>
          <p className="subtle">Create users, filter accounts, and review access quickly.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
            {loading ? <Loader size={13} /> : <RefreshCw size={13} />} &nbsp;Refresh
          </button>
          <button className="btn-accent" onClick={() => { setShowCreate((p) => !p); setCreateError(""); setCreateSuccess(""); }}>
            <UserPlus size={13} /> &nbsp;{showCreate ? "Cancel" : "New User"}
          </button>
        </div>
      </div>

      {/* Metrics */}
      <div className="metric-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
        <div className="metric-card"><div className="metric-label">Total users</div><div className="metric-value">{users.length}</div><div className="metric-sub">All accounts</div></div>
        <div className="metric-card accent"><div className="metric-label">Active</div><div className="metric-value">{activeCount}</div><div className="metric-sub">Enabled accounts</div></div>
        <div className="metric-card info"><div className="metric-label">MFA enrolled</div><div className="metric-value">{mfaCount}</div><div className="metric-sub">2FA active</div></div>
        <div className={`metric-card ${lockedCount > 0 ? "danger" : ""}`}><div className="metric-label">Locked</div><div className="metric-value">{lockedCount}</div><div className="metric-sub">Failed login lockout</div></div>
      </div>

      {/* Create user panel */}
      {showCreate && (
        <div className="panel" style={{ marginBottom: 16, borderColor: "rgba(49,255,144,.3)" }}>
          <div className="panel-header">
            <h3><UserPlus size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />Create user</h3>
            <span className="muted">Username, role, and access scope</span>
          </div>
          <form onSubmit={(e) => void handleCreate(e)}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
              <div>
                <p className="label" style={{ marginBottom: 4 }}>Username *</p>
                <input value={newUsername} onChange={(e) => setNewUsername(e.target.value)} placeholder="e.g. kps_analyst_02" style={{ width: "100%" }} />
              </div>
              <div>
                <p className="label" style={{ marginBottom: 4 }}>Display name</p>
                <input value={newDisplay} onChange={(e) => setNewDisplay(e.target.value)} placeholder="Full name (optional)" style={{ width: "100%" }} />
              </div>
              <div>
                <p className="label" style={{ marginBottom: 4 }}>Password * (min 12 chars)</p>
                <div style={{ position: "relative" }}>
                  <input
                    type={showPwd ? "text" : "password"}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="••••••••••••"
                    style={{ width: "100%", paddingRight: 40 }}
                  />
                  <button type="button" className="pwd-toggle" onClick={() => setShowPwd((p) => !p)} tabIndex={-1}>
                    {showPwd ? <EyeOff size={13} /> : <Eye size={13} />}
                  </button>
                </div>
              </div>
              <div>
                <p className="label" style={{ marginBottom: 4 }}>Role</p>
                <select value={newRole} onChange={(e) => setNewRole(e.target.value)} style={{ width: "100%" }}>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <div>
                <p className="label" style={{ marginBottom: 4 }}>Access level</p>
                <select value={newAccess} onChange={(e) => setNewAccess(e.target.value as "section" | "central")} style={{ width: "100%" }}>
                  <option value="section">Section (agency-scoped)</option>
                  <option value="central">Central (cross-agency)</option>
                </select>
              </div>
              {newAccess === "section" && (
                <div>
                  <p className="label" style={{ marginBottom: 4 }}>Agency *</p>
                  <select value={newSection} onChange={(e) => setNewSection(e.target.value)} style={{ width: "100%" }}>
                    <option value="">— Select agency —</option>
                    {AGENCY_CODES.slice(1).map((c) => (
                      <option key={c} value={c}>{c} — {KENYA_AGENCIES[c]?.name}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            {createError && (
              <div className="login-error" style={{ marginBottom: 10 }}>
                <AlertTriangle size={13} /><span>{createError}</span>
              </div>
            )}
            {createSuccess && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--accent)", marginBottom: 10, fontSize: "0.85rem" }}>
                <CheckCircle size={14} />{createSuccess}
              </div>
            )}
            <button type="submit" className="btn-accent" disabled={creating || !newUsername.trim() || newPassword.length < 12}>
              {creating ? <Loader size={13} /> : <UserPlus size={13} />} &nbsp;Create User
            </button>
          </form>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: selected ? "1fr 320px" : "1fr", gap: 16 }}>
        {/* User list */}
        <div className="panel">
          {/* Filters */}
          <div style={{ display: "flex", gap: 10, marginBottom: 12, alignItems: "flex-end" }}>
            <div>
              <p className="label" style={{ marginBottom: 4 }}>Agency</p>
              <select value={filterSection} onChange={(e) => setFilterSection(e.target.value)}>
                <option value="">All agencies</option>
                {AGENCY_CODES.slice(1).map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <p className="label" style={{ marginBottom: 4 }}>Role</p>
              <select value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
                <option value="">All roles</option>
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <span className="muted" style={{ fontSize: "0.8rem", marginBottom: 4 }}>
              {filtered.length} of {users.length} users
            </span>
          </div>

          {loading ? (
            <div className="state-box"><Loader size={22} /><p>Loading users…</p></div>
          ) : filtered.length === 0 ? (
            <div className="state-box"><Users size={28} /><p>No users found.</p></div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Display name</th>
                    <th>Agency</th>
                    <th>Role</th>
                    <th>Access</th>
                    <th>MFA</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((u) => (
                    <tr
                      key={u.user_id}
                      style={{ cursor: "pointer", background: selected?.user_id === u.user_id ? "rgba(49,255,144,.06)" : undefined }}
                      onClick={() => setSelected(u.user_id === selected?.user_id ? null : u)}
                    >
                      <td><span className="mono" style={{ fontSize: "0.8rem" }}>{u.username}</span></td>
                      <td className="muted" style={{ fontSize: "0.8rem" }}>{u.display_name ?? "—"}</td>
                      <td>
                        <span className="risk-badge info" style={{ fontSize: "0.65rem" }}>
                          {u.section_code ?? "CENTRAL"}
                        </span>
                      </td>
                      <td><span className={`risk-badge ${roleBadgeClass(u.role)}`}>{u.role}</span></td>
                      <td>
                        <span
                          className="risk-badge"
                          style={{
                            background: u.access_level === "central" ? "rgba(49,255,144,.12)" : "rgba(79,195,247,.12)",
                            color: u.access_level === "central" ? "var(--accent)" : "var(--info)",
                            border: `1px solid ${u.access_level === "central" ? "rgba(49,255,144,.3)" : "rgba(79,195,247,.3)"}`,
                          }}
                        >
                          {u.access_level}
                        </span>
                      </td>
                      <td>
                        {u.mfa_enabled
                          ? <CheckCircle size={14} color="var(--accent)" />
                          : <XCircle size={14} color="var(--ink-muted)" />}
                      </td>
                      <td>
                        {u.locked_until ? (
                          <span className="risk-badge critical">Locked</span>
                        ) : u.is_active ? (
                          <span className="risk-badge low">Active</span>
                        ) : (
                          <span className="risk-badge medium">Inactive</span>
                        )}
                      </td>
                      <td className="muted" style={{ fontSize: "0.76rem" }}>{fmtDate(u.created_at)}</td>
                      <td>
                        <button
                          className="btn-ghost"
                          style={{ padding: "2px 8px", fontSize: "0.72rem" }}
                          onClick={(e) => { e.stopPropagation(); setResetTarget(u); setResetMsg(""); setResetPwd(""); }}
                        >
                          <Shield size={11} />
                        </button>
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
              <h3>User detail</h3>
              <button className="btn-ghost" style={{ padding: "2px 8px" }} onClick={() => setSelected(null)}>×</button>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: "0.82rem" }}>
              <DetailRow label="Username"     value={selected.username} mono />
              <DetailRow label="Agency"       value={agencyName(selected.section_code)} />
              <DetailRow label="Role"         value={selected.role} />
              <DetailRow label="Access level" value={selected.access_level} />
              <DetailRow label="MFA"          value={selected.mfa_enabled ? "Enrolled" : "Not enrolled"} />
              <DetailRow label="Status" value={selected.locked_until ? "Locked" : selected.is_active ? "Active" : "Inactive"} />
              {selected.display_name && <DetailRow label="Display name" value={selected.display_name} />}
              <details className="panel panel-details">
                <summary>
                  <span>Identifiers and scopes</span>
                  <span className="muted">Audit fields and permissions</span>
                </summary>
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
                  <DetailRow label="User ID" value={selected.user_id} mono small />
                  <DetailRow label="Failed logins" value={selected.failed_login_count.toString()} />
                  <DetailRow label="Locked until" value={selected.locked_until ?? "Not locked"} />
                  <DetailRow label="Created" value={fmtDate(selected.created_at)} />
                  <DetailRow label="Updated" value={fmtDate(selected.updated_at)} />
                  {selected.scopes.length > 0 && (
                    <div>
                      <p className="label" style={{ marginBottom: 4 }}>Scopes</p>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {selected.scopes.map((s) => (
                          <span key={s} className="risk-badge info" style={{ fontSize: "0.62rem" }}>{s}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </details>
              <button
                className="btn-ghost"
                style={{ marginTop: 6, fontSize: "0.78rem" }}
                onClick={() => { setResetTarget(selected); setResetMsg(""); setResetPwd(""); }}
              >
                <Shield size={12} /> &nbsp;Reset Password
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Password reset modal */}
      {resetTarget && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <h3>
              <AlertTriangle size={15} color="var(--warning)" style={{ marginRight: 8, verticalAlign: "middle" }} />
              Reset Password — {resetTarget.username}
            </h3>
            <div className="modal-body">
              <p style={{ marginBottom: 12, fontSize: "0.85rem" }}>
                Agency: <strong>{agencyName(resetTarget.section_code)}</strong><br />
                Role: <strong>{resetTarget.role}</strong><br />
                All active sessions will be revoked.
              </p>
              <form onSubmit={(e) => void handleReset(e)}>
                <p className="label" style={{ marginBottom: 6 }}>New password (min 12 chars)</p>
                <input
                  type="password"
                  value={resetPwd}
                  onChange={(e) => setResetPwd(e.target.value)}
                  placeholder="••••••••••••"
                  style={{ width: "100%", marginBottom: 12 }}
                  autoFocus
                />
                {resetMsg && (
                  <div
                    style={{
                      color: resetMsg.startsWith("Failed") ? "var(--danger)" : "var(--accent)",
                      fontSize: "0.82rem",
                      marginBottom: 8,
                    }}
                  >
                    {resetMsg}
                  </div>
                )}
                <div className="modal-actions">
                  <button type="button" className="btn-ghost" onClick={() => { setResetTarget(null); setResetPwd(""); }}>
                    Cancel
                  </button>
                  <button type="submit" className="btn-danger" disabled={resetting || resetPwd.length < 12}>
                    {resetting ? <Loader size={13} /> : <Shield size={13} />}
                    &nbsp;Reset & Revoke Sessions
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DetailRow({ label, value, mono, small }: { label: string; value: string; mono?: boolean; small?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
      <span className="muted">{label}</span>
      <span style={{ fontFamily: mono ? "JetBrains Mono, monospace" : undefined, fontSize: small ? "0.72rem" : "0.82rem", textAlign: "right", wordBreak: "break-all" }}>
        {value}
      </span>
    </div>
  );
}
