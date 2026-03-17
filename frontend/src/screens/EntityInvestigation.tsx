import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  FileText,
  GitBranch,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  Sparkles,
  Wrench,
} from "lucide-react";

import {
  fetchEntityFusion,
  fetchEntityPaths,
  fetchEntityPredictions,
  fetchEntityTrustSummary,
  fetchPredictionExplanation,
  submitFeedback,
  fetchToolAttribution,
  queryAICopilot,
} from "../api/ai";
import {
  createIncidentRun,
  executeContainmentAction,
  fetchWebhookDeliveries,
  fetchWebhooks,
} from "../api/defense";
import { downloadReport, generateReport } from "../api/reports";
import type { AIPrediction, EntityTrustSummary } from "../types/ai";
import type { Principal } from "../types/auth";
import type { WebhookDeliveryRecord, WebhookRecord } from "../types/defense";
import { formatPercent } from "../utils/formatters";
import { clampRiskPercent, formatRiskScore, riskColor, riskSeverityLabel } from "../utils/risk";

type InvestigationProps = {
  initialEntityKey: string | null;
  analystId: string;
  principal: Principal;
};

type ExplanationRecord = {
  reason_codes?: string[];
  evidence_hashes?: string[];
  evidence_paths?: Array<{
    path?: string[];
    node_types?: string[];
    shared_events?: number;
    hop_count?: number;
  }>;
  recommended_controls?: string[];
  counterfactual?: {
    target_probability?: number;
    current_probability?: number;
    required_probability_shift?: number;
    recommended_direction?: string;
    top_feature_hint?: string;
  } | null;
  explanation_method?: string;
  top_feature?: string | null;
  feature_attributions?: Array<{ feature?: string; score?: number }>;
};

type ToolAttributionRecord = {
  techniques?: Array<{ technique_id: string; tactic?: string; confidence?: number }>;
  tools?: Array<{ software_id: string; name: string; type?: string; matched_techniques?: string[] }>;
  summary?: { technique_count?: number; tool_count?: number; top_tactic?: string | null };
};

type PathScoreRecord = {
  id?: string;
  entity_key?: string;
  path_score?: number;
  hop_count?: number;
  evidence_entity_keys?: string[];
};

type FusionRecord = {
  id?: string;
  entity_key?: string;
  fused_score?: number;
  severity?: string;
  decision?: string;
  signals?: { gnn_score?: number; path_score?: number; anomaly_score?: number };
};

function ScoreRing({ value, label, color }: { value: number; label: string; color: string }) {
  const size = 88;
  const radius = 30;
  const circumference = 2 * Math.PI * radius;
  const dash = (Math.max(0, Math.min(100, value)) / 100) * circumference;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={8} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={8}
          strokeDasharray={`${dash} ${circumference}`}
          strokeLinecap="round"
        />
      </svg>
      <div style={{ marginTop: -64, fontWeight: 700, fontSize: "1rem", color }}>{Math.round(value)}</div>
      <div style={{ fontSize: "0.72rem", color: "var(--ink-muted)" }}>{label}</div>
    </div>
  );
}

function extractFirstItem<T>(payload: Record<string, unknown> | null): T | null {
  if (!payload) return null;
  const rows = Array.isArray(payload.items) ? (payload.items as T[]) : [];
  return rows[0] ?? null;
}

function trustTone(status: "pass" | "warn" | "fail"): string {
  if (status === "pass") return "var(--accent)";
  if (status === "fail") return "var(--risk-critical)";
  return "var(--warning)";
}

function rawEntityTarget(entityKey: string): string {
  const idx = entityKey.indexOf(":");
  return idx >= 0 ? entityKey.slice(idx + 1) : entityKey;
}

function entityFamily(entityKey: string): string {
  const idx = entityKey.indexOf(":");
  return idx >= 0 ? entityKey.slice(0, idx) : entityKey;
}

function suggestedActionType(entityKey: string): string {
  if (entityKey.startsWith("ip:")) return "block_ip";
  if (entityKey.startsWith("host:") || entityKey.startsWith("endpoint:") || entityKey.startsWith("device_id:")) {
    return "isolate_host";
  }
  if (entityKey.startsWith("account_h:") || entityKey.startsWith("user:") || entityKey.startsWith("email:")) {
    return "revoke_user";
  }
  return "block_ip";
}

function suggestedActionTarget(entityKey: string): string {
  const family = entityFamily(entityKey);
  if (["ip", "host", "endpoint", "device_id", "account_h", "user", "email"].includes(family)) {
    return rawEntityTarget(entityKey);
  }
  return "";
}

