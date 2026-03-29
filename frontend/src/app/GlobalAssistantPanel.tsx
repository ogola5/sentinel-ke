import { useMemo, useState } from "react";
import { Bot, Loader, Lock, ShieldCheck } from "lucide-react";

import { queryAICopilot } from "../api/ai";
import {
  apiStartMfaEnrollment,
  apiVerifyMfaEnrollment,
  LOGIN_NOTICE_KEY,
} from "../api/auth";
import type { Principal } from "../types/auth";
import type { EntityProfile } from "../types/domain";
import type { ScreenGuide, ScreenId } from "./navigation";

type Props = {
  open: boolean;
  activeScreen: ScreenId;
  screenTitle: string;
  screenGuide: ScreenGuide;
  principal: Principal;
  backendLabel: string;
  selectedEntity: EntityProfile | null;
  selectedCampaignId: string;
  selectedServiceId: string;
  selectedCaseId: string;
  eventCount: number;
  campaignCount: number;
  entityCount: number;
  graphNodes: number;
  graphEdges: number;
  healthGnnLoaded: boolean;
  healthModelVersion: string | null;
  actionStatus: string;
  onClose: () => void;
  onRequireLogin: () => void;
};

export default function GlobalAssistantPanel({
  open,
  activeScreen,
  screenTitle,
  screenGuide,
  principal,
  backendLabel,
  selectedEntity,
  selectedCampaignId,
  selectedServiceId,
  selectedCaseId,
  eventCount,
  campaignCount,
  entityCount,
  graphNodes,
  graphEdges,
  healthGnnLoaded,
  healthModelVersion,
  actionStatus,
  onClose,
  onRequireLogin,
}: Props) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [answerMeta, setAnswerMeta] = useState<{ intent?: string | null; model?: string | null; sources?: string[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [mfaStartBusy, setMfaStartBusy] = useState(false);
  const [mfaVerifyBusy, setMfaVerifyBusy] = useState(false);
  const [mfaStatus, setMfaStatus] = useState<string | null>(null);
  const [mfaOtp, setMfaOtp] = useState("");
  const [mfaEnrollment, setMfaEnrollment] = useState<{
    username: string;
    issuer: string;
    secret: string;
    provisioningUri: string;
  } | null>(null);

  const assistantContext = useMemo(
    () => ({
      current_screen: activeScreen,
      screen_title: screenTitle,
      screen_purpose: screenGuide.purpose,
      workflow_steps: screenGuide.steps,
      next_screen: screenGuide.next ?? null,
      principal_role: principal.role,
      principal_access_level: principal.access_level,
      principal_section_code: principal.section_code,
      principal_mfa_authenticated: principal.mfa_authenticated === true,
      selected_entity_key: selectedEntity?.id ?? null,
      selected_entity_label: selectedEntity?.label ?? null,
      selected_campaign_id: selectedCampaignId || null,
      selected_service_id: selectedServiceId || null,
      selected_case_id: selectedCaseId || null,
      backend_status: backendLabel,
      event_count: eventCount,
      campaign_count: campaignCount,
      entity_count: entityCount,
      graph_nodes: graphNodes,
      graph_edges: graphEdges,
      health_gnn_loaded: healthGnnLoaded,
      health_model_version: healthModelVersion,
      latest_action_status: actionStatus || null,
    }),
    [
      activeScreen,
      actionStatus,
      backendLabel,
      campaignCount,
      entityCount,
      eventCount,
      graphEdges,
      graphNodes,
      healthGnnLoaded,
      healthModelVersion,
      principal.access_level,
      principal.mfa_authenticated,
      principal.role,
      principal.section_code,
      screenGuide.next,
      screenGuide.purpose,
      screenGuide.steps,
      screenTitle,
      selectedCampaignId,
      selectedCaseId,
      selectedEntity,
      selectedServiceId,
    ],
  );

  const quickPrompts = useMemo(() => {
    const prompts = [
      "Explain the whole system end to end.",
      "How was the cyber lane trained and evaluated?",
      "What do the graph nodes and edges mean in plain English?",
      "What can I honestly claim to judges right now?",
      "What readiness evidence is strongest right now?",
      "How do legacy systems connect to Sentinel-KE?",
      `What should I say on the ${screenTitle} screen?`,
      "What should I click next to keep the workflow strong?",
      "Summarize the current workflow in plain language.",
      "How can I show MFA in action?",
      "How real is the data behind this workflow?",
    ];
    if (selectedEntity?.id) {
      prompts.unshift(`Explain ${selectedEntity.id} in plain English.`);
      prompts.push(`What does the graph score mean for ${selectedEntity.id}?`);
    }
    if (activeScreen === "gnn") {
      prompts.push("Explain the GNN on this screen in plain language.");
    }
    return Array.from(new Set(prompts)).slice(0, 8);
  }, [activeScreen, screenTitle, selectedEntity]);

  const ask = async (text: string) => {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const response = await queryAICopilot(text, assistantContext);
      if (!response || typeof response.answer !== "string") {
        setError("No local assistant answer was returned.");
        setAnswer(null);
        setAnswerMeta(null);
      } else {
        setAnswer(response.answer);
        setAnswerMeta({
          intent: typeof response.intent === "string" ? response.intent : null,
          model: typeof response.model === "string" ? response.model : null,
          sources: Array.isArray(response.sources) ? response.sources.map((item) => String(item)) : [],
        });
      }
    } catch (err) {
      setAnswer(null);
      setAnswerMeta(null);
      setError(err instanceof Error ? err.message : "assistant_request_failed");
    } finally {
      setLoading(false);
    }
  };

  const startMfa = async () => {
    setMfaStartBusy(true);
    setMfaStatus(null);
    try {
      const response = await apiStartMfaEnrollment();
      setMfaEnrollment({
        username: response.username,
        issuer: response.issuer,
        secret: response.secret,
        provisioningUri: response.provisioning_uri,
      });
      setMfaStatus("MFA enrollment started. Add the secret to your authenticator app, then verify with a 6-digit code.");
    } catch (err) {
      const detail = (err as { detail?: string })?.detail ?? String(err);
      if (detail === "mfa_already_enabled") {
        setMfaStatus("MFA is already enabled for this account. Log out and sign back in to demonstrate the MFA prompt.");
      } else {
        setMfaStatus(detail);
      }
    } finally {
      setMfaStartBusy(false);
    }
  };

  const verifyMfa = async () => {
    if (!mfaOtp.trim()) return;
    setMfaVerifyBusy(true);
    setMfaStatus(null);
    try {
      await apiVerifyMfaEnrollment(mfaOtp.trim());
      localStorage.setItem(
        LOGIN_NOTICE_KEY,
        "MFA has been enrolled for this account. Sign in again with your password, then enter the 6-digit authenticator code to continue.",
      );
      setMfaStatus("MFA enrolled successfully. You will be returned to the login screen so you can demonstrate the second-factor prompt.");
      onRequireLogin();
    } catch (err) {
      const detail = (err as { detail?: string })?.detail ?? String(err);
      setMfaStatus(detail === "invalid_mfa_code" ? "Invalid MFA code. Check the authenticator app and try again." : detail);
    } finally {
      setMfaVerifyBusy(false);
    }
  };

  if (!open) return null;

  return (
    <div className="assistant-panel">
      <div className="assistant-panel-header">
        <div>
          <p className="eyebrow">Local Copilot</p>
          <h3 style={{ margin: 0 }}>Mission Assistant</h3>
          <p className="muted" style={{ marginTop: 4 }}>
            Screen-aware guidance, presentation help, workflow suggestions, and security tools.
          </p>
        </div>
        <button className="btn-ghost" type="button" onClick={onClose}>Close</button>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3><Bot size={14} /> Ask anything about the current workflow</h3>
            <span className="muted">{screenTitle}</span>
          </div>
          <div className="detail-grid" style={{ marginBottom: 12 }}>
            <div>
              <p className="label">Current screen</p>
              <p>{screenTitle}</p>
            </div>
            <div>
              <p className="label">Best next move</p>
              <p>{screenGuide.next ?? "Stay on this screen until one action is complete."}</p>
            </div>
            <div>
              <p className="label">Selected entity</p>
              <p className="mono">{selectedEntity?.id ?? "—"}</p>
            </div>
            <div>
              <p className="label">Platform state</p>
              <p>{backendLabel}</p>
            </div>
          </div>
          <div className="topbar-search-row" style={{ width: "100%" }}>
            <input
              className="search"
              placeholder="Ask the local assistant what to say, what to click next, what the graph means, or how to present the workflow."
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void ask(question);
                }
              }}
            />
            <button className="chip active" type="button" disabled={loading || !question.trim()} onClick={() => void ask(question)}>
              {loading ? "Thinking…" : "Ask"}
            </button>
          </div>
          <div className="chip-row" style={{ marginTop: 10 }}>
            {quickPrompts.map((prompt) => (
              <button key={prompt} className="chip ghost" type="button" onClick={() => { setQuestion(prompt); void ask(prompt); }}>
                {prompt}
              </button>
            ))}
          </div>
          {error && (
            <div className="panel-subsection">
              <p className="muted" style={{ color: "var(--risk-critical)" }}>{error}</p>
            </div>
          )}
          {answer && (
            <div className="panel-subsection">
              <div className="list-item">
                <p style={{ margin: 0, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{answer}</p>
              </div>
              {answerMeta && (
                <div className="detail-grid" style={{ marginTop: 10 }}>
                  <div>
                    <p className="label">Intent</p>
                    <p>{answerMeta.intent ?? "—"}</p>
                  </div>
                  <div>
                    <p className="label">Model</p>
                    <p>{answerMeta.model ?? "—"}</p>
                  </div>
                  <div style={{ gridColumn: "1 / -1" }}>
                    <p className="label">Grounded in</p>
                    <p className="mono">{answerMeta.sources && answerMeta.sources.length > 0 ? answerMeta.sources.join(", ") : "—"}</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3><ShieldCheck size={14} /> Security tools</h3>
            <span className="muted">MFA demonstration support</span>
          </div>
          <div className="list">
            <div className="list-item">
              <strong>Current session MFA state</strong>
              <p className="muted" style={{ marginTop: 4 }}>
                {principal.mfa_authenticated
                  ? `This session already has MFA step-up authentication${principal.mfa_at ? ` from ${new Date(principal.mfa_at).toLocaleString()}` : ""}.`
                  : "This session is currently password-authenticated only."}
              </p>
            </div>
            <div className="list-item">
              <strong>How to demo MFA</strong>
              <p className="muted" style={{ marginTop: 4 }}>
                Start enrollment, add the secret to an authenticator app, verify one code, then sign in again. The login screen will then require the 6-digit code after password entry.
              </p>
            </div>
          </div>

          <div className="chip-row" style={{ marginTop: 12 }}>
            <button className="chip active" type="button" disabled={mfaStartBusy || mfaVerifyBusy} onClick={() => void startMfa()}>
              {mfaStartBusy ? <Loader size={13} className="spin" /> : <Lock size={13} />}
              &nbsp;Start MFA Enrollment
            </button>
            <button className="chip ghost" type="button" onClick={() => void ask("How can I show MFA in action?")}>
              Ask assistant
            </button>
          </div>

          {mfaEnrollment && (
            <div className="panel-subsection">
              <div className="detail-grid">
                <div>
                  <p className="label">Username</p>
                  <p className="mono">{mfaEnrollment.username}</p>
                </div>
                <div>
                  <p className="label">Issuer</p>
                  <p>{mfaEnrollment.issuer}</p>
                </div>
              </div>
              <div style={{ marginTop: 10 }}>
                <p className="label">Authenticator secret</p>
                <p className="mono" style={{ wordBreak: "break-all" }}>{mfaEnrollment.secret}</p>
              </div>
              <details className="collapsible-panel" style={{ marginTop: 10 }}>
                <summary>
                  Provisioning URI
                  <span className="muted">Use if your authenticator supports otpauth links</span>
                </summary>
                <p className="mono" style={{ wordBreak: "break-all" }}>{mfaEnrollment.provisioningUri}</p>
              </details>
              <div className="topbar-search-row" style={{ width: "100%", marginTop: 12 }}>
                <input
                  className="search mono"
                  placeholder="Enter 6-digit MFA code"
                  value={mfaOtp}
                  onChange={(event) => setMfaOtp(event.target.value.replace(/\D/g, "").slice(0, 6))}
                />
                <button className="chip active" type="button" disabled={mfaVerifyBusy || mfaOtp.trim().length < 6} onClick={() => void verifyMfa()}>
                  {mfaVerifyBusy ? "Verifying…" : "Verify MFA"}
                </button>
              </div>
            </div>
          )}

          {mfaStatus && (
            <div className="panel-subsection">
              <p className="muted" style={{ margin: 0 }}>{mfaStatus}</p>
            </div>
          )}
        </div>
      </div>

      <div className="assistant-context-row">
        <span className="chip">Events: {eventCount}</span>
        <span className="chip">Campaigns: {campaignCount}</span>
        <span className="chip">Entities: {entityCount}</span>
        <span className="chip">Graph: {graphNodes} nodes / {graphEdges} edges</span>
        <span className="chip">GNN loaded: {healthGnnLoaded ? "yes" : "no"}</span>
        <span className="chip">Model: {healthModelVersion ?? "—"}</span>
      </div>
    </div>
  );
}