function containmentReadinessMessage(
  entityKey: string | null,
  actionType: string,
  webhooks: WebhookRecord[],
  accessLevel: Principal["access_level"],
): string {
  if (!entityKey) return "Load one entity before planning containment.";
  const family = entityFamily(entityKey);
  if (["service_id", "provider_id", "domain", "url", "person_h", "phone_h"].includes(family)) {
    return "This entity is a correlation object, not a directly actionable host or IP. Choose the concrete IP, host, or account target you want to contain.";
  }
  if (accessLevel !== "central") {
    return "Containment can still be requested, but webhook registry visibility is restricted to central command users.";
  }
  const matching = webhooks.filter((item) => item.is_active && item.action_type === actionType);
  if (matching.length === 0) {
    return `No active ${actionType} webhook is registered right now. The action can be recorded, but no partner-side delivery will fire until a webhook is configured.`;
  }
  return `${matching.length} active ${actionType} webhook${matching.length === 1 ? "" : "s"} can currently receive this action.`;
}

export default function EntityInvestigation({ initialEntityKey, analystId, principal }: InvestigationProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState(initialEntityKey ?? "");
  const [entityKey, setEntityKey] = useState<string | null>(initialEntityKey);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [prediction, setPrediction] = useState<AIPrediction | null>(null);
  const [explanation, setExplanation] = useState<ExplanationRecord | null>(null);
  const [toolAttribution, setToolAttribution] = useState<ToolAttributionRecord | null>(null);
  const [pathScore, setPathScore] = useState<PathScoreRecord | null>(null);
  const [fusion, setFusion] = useState<FusionRecord | null>(null);
  const [reportPreview, setReportPreview] = useState<Record<string, unknown> | null>(null);
  const [trustSummary, setTrustSummary] = useState<EntityTrustSummary | null>(null);
  const [webhooks, setWebhooks] = useState<WebhookRecord[]>([]);
  const [deliveryReceipts, setDeliveryReceipts] = useState<WebhookDeliveryRecord[]>([]);
  const [feedbackNotes, setFeedbackNotes] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackStatus, setFeedbackStatus] = useState<string | null>(null);
  const [actionType, setActionType] = useState("block_ip");
  const [actionTarget, setActionTarget] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [actionStatus, setActionStatus] = useState<string | null>(null);
  const [containmentAccessNote, setContainmentAccessNote] = useState<string | null>(null);

  const [copilotQuestion, setCopilotQuestion] = useState("");
  const [copilotAnswer, setCopilotAnswer] = useState<string | null>(null);
  const [copilotLoading, setCopilotLoading] = useState(false);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!initialEntityKey) return;
    setQuery(initialEntityKey);
    if (initialEntityKey !== entityKey) {
      void investigate(initialEntityKey);
    }
  }, [initialEntityKey]);

  async function investigate(nextEntityKey: string) {
    const trimmed = nextEntityKey.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);
    setEntityKey(trimmed);
    setCopilotAnswer(null);
    setActionType(suggestedActionType(trimmed));
    setActionTarget(suggestedActionTarget(trimmed));
    setActionStatus(null);
    setFeedbackStatus(null);

    try {
      const directPredictions = await fetchEntityPredictions(trimmed, { limit: 1, predictionType: "risk_gnn", strict: true });
      const fallbackPredictions = directPredictions.length > 0
        ? directPredictions
        : await fetchEntityPredictions(trimmed, { limit: 1, predictionType: "corruption_risk", strict: true });
      const latestPrediction = fallbackPredictions[0] ?? null;
      setPrediction(latestPrediction);

      const webhookPromise =
        principal.access_level === "central"
          ? fetchWebhooks({ strict: true })
          : Promise.resolve<WebhookRecord[]>([]);
      const deliveryPromise =
        principal.access_level === "central"
          ? fetchWebhookDeliveries(50, { strict: true })
          : Promise.resolve<WebhookDeliveryRecord[]>([]);

      const [explanationPayload, toolPayload, pathPayload, fusionPayload, reportPayload, trustPayload, webhookResult, deliveryResult] = await Promise.allSettled([
        latestPrediction ? fetchPredictionExplanation(latestPrediction.id) : Promise.resolve(null),
        fetchToolAttribution(trimmed),
        fetchEntityPaths(trimmed),
        fetchEntityFusion(trimmed),
        generateReport({
          report_type: "entity_investigation",
          period: "daily",
          format: "json",
          prediction_type: latestPrediction?.prediction_type ?? "risk_gnn",
          entity_key: trimmed,
          classification: "RESTRICTED",
        }).catch(() => null),
        fetchEntityTrustSummary(trimmed, latestPrediction?.prediction_type),
        webhookPromise,
        deliveryPromise,
      ]);

      setExplanation(explanationPayload.status === "fulfilled" ? (explanationPayload.value as ExplanationRecord | null) ?? null : null);
      setToolAttribution(toolPayload.status === "fulfilled" ? (toolPayload.value as ToolAttributionRecord | null) ?? null : null);
      setPathScore(pathPayload.status === "fulfilled" ? extractFirstItem<PathScoreRecord>(pathPayload.value) : null);
      setFusion(fusionPayload.status === "fulfilled" ? extractFirstItem<FusionRecord>(fusionPayload.value) : null);
      setReportPreview(reportPayload.status === "fulfilled" ? reportPayload.value : null);
      setTrustSummary(trustPayload.status === "fulfilled" ? trustPayload.value : null);

      if (principal.access_level !== "central") {
        setContainmentAccessNote("Webhook registry and delivery receipts are visible only to central command users.");
        setWebhooks([]);
        setDeliveryReceipts([]);
      } else {
        if (webhookResult.status === "fulfilled") {
          setWebhooks(webhookResult.value);
          setContainmentAccessNote(null);
        } else {
          setWebhooks([]);
          setContainmentAccessNote(webhookResult.reason instanceof Error ? webhookResult.reason.message : "webhook_registry_unavailable");
        }
        if (deliveryResult.status === "fulfilled") {
          setDeliveryReceipts(deliveryResult.value);
        } else {
          setDeliveryReceipts([]);
          setContainmentAccessNote(deliveryResult.reason instanceof Error ? deliveryResult.reason.message : "delivery_receipts_unavailable");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "investigation_failed");
      setPrediction(null);
      setExplanation(null);
      setToolAttribution(null);
      setPathScore(null);
      setFusion(null);
      setReportPreview(null);
      setTrustSummary(null);
      setWebhooks([]);
      setDeliveryReceipts([]);
      setContainmentAccessNote(null);
    } finally {
      setLoading(false);
    }
  }

  async function recordFeedback(feedbackLabel: 0 | 1 | 2) {
    if (!prediction || !entityKey) return;
    setFeedbackBusy(true);
    setFeedbackStatus(null);
    try {
      await submitFeedback(
        prediction.id,
        feedbackLabel,
        analystId,
        feedbackNotes.trim() || undefined,
      );
      const updatedTrust = await fetchEntityTrustSummary(entityKey, prediction.prediction_type);
      setTrustSummary(updatedTrust);
      setFeedbackStatus("Analyst review saved.");
      setFeedbackNotes("");
    } catch (err) {
      setFeedbackStatus(err instanceof Error ? err.message : "feedback_submit_failed");
    } finally {
      setFeedbackBusy(false);
    }
  }

  async function triggerContainment() {
    if (!prediction || !entityKey || !actionTarget.trim()) return;
    setActionBusy(true);
    setActionStatus(null);
    try {
      const severity =
        prediction.score >= 90 ? "critical" : prediction.score >= 75 ? "high" : prediction.score >= 55 ? "medium" : "low";
      const run = await createIncidentRun(`investigation:${entityKey}`, severity, {
        entity_key: entityKey,
        prediction_id: prediction.id,
        source: "entity_investigation",
      });
      const result = await executeContainmentAction(run.id, actionType, actionTarget.trim(), {
        entity_key: entityKey,
        prediction_id: prediction.id,
      });
      const firstAction = result.actions?.[0];
      const webhookStatus =
        firstAction && firstAction.details && typeof firstAction.details.webhook_status === "string"
          ? firstAction.details.webhook_status
          : null;
      const hint =
        firstAction && firstAction.details && typeof firstAction.details.hint === "string"
          ? firstAction.details.hint
          : null;
      setActionStatus(
        `${result.status} — ${actionType} requested for ${actionTarget.trim()}.${webhookStatus ? ` Delivery state: ${webhookStatus}.` : ""}${hint ? ` ${hint}` : ""}`,
      );
      const nextTrust = await fetchEntityTrustSummary(entityKey, prediction.prediction_type);
      setTrustSummary(nextTrust);
      if (principal.access_level === "central") {
        const nextDeliveries = await fetchWebhookDeliveries(50, { strict: true });
        setDeliveryReceipts(nextDeliveries);
      }
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : "containment_action_failed");
    } finally {
      setActionBusy(false);
    }
  }

  async function askCopilot() {
    if (!copilotQuestion.trim()) return;
    setCopilotLoading(true);
    try {
      const response = await queryAICopilot(copilotQuestion, {
        entity_key: entityKey,
        prediction_score: prediction?.score,
        prediction_type: prediction?.prediction_type,
        reason_codes: explanation?.reason_codes ?? prediction?.reason_codes ?? [],
        path_score: pathScore?.path_score,
        fused_score: fusion?.fused_score,
        decision: fusion?.decision,
        tools: toolAttribution?.tools?.map((item) => item.name) ?? [],
        operator_brief: trustSummary?.operator_brief ?? null,
        linked_campaigns: trustSummary?.linked_campaigns?.map((item) => item.campaign_id) ?? [],
        data_realism: trustSummary?.operator_brief?.data_realism ?? null,
        trust_checks: trustSummary?.trust_checks?.map((item) => ({
          label: item.label,
          status: item.status,
        })) ?? [],
      });
      setCopilotAnswer(typeof response?.answer === "string" ? response.answer : "No answer returned.");
    } finally {
      setCopilotLoading(false);
    }
  }

  const summaryText = useMemo(() => {
    if (!prediction || !entityKey) return null;
    const reasons = (explanation?.reason_codes ?? prediction.reason_codes ?? []).slice(0, 3);
    const evidenceCount = explanation?.evidence_hashes?.length ?? 0;
    const toolCount = toolAttribution?.summary?.tool_count ?? toolAttribution?.tools?.length ?? 0;
    const brief = trustSummary?.operator_brief;
    const operatorDecision = brief?.operator_decision;
    const graphMeaning = brief?.graph_meaning;
    const dataRealism = brief?.data_realism;
    const containmentReadiness = brief?.containment_readiness;

    return [
      `${entityKey} is currently ${riskSeverityLabel(prediction.score).toLowerCase()} risk at ${formatRiskScore(prediction.score)} / 100.`,
      operatorDecision ?? null,
      prediction.kill_chain_stage ? `The current kill-chain stage is ${prediction.kill_chain_stage}.` : null,
      reasons.length > 0 ? `Main reasons: ${reasons.join(", ").toLowerCase().replaceAll("_", " ")}.` : null,
      graphMeaning ?? null,
      evidenceCount > 0 ? `${evidenceCount} supporting evidence record(s) are attached to the explanation.` : null,
      toolCount > 0 ? `${toolCount} likely attacker tool mapping(s) are currently attached.` : null,
      dataRealism ?? null,
      containmentReadiness ?? null,
      "Treat this as an investigative indicator, not final proof.",
    ].filter(Boolean).join(" ");
  }, [entityKey, explanation, prediction, toolAttribution, trustSummary]);

  const predictionScore = clampRiskPercent(prediction?.score);
  const pathScoreValue = clampRiskPercent(pathScore?.path_score);
  const fusedScoreValue = clampRiskPercent(fusion?.fused_score);
  const uncertaintyValue = Math.max(0, Math.min(100, (prediction?.uncertainty ?? 0) * 100));
  const reportSummary = (reportPreview?.summary as Record<string, unknown> | undefined) ?? {};
  const reportFindings = Array.isArray(reportPreview?.findings) ? (reportPreview?.findings as Array<Record<string, unknown>>) : [];
  const trustBrief = trustSummary?.operator_brief;
  const trustChecks = trustSummary?.trust_checks ?? [];
  const rawTarget = entityKey ? rawEntityTarget(entityKey) : "";
  const relatedDeliveries = useMemo(
    () =>
      deliveryReceipts.filter((item) => {
        const target = item.target.trim();
        if (!target) return false;
        return target === rawTarget || target === entityKey;
      }),
    [deliveryReceipts, entityKey, rawTarget],
  );
  const activeWebhooks = webhooks.filter((item) => item.is_active);
  const containmentGuidance = containmentReadinessMessage(entityKey, actionType, activeWebhooks, principal.access_level);

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S3</p>
          <h2>Entity Investigation</h2>
          <p className="subtle">
            One entity, one explanation flow: score, evidence, graph paths, tool attribution, and downloadable reports.
          </p>
        </div>
      </div>

      <div className="panel" style={{ background: "rgba(var(--accent-rgb), 0.08)", borderColor: "rgba(var(--accent-rgb), 0.28)" }}>
        <div className="panel-header">
          <h3>How to use this page</h3>
          <span className="muted">One entity, one decision flow</span>
        </div>
        <div className="detail-grid">
          <div>
            <p className="label">Step 1</p>
            <p>Search one real entity key, not a broad keyword.</p>
          </div>
          <div>
            <p className="label">Step 2</p>
            <p>Read the trust brief and trust checks before taking action.</p>
          </div>
          <div>
            <p className="label">Step 3</p>
            <p>Use analyst review to mark malicious, benign, or uncertain.</p>
          </div>
          <div>
            <p className="label">Step 4</p>
            <p>Use containment only after review, then confirm webhook receipts.</p>
          </div>
        </div>
        <div className="chip-row" style={{ marginTop: 14 }}>
          <span className="chip">Start: search box</span>
          <span className="chip">Review: trust brief</span>
          <span className="chip">Label: analyst review</span>
          <span className="chip">Act: containment state</span>
          <span className="chip">Export: reports</span>
        </div>
      </div>

      <div className="panel">
        <div className="topbar-search-row" style={{ width: "100%" }}>
          <div style={{ position: "relative", flex: 1 }}>
            <Search size={14} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--ink-muted)" }} />
            <input
              ref={inputRef}
              className="search"
              style={{ paddingLeft: 34 }}
              placeholder="ip:…, account_h:…, service_id:…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void investigate(query);
                }
              }}
            />
          </div>
          <button className="chip active" type="button" disabled={loading || !query.trim()} onClick={() => void investigate(query)}>
            {loading ? "Investigating…" : "Investigate"}
          </button>
        </div>
      </div>

      {!entityKey && !loading && (
        <div className="panel">
          <div className="state-box">
            <Search size={24} />
            <p>Search for a specific entity to start a guided investigation.</p>
          </div>
        </div>
      )}

      {error && (
        <div className="panel" style={{ borderColor: "rgba(255,45,85,0.35)" }}>
          <p style={{ color: "var(--risk-critical)", margin: 0 }}>{error}</p>
        </div>
      )}

      {prediction && (
        <>
          <div className="panel">
            <div className="panel-header">
              <h3>Plain-English summary</h3>
              <span className={`risk-badge ${riskSeverityLabel(prediction.score).toLowerCase()}`}>
                {riskSeverityLabel(prediction.score)}
              </span>
            </div>
            <p style={{ lineHeight: 1.7, marginBottom: 12 }}>{summaryText}</p>
            <div className="detail-grid" style={{ marginBottom: 12 }}>
              <div>
                <p className="label">Recommended posture</p>
                <p>{trustBrief?.operator_decision ?? "Review the trust brief before acting."}</p>
              </div>
              <div>
                <p className="label">Likelihood indicator</p>
                <p>{trustBrief?.likelihood_indicator ?? `${Math.round(prediction.score)}/100 cyber-risk indicator`}</p>
              </div>
              <div>
                <p className="label">Data realism</p>
                <p>{trustBrief?.data_realism ?? "No current provenance statement is attached."}</p>
              </div>
              <div>
                <p className="label">Containment readiness</p>
                <p>{trustBrief?.containment_readiness ?? containmentGuidance}</p>
              </div>
            </div>
            <div className="chip-row">
              <span className="chip">Entity: {prediction.entity_key}</span>
              <span className="chip">Prediction: {prediction.prediction_type}</span>
              <span className="chip">Model: {prediction.model_version ?? "—"}</span>
              <span className="chip">Decision source: {prediction.decision_source ?? "—"}</span>
            </div>
          </div>

          {trustBrief && (
            <div className="grid-two">
              <div className="panel">
                <div className="panel-header">
                  <h3>What the system saw</h3>
                  <span className="muted">Operator trust brief</span>
                </div>
                <div className="list">
                  <div className="list-item">
                    <strong>{trustBrief.headline}</strong>
                    <p className="muted" style={{ marginTop: 4 }}>{trustBrief.caveat}</p>
                  </div>
                  {trustBrief.what_system_saw.map((item) => (
                    <div key={item} className="list-item">
                      <p style={{ margin: 0 }}>{item}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="panel">
                <div className="panel-header">
                  <h3>What to do next</h3>
                  <span className="muted">Actionable without flooding the analyst</span>
                </div>
                <div className="list">
                  {trustBrief.next_actions.map((item) => (
                    <div key={item} className="list-item">
                      <strong>Next action</strong>
                      <p className="muted" style={{ marginTop: 4 }}>{item}</p>
                    </div>
                  ))}
                  {trustBrief.why_it_matters.map((item) => (
                    <div key={item} className="list-item">
                      <strong>Why it matters</strong>
                      <p className="muted" style={{ marginTop: 4 }}>{item}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="panel">
            <div className="panel-header">
              <h3>Decision posture</h3>
              <span className="muted">Corrected score scales from the backend</span>
            </div>
            <div className="list" style={{ marginBottom: 16 }}>
              <div className="list-item">
                <strong>How to read this</strong>
                <p className="muted" style={{ marginTop: 4 }}>
                  Risk score tells you how much attention this entity deserves. Uncertainty tells you how careful the analyst should be before escalation. Path score tells you how strongly the graph links this entity to risky neighbours and shared events.
                </p>
              </div>
            </div>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              <ScoreRing value={predictionScore} label="Risk score" color={riskColor(prediction.score)} />
              <ScoreRing value={uncertaintyValue} label="Uncertainty" color="var(--warning)" />
              <ScoreRing value={pathScoreValue} label="Path score" color="var(--accent)" />
              <ScoreRing value={fusedScoreValue} label="Fused score" color="var(--info)" />
            </div>
            <div className="detail-grid" style={{ marginTop: 20 }}>
              <div>
                <p className="label">Kill-chain stage</p>
                <p>{prediction.kill_chain_stage ?? "—"}</p>
              </div>
              <div>
                <p className="label">Confidence</p>
                <p>{prediction.confidence != null ? formatPercent(prediction.confidence, 0) : "—"}</p>
              </div>
              <div>
                <p className="label">Decision fusion</p>
                <p>{fusion?.decision ?? "Not available"}</p>
              </div>
              <div>
                <p className="label">Window end</p>
                <p className="mono">{prediction.window_end ?? "—"}</p>
              </div>
            </div>
          </div>

          {trustChecks.length > 0 && (
            <div className="panel">
              <div className="panel-header">
                <h3>Trust checks</h3>
                <span className="muted">Why an operator should or should not trust this score</span>
              </div>
              <div className="list">
                {trustChecks.map((item) => (
                  <div key={`${item.label}-${item.status}`} className="list-item">
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                      <strong>{item.label}</strong>
                      <span className="chip" style={{ color: trustTone(item.status), borderColor: `${trustTone(item.status)}55` }}>
                        {item.status.toUpperCase()}
                      </span>
                    </div>
                    <p className="muted" style={{ marginTop: 6 }}>{item.detail}</p>
                    {item.action && (
                      <p style={{ marginTop: 8, color: "var(--ink)" }}>
                        <strong>Recommended follow-up:</strong> {item.action}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid-two">
            <div className="panel">
              <div className="panel-header">
                <h3><Shield size={14} /> Analyst review</h3>
                <span className="muted">
                  {trustSummary?.feedback?.count ?? 0} prior reviews
                </span>
              </div>
              <div className="detail-grid" style={{ marginBottom: 12 }}>
                <div>
                  <p className="label">Analyst</p>
                  <p className="mono">{analystId}</p>
                </div>
                <div>
                  <p className="label">Latest feedback</p>
                  <p>
                    {trustSummary?.feedback?.latest_label != null
                      ? `${trustSummary.feedback.latest_label} · ${trustSummary.feedback.latest_status ?? "recorded"}`
                      : "No analyst review yet"}
                  </p>
                </div>
              </div>
              <textarea
                className="search"
                style={{ minHeight: 90, resize: "vertical" }}
                placeholder="Add plain-English review notes for the next training cycle or case packet."
                value={feedbackNotes}
                onChange={(event) => setFeedbackNotes(event.target.value)}
              />
              <div className="chip-row" style={{ marginTop: 12 }}>
                <button className="chip active" type="button" disabled={feedbackBusy} onClick={() => void recordFeedback(1)}>
                  Mark malicious
                </button>
                <button className="chip ghost" type="button" disabled={feedbackBusy} onClick={() => void recordFeedback(0)}>
                  Mark benign
                </button>
                <button className="chip ghost" type="button" disabled={feedbackBusy} onClick={() => void recordFeedback(2)}>
                  Mark uncertain
                </button>
              </div>
              {feedbackStatus && (
                <p className="muted" style={{ marginTop: 10 }}>{feedbackStatus}</p>
              )}
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3><ShieldAlert size={14} /> Containment and delivery state</h3>
                <span className="muted">{activeWebhooks.length} active hooks</span>
              </div>
              <div className="list" style={{ marginBottom: 12 }}>
                <div className="list-item">
                  <strong>Containment readiness</strong>
                  <p className="muted" style={{ marginTop: 4 }}>{containmentGuidance}</p>
                </div>
              </div>
              <div className="detail-grid" style={{ marginBottom: 12 }}>
                <div>
                  <p className="label">Suggested target</p>
                  <p className="mono">{actionTarget || "Choose a concrete target"}</p>
                </div>
                <div>
                  <p className="label">Recent receipts</p>
                  <p>{relatedDeliveries.length}</p>
                </div>
                <div>
                  <p className="label">Selected action hooks</p>
                  <p>{activeWebhooks.filter((item) => item.action_type === actionType).length}</p>
                </div>
                <div>
                  <p className="label">Entity family</p>
                  <p className="mono">{entityFamily(entityKey ?? "")}</p>
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr auto", gap: 10, alignItems: "end" }}>
                <div>
                  <p className="label" style={{ marginBottom: 6 }}>Action</p>
                  <select value={actionType} onChange={(event) => setActionType(event.target.value)} style={{ width: "100%" }}>
                    <option value="block_ip">block_ip</option>
                    <option value="isolate_host">isolate_host</option>
                    <option value="revoke_user">revoke_user</option>
                  </select>
                </div>
                <div>
                  <p className="label" style={{ marginBottom: 6 }}>Target</p>
                  <input
                    className="search"
                    value={actionTarget}
                    onChange={(event) => setActionTarget(event.target.value)}
                    placeholder="Containment target"
                  />
                </div>
                <button className="chip active" type="button" disabled={actionBusy || !actionTarget.trim()} onClick={() => void triggerContainment()}>
                  {actionBusy ? <RefreshCw size={13} className="spin" /> : "Execute"}
                </button>
              </div>
              {actionStatus && (
                <p className="muted" style={{ marginTop: 10 }}>{actionStatus}</p>
              )}
              {containmentAccessNote && (
                <p className="muted" style={{ marginTop: 10 }}>{containmentAccessNote}</p>
              )}
              <div className="panel-subsection">
                <h4>Webhook delivery receipts</h4>
                {relatedDeliveries.length ? (
                  <div className="list">
                    {relatedDeliveries.slice(0, 4).map((item) => (
                      <div key={item.id} className="list-item">
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                          <strong>{item.action_type}</strong>
                          <span className="chip">{item.status}</span>
                        </div>
                        <p className="muted" style={{ marginTop: 4 }}>
                          {item.target} · HTTP {item.http_status_code ?? "—"} · attempts {item.attempt_count}
                        </p>
                        {item.error_message ? <p className="muted" style={{ marginTop: 4 }}>{item.error_message}</p> : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No containment webhook deliveries are recorded yet for this entity target.</p>
                )}
              </div>
            </div>
          </div>

          <div className="grid-two">
            <div className="panel">
              <div className="panel-header">
                <h3><Sparkles size={14} /> Why it was flagged</h3>
                <span className="muted">{(explanation?.reason_codes ?? prediction.reason_codes ?? []).length} reasons</span>
              </div>
              <div className="chip-row" style={{ marginBottom: 12 }}>
                {(explanation?.reason_codes ?? prediction.reason_codes ?? []).map((reason) => (
                  <span key={reason} className="chip">{reason.replaceAll("_", " ").toLowerCase()}</span>
                ))}
              </div>
              <div className="list">
                {(explanation?.recommended_controls ?? []).length > 0 ? (
                  explanation?.recommended_controls?.map((control) => (
                    <div key={control} className="list-item">
                      <strong>Recommended control</strong>
                      <p className="muted" style={{ marginTop: 4 }}>{control}</p>
                    </div>
                  ))
                ) : (
                  <div className="list-item">
                    <strong>No recommended controls returned</strong>
                    <p className="muted" style={{ marginTop: 4 }}>
                      Use the Defense workspace for manual response execution once an incident run exists.
                    </p>
                  </div>
                )}
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3><GitBranch size={14} /> Graph and evidence</h3>
                <span className="muted">{trustSummary?.evidence_summary?.linked_campaign_count ?? 0} linked campaigns</span>
              </div>
              <div className="list" style={{ marginBottom: 12 }}>
                <div className="list-item">
                  <strong>What the graph means</strong>
                  <p className="muted" style={{ marginTop: 4 }}>
                    {trustBrief?.graph_meaning ?? "The graph score is a structural signal showing how strongly this entity is linked to risky neighbours, shared events, or campaign routes."}
                  </p>
                </div>
              </div>
              <div className="detail-grid">
                <div>
                  <p className="label">Path score</p>
                  <p>{pathScore?.path_score != null ? `${formatRiskScore(pathScore.path_score)} / 100` : "—"}</p>
                </div>
                <div>
                  <p className="label">Hop count</p>
                  <p>{pathScore?.hop_count ?? "—"}</p>
                </div>
                <div>
                  <p className="label">Evidence hashes</p>
                  <p>{trustSummary?.evidence_summary?.evidence_hash_count ?? explanation?.evidence_hashes?.length ?? 0}</p>
                </div>
                <div>
                  <p className="label">Counterfactual</p>
                  <p>{trustSummary?.evidence_summary?.counterfactual_available ? "Available" : "Missing"}</p>
                </div>
              </div>
              <div className="panel-subsection">
                <h4>Evidence paths</h4>
                {explanation?.evidence_paths?.length ? (
                  <div className="list">
                    {explanation.evidence_paths.slice(0, 4).map((item, index) => (
                      <div key={`${item.path?.join("->") ?? "path"}-${index}`} className="list-item">
                        <p className="mono" style={{ fontSize: "0.78rem" }}>{item.path?.join(" → ") ?? "Path unavailable"}</p>
                        <p className="muted" style={{ marginTop: 4 }}>
                          {item.hop_count ?? 0} hops · {item.shared_events ?? 0} shared events
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No graph paths are attached to this explanation yet.</p>
                )}
              </div>
              {trustSummary?.linked_campaigns?.length ? (
                <div className="panel-subsection">
                  <h4>Linked campaigns</h4>
                  <div className="list">
                    {trustSummary.linked_campaigns.slice(0, 4).map((item) => (
                      <div key={item.campaign_id} className="list-item">
                        <strong>{item.severity} · {formatRiskScore(item.score)} / 100</strong>
                        <p className="muted" style={{ marginTop: 4 }}>
                          {item.flagged_entity_count} flagged entities
                        </p>
                        <p className="mono" style={{ marginTop: 4, fontSize: "0.78rem" }}>{item.campaign_id}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <div className="grid-two">
            <div className="panel">
              <div className="panel-header">
                <h3><Wrench size={14} /> Tool and technique attribution</h3>
                <span className="muted">
                  {toolAttribution?.summary?.tool_count ?? toolAttribution?.tools?.length ?? 0} tools
                </span>
              </div>
              <div className="panel-subsection">
                <h4>Tools</h4>
                {toolAttribution?.tools?.length ? (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Software ID</th>
                      </tr>
                    </thead>
                    <tbody>
                      {toolAttribution.tools.slice(0, 6).map((item) => (
                        <tr key={`${item.software_id}-${item.name}`}>
                          <td>{item.name}</td>
                          <td className="muted">{item.type ?? "—"}</td>
                          <td className="mono">{item.software_id}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="muted">No tool attribution is available for this entity.</p>
                )}
              </div>
              <div className="panel-subsection">
                <h4>Techniques</h4>
                {toolAttribution?.techniques?.length ? (
                  <div className="chip-row">
                    {toolAttribution.techniques.slice(0, 8).map((item) => (
                      <span key={`${item.technique_id}-${item.tactic ?? ""}`} className="chip">
                        {item.technique_id} {item.tactic ? `· ${item.tactic}` : ""}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No ATT&CK techniques are attached yet.</p>
                )}
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3><FileText size={14} /> Downloadable reports</h3>
                <span className="muted">Readable artifacts for operators and reviewers</span>
              </div>
              <div className="list">
                <div className="list-item">
                  <strong>Entity investigation report</strong>
                  <p className="muted" style={{ marginTop: 4 }}>
                    {String(reportSummary.subject ?? entityKey ?? "Entity")} · {String(reportSummary.severity ?? riskSeverityLabel(prediction.score))}
                  </p>
                  <div className="chip-row" style={{ marginTop: 10 }}>
                    <button
                      className="chip active"
                      type="button"
                      onClick={() => void downloadReport({
                        report_type: "entity_investigation",
                        period: "daily",
                        format: "html",
                        entity_key: entityKey ?? undefined,
                        prediction_type: prediction.prediction_type,
                        classification: "RESTRICTED",
                      })}
                    >
                      Download HTML
                    </button>
                    <button
                      className="chip ghost"
                      type="button"
                      onClick={() => void downloadReport({
                        report_type: "entity_investigation",
                        period: "daily",
                        format: "json",
                        entity_key: entityKey ?? undefined,
                        prediction_type: prediction.prediction_type,
                        classification: "RESTRICTED",
                      })}
                    >
                      Download JSON
                    </button>
                    <button
                      className="chip ghost"
                      type="button"
                      onClick={() => void downloadReport({
                        report_type: "entity_investigation",
                        period: "daily",
                        format: "pdf",
                        entity_key: entityKey ?? undefined,
                        prediction_type: prediction.prediction_type,
                        classification: "RESTRICTED",
                      })}
                    >
                      Download PDF
                    </button>
                  </div>
                </div>

                <div className="list-item">
                  <strong>AI decision explanation</strong>
                  <p className="muted" style={{ marginTop: 4 }}>
                    Download the formal decision explanation tied to prediction {prediction.id.slice(0, 8)}…
                  </p>
                  <div className="chip-row" style={{ marginTop: 10 }}>
                    <button
                      className="chip active"
                      type="button"
                      onClick={() => void downloadReport({
                        report_type: "ai_decision_explanation",
                        period: "daily",
                        format: "html",
                        entity_key: entityKey ?? undefined,
                        prediction_id: prediction.id,
                        prediction_type: prediction.prediction_type,
                        classification: "RESTRICTED",
                      })}
                    >
                      Download HTML
                    </button>
                    <button
                      className="chip ghost"
                      type="button"
                      onClick={() => void downloadReport({
                        report_type: "ai_decision_explanation",
                        period: "daily",
                        format: "json",
                        entity_key: entityKey ?? undefined,
                        prediction_id: prediction.id,
                        prediction_type: prediction.prediction_type,
                        classification: "RESTRICTED",
                      })}
                    >
                      Download JSON
                    </button>
                    <button
                      className="chip ghost"
                      type="button"
                      onClick={() => void downloadReport({
                        report_type: "ai_decision_explanation",
                        period: "daily",
                        format: "pdf",
                        entity_key: entityKey ?? undefined,
                        prediction_id: prediction.id,
                        prediction_type: prediction.prediction_type,
                        classification: "RESTRICTED",
                      })}
                    >
                      Download PDF
                    </button>
                  </div>
                </div>
              </div>

              {reportFindings.length > 0 && (
                <div className="panel-subsection">
                  <h4>Official report findings</h4>
                  <div className="list">
                    {reportFindings.slice(0, 3).map((item, index) => (
                      <div key={`finding-${index}`} className="list-item">
                        <strong>{String(item.title ?? item.label ?? `Finding ${index + 1}`)}</strong>
                        <p className="muted" style={{ marginTop: 4 }}>
                          {String(item.body ?? item.summary ?? item.value ?? "No detail provided.")}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3><Bot size={14} /> Analyst assistant</h3>
              <span className="muted">Local question answering over current context</span>
            </div>
            <div className="topbar-search-row" style={{ width: "100%" }}>
              <input
                className="search"
                placeholder="Ask: why is this risky, what should be reviewed next, what evidence supports it?"
                value={copilotQuestion}
                onChange={(event) => setCopilotQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void askCopilot();
                  }
                }}
              />
              <button className="chip active" type="button" disabled={copilotLoading || !copilotQuestion.trim()} onClick={() => void askCopilot()}>
                {copilotLoading ? "Asking…" : "Ask"}
              </button>
            </div>
            <div className="chip-row" style={{ marginTop: 10 }}>
              {[
                "Explain this in plain English",
                "What does the graph score mean here?",
                "Is this low risk or urgent?",
                "What should I say in a presentation about this entity?",
                "How real is the data behind this score?",
              ].map((prompt) => (
                <button key={prompt} className="chip ghost" type="button" onClick={() => setCopilotQuestion(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
            {copilotAnswer && (
              <div className="panel-subsection">
                <div className="list-item">
                  <p style={{ lineHeight: 1.7, margin: 0, whiteSpace: "pre-wrap" }}>{copilotAnswer}</p>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {!loading && entityKey && !prediction && !error && (
        <div className="panel">
          <div className="state-box">
            <Shield size={24} />
            <p>No prediction record was found for this entity yet.</p>
            <p className="muted">The entity may not have been scored in the current windows.</p>
          </div>
        </div>
      )}
    </section>
  );
}
