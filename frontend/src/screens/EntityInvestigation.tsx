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

import ArchitectureFlow from "../app/ArchitectureFlow";
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
import { fetchGraphNeighbours } from "../api/graph";
import type { GraphNeighboursResponse } from "../api/graph";
import {
  createIncidentRun,
  DEFAULT_DEFENSE_ACTIONS,
  executeContainmentAction,
  fetchDefenseActionCatalog,
  fetchWebhookDeliveries,
  fetchWebhooks,
} from "../api/defense";
import { downloadReport, generateReport } from "../api/reports";
import type { AIPrediction, EntityTrustSummary } from "../types/ai";
import type { Principal } from "../types/auth";
import type { DefenseActionDefinition, WebhookDeliveryRecord, WebhookRecord } from "../types/defense";
import { clampRiskPercent, formatRiskScore, riskSeverityLabel } from "../utils/risk";

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
  if (entityKey.startsWith("service_id:") || entityKey.startsWith("url:") || entityKey.startsWith("domain:")) {
    return "enable_waf_challenge";
  }
  if (entityKey.startsWith("host:") || entityKey.startsWith("endpoint:") || entityKey.startsWith("device_id:")) {
    return "isolate_host";
  }
  if (entityKey.startsWith("phone_h:")) return "suspend_sim_change";
  if (entityKey.startsWith("agent_id:")) return "hold_cashout";
  if (entityKey.startsWith("account_h:")) return "freeze_account";
  if (entityKey.startsWith("user:") || entityKey.startsWith("email:")) {
    return entityKey.startsWith("email:") ? "quarantine_email" : "revoke_user";
  }
  return "block_ip";
}

function suggestedActionTarget(entityKey: string): string {
  const family = entityFamily(entityKey);
  if (["ip", "host", "endpoint", "device_id", "phone_h", "agent_id", "account_h", "user", "email", "service_id", "url", "domain"].includes(family)) {
    return rawEntityTarget(entityKey);
  }
  return "";
}

function preferredParentEntityKey(entityKey: string | null): string | null {
  if (!entityKey) return null;
  if (entityKey.startsWith("endpoint:")) {
    const raw = entityKey.slice("endpoint:".length);
    const splitIndex = raw.indexOf(":");
    if (splitIndex > 0) {
      return `service_id:${raw.slice(0, splitIndex)}`;
    }
  }
  return null;
}

function suggestedContainmentSection(entityKey: string | null, principal: Principal): string | undefined {
  const principalSection = principal.access_level === "section" ? principal.section_code?.trim() : "";
  if (principalSection) return principalSection;
  if (!entityKey) return undefined;
  const family = entityFamily(entityKey);
  if (family === "service_id" || family === "provider_id") {
    const target = rawEntityTarget(entityKey).trim();
    return target || undefined;
  }
  return undefined;
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
    return `No active ${actionType} control endpoint is registered right now. The action can still be recorded, but partner-side delivery remains pending until a webhook is configured.`;
  }
  return `${matching.length} active ${actionType} webhook${matching.length === 1 ? "" : "s"} can currently receive this action.`;
}

const REASON_CODE_EXPLANATIONS: Record<string, string> = {
  ABOVE_ENTITY_THRESHOLD: "This entity crossed the calibrated alert threshold for its type in the current scoring window.",
  CAMPAIGN_LINKED: "The graph links this entity to an active campaign or risky cluster rather than a one-off event.",
  EVENT_VOLUME_HIGH: "The score is supported by repeated observations or dense telemetry, not a single isolated hit.",
  GNN_RISK_ELEVATED: "The GNN found elevated risk in the surrounding graph neighborhood and linked entity structure.",
  RISK_INDICATOR_ONLY_NOT_FINAL_PROOF: "This is an investigative signal for analyst prioritisation, not standalone proof.",
  VPN_INFRA_REUSE: "The entity overlaps with VPN or masking-infrastructure reuse patterns seen elsewhere in the graph.",
  THREAT_INTEL_HIT: "Threat-intelligence or IOC evidence currently references this entity.",
  MALWARE_INDICATOR: "The entity matches malware-associated telemetry or curated indicator evidence.",
  HIGH_FRACTION_FLAGGED: "A large share of linked nodes in this graph component were also flagged as risky.",
  HAS_CRITICAL_ENTITY_SIGNAL: "A critical signal exists within the same connected graph component.",
  DISCOVERED_FROM_GRAPH_COMPONENT: "The entity was surfaced through graph expansion from another risky node.",
  SIM_SWAP_FRAUD_CHAIN: "This entity is part of a SIM-swap-to-fraud progression rather than a single isolated event.",
  ACCOUNT_TAKEOVER_SIGNAL: "The observed pattern is consistent with account-takeover pressure.",
  PHISHING_ATO_CHAIN: "The graph links phishing activity to likely downstream account takeover.",
  CREDENTIAL_HARVEST_THEN_FRAUD: "The telemetry suggests credential collection followed by fraud progression.",
  RECON_BEFORE_DDOS: "The entity appears in reconnaissance activity that preceded service-pressure signals.",
  STAGED_ATTACK_PROGRESSION: "The sequence looks staged across multiple phases rather than accidental overlap.",
  VULN_EXPLOIT_DATA_ACCESS: "The signal suggests vulnerability exploitation with downstream data-access risk.",
  POST_EXPLOITATION_SIGNAL: "The entity appears in post-compromise activity rather than initial probing only.",
  CREDENTIAL_STUFFING_PRECEDES_SIM_SWAP: "The signal chain suggests login pressure before SIM-swap activity.",
  WAF_BYPASS_RISK: "Traffic patterns suggest attempts to get around existing WAF controls.",
  WAF_UNDER_PRESSURE: "The service is under enough web-attack pressure to justify containment review.",
  WEB_ATTACK_VOLUME_HIGH: "The service is seeing sustained hostile web activity rather than a routine background scan.",
  BEC_SIGNAL_SURGE: "Business-email-compromise indicators rose sharply in the current window.",
};

function formatTimestamp(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-KE", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function humanizeCode(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
    .replace(/\bGnn\b/g, "GNN")
    .replace(/\bAi\b/g, "AI")
    .replace(/\bIoc\b/g, "IOC")
    .replace(/\bDns\b/g, "DNS")
    .replace(/\bDdos\b/g, "DDoS")
    .replace(/\bVpn\b/g, "VPN")
    .replace(/\bAto\b/g, "ATO");
}

function reasonCodeDetail(code: string): string {
  return REASON_CODE_EXPLANATIONS[code] ?? `${humanizeCode(code)} contributed to the current risk assessment.`;
}

function decisionSourceLabel(source?: string | null): string {
  if (source === "gnn") return "GNN inference";
  if (source === "heuristic") return "Heuristic fallback";
  if (source === "blocked") return "Inference blocked by governance guard";
  return source ? humanizeCode(source) : "Unknown inference source";
}

function killChainLabel(stage?: string | null): string {
  if (!stage) return "Unspecified";
  return humanizeCode(stage);
}

function confidenceDescriptor(value?: number | null): string {
  const confidence = Number(value ?? 0);
  if (confidence >= 0.9) return "High-confidence inference";
  if (confidence >= 0.75) return "Solid confidence";
  if (confidence >= 0.55) return "Moderate confidence";
  return "Low-confidence inference";
}

function uncertaintyDescriptor(value?: number | null): string {
  const uncertainty = Number(value ?? 0);
  if (uncertainty <= 0.15) return "Low uncertainty";
  if (uncertainty <= 0.35) return "Moderate uncertainty";
  return "High uncertainty";
}

function investigationProfile(entityKey: string | null, predictionType?: string | null): {
  title: string;
  noun: string;
  subtitle: string;
} {
  if (predictionType === "corruption_risk") {
    return {
      title: "Integrity Risk Analysis",
      noun: "integrity risk",
      subtitle: "Read procurement, payment, and graph-linked review pressure before escalation.",
    };
  }
  const family = entityKey ? entityFamily(entityKey) : "";
  if (["account_h", "phone_h", "agent_id", "person_h"].includes(family)) {
    return {
      title: "Fraud-Chain Analysis",
      noun: "fraud-chain risk",
      subtitle: "Read transaction progression, linked accounts, and control readiness before intervention.",
    };
  }
  return {
    title: "Cyber Threat Analysis",
    noun: "cyber risk",
    subtitle: "Read telemetry, graph evidence, ATT&CK context, and bounded control readiness together.",
  };
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
  const [liveGraph, setLiveGraph] = useState<GraphNeighboursResponse | null>(null);
  const [reportPreview, setReportPreview] = useState<Record<string, unknown> | null>(null);
  const [trustSummary, setTrustSummary] = useState<EntityTrustSummary | null>(null);
  const [webhooks, setWebhooks] = useState<WebhookRecord[]>([]);
  const [deliveryReceipts, setDeliveryReceipts] = useState<WebhookDeliveryRecord[]>([]);
  const [actionCatalog, setActionCatalog] = useState<DefenseActionDefinition[]>(DEFAULT_DEFENSE_ACTIONS);
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
  const containmentSectionCode = useMemo(
    () => suggestedContainmentSection(entityKey, principal),
    [entityKey, principal],
  );
  const analysisProfile = useMemo(
    () => investigationProfile(entityKey, prediction?.prediction_type),
    [entityKey, prediction?.prediction_type],
  );

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    void fetchDefenseActionCatalog().then(setActionCatalog).catch(() => setActionCatalog(DEFAULT_DEFENSE_ACTIONS));
  }, []);

  useEffect(() => {
    if (!initialEntityKey) return;
    setQuery(initialEntityKey);
    if (initialEntityKey !== entityKey) {
      void investigate(initialEntityKey);
    }
  }, [initialEntityKey]);

  useEffect(() => {
    if (actionCatalog.some((item) => item.key === actionType)) return;
    setActionType(actionCatalog[0]?.key ?? "block_ip");
  }, [actionCatalog, actionType]);

  async function investigate(nextEntityKey: string) {
    const trimmed = nextEntityKey.trim();
    if (!trimmed) return;
    const nextContainmentSectionCode = suggestedContainmentSection(trimmed, principal);

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
          ? fetchWebhooks({ sectionCode: nextContainmentSectionCode, strict: true })
          : Promise.resolve<WebhookRecord[]>([]);
      const deliveryPromise =
        principal.access_level === "central"
          ? fetchWebhookDeliveries(50, { sectionCode: nextContainmentSectionCode, strict: true })
          : Promise.resolve<WebhookDeliveryRecord[]>([]);

      const [explanationPayload, toolPayload, pathPayload, fusionPayload, liveGraphPayload, reportPayload, trustPayload, webhookResult, deliveryResult] = await Promise.allSettled([
        latestPrediction ? fetchPredictionExplanation(latestPrediction.id) : Promise.resolve(null),
        fetchToolAttribution(trimmed),
        fetchEntityPaths(trimmed),
        fetchEntityFusion(trimmed),
        fetchGraphNeighbours(trimmed),
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
      setLiveGraph(liveGraphPayload.status === "fulfilled" ? liveGraphPayload.value : null);
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
      setLiveGraph(null);
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
      }, containmentSectionCode);
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
      const detailError =
        firstAction && firstAction.details && typeof firstAction.details.error === "string"
          ? firstAction.details.error
          : null;
      setActionStatus(
        `${result.status} — ${actionType} requested for ${actionTarget.trim()}.${webhookStatus ? ` Delivery state: ${webhookStatus}.` : ""}${detailError ? ` ${detailError}.` : ""}${hint ? ` ${hint}` : ""}`,
      );
      const nextTrust = await fetchEntityTrustSummary(entityKey, prediction.prediction_type);
      setTrustSummary(nextTrust);
      if (principal.access_level === "central") {
        const nextDeliveries = await fetchWebhookDeliveries(50, { sectionCode: containmentSectionCode, strict: true });
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
    const techniqueCount = toolAttribution?.techniques?.length ?? 0;
    const brief = trustSummary?.operator_brief;
    const operatorDecision = brief?.operator_decision;
    const graphMeaning = brief?.graph_meaning;
    const dataRealism = brief?.data_realism;
    const containmentReadiness = brief?.containment_readiness;

    return [
      brief?.headline ?? `${entityKey} is currently assessed as ${riskSeverityLabel(prediction.score).toLowerCase()} ${analysisProfile.noun} at ${formatRiskScore(prediction.score)} / 100.`,
      operatorDecision ?? null,
      prediction.kill_chain_stage ? `Kill-chain stage: ${killChainLabel(prediction.kill_chain_stage)}.` : null,
      reasons.length > 0 ? `Model drivers: ${reasons.map(humanizeCode).join(", ")}.` : null,
      graphMeaning ?? null,
      evidenceCount > 0 ? `${evidenceCount} supporting evidence hash(es) and ${explanation?.evidence_paths?.length ?? 0} graph path(s) are attached to the explanation.` : null,
      toolCount > 0 || techniqueCount > 0 ? `${toolCount} inferred tool mapping(s) and ${techniqueCount} ATT&CK technique hit(s) are attached.` : null,
      dataRealism ?? null,
      containmentReadiness ?? null,
      "This score is an investigative signal for analyst prioritisation. Formal escalation still requires corroborating evidence and operator judgement.",
    ].filter(Boolean).join(" ");
  }, [analysisProfile.noun, entityKey, explanation, prediction, toolAttribution, trustSummary]);

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
  const actionHookCount = activeWebhooks.filter((item) => item.action_type === actionType).length;
  const selectedAction = actionCatalog.find((item) => item.key === actionType) ?? actionCatalog[0] ?? DEFAULT_DEFENSE_ACTIONS[0];
  const primaryReasons = (explanation?.reason_codes ?? prediction?.reason_codes ?? []).slice(0, 4);
  const reasonInsights = primaryReasons.map((code) => ({
    code,
    label: humanizeCode(code),
    detail: reasonCodeDetail(code),
  }));
  const recommendedControls = explanation?.recommended_controls ?? [];
  const leadingNextActions = trustBrief?.next_actions.slice(0, 2) ?? [];
  const leadingWhyItMatters = trustBrief?.why_it_matters.slice(0, 2) ?? [];
  const parentEntityKey = preferredParentEntityKey(entityKey);
  const techniqueCount = trustSummary?.evidence_summary?.technique_count ?? toolAttribution?.techniques?.length ?? 0;
  const toolCount = trustSummary?.evidence_summary?.tool_count ?? toolAttribution?.tools?.length ?? 0;
  const topTechnique = toolAttribution?.summary?.top_tactic ? humanizeCode(toolAttribution.summary.top_tactic) : null;
  const confidenceSummary = confidenceDescriptor(prediction?.confidence);
  const uncertaintySummary = uncertaintyDescriptor(prediction?.uncertainty);
  const governance = trustSummary?.governance;
  const provenance = governance?.provenance ?? {};
  const realRatio = typeof provenance.real_ratio === "number" ? provenance.real_ratio : null;
  const avgRealSignalRatio = typeof provenance.avg_real_signal_ratio === "number" ? provenance.avg_real_signal_ratio : null;
  const analysisSources = [
    {
      title: "Prediction record",
      detail: `${decisionSourceLabel(prediction?.decision_source)} from model ${prediction?.model_version ?? "—"} in window ${formatTimestamp(prediction?.window_end ?? prediction?.created_at)}.`,
    },
    {
      title: "Explanation artifact",
      detail: explanation
        ? `${(explanation.reason_codes ?? []).length} reason code(s), ${explanation.evidence_hashes?.length ?? 0} evidence hash(es), method ${humanizeCode(explanation.explanation_method ?? "model_explanation")}.`
        : "No explanation artifact is attached yet; the screen is currently relying on the raw prediction record.",
    },
    {
      title: "Graph context",
      detail: pathScore
        ? `Path score ${formatRiskScore(pathScore.path_score)} / 100 across ${pathScore.hop_count ?? 0} hop(s), with ${liveGraph?.neighbours?.length ?? 0} live neighbour(s) visible.`
        : `${liveGraph?.neighbours?.length ?? 0} live neighbour(s) are visible, but the scored graph-path artifact is not attached yet.`,
    },
    {
      title: "Campaign and tradecraft",
      detail: `${trustSummary?.linked_campaigns?.length ?? 0} linked campaign(s), ${techniqueCount} ATT&CK technique hit(s), and ${toolCount} inferred tool mapping(s) currently enrich this entity.`,
    },
    {
      title: "Governance state",
      detail: `Real-data gate ${governance?.real_data_gate_passed ? "passed" : "warning"}, fairness ${String(governance?.fairness_status ?? "unknown")}, drift ${String(governance?.drift_status ?? "unknown")}.`,
    },
  ];

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S3</p>
          <h2>{analysisProfile.title}</h2>
          <p className="subtle">
            {analysisProfile.subtitle}
          </p>
        </div>
      </div>

      <ArchitectureFlow
        label="Analytic flow"
        title="How one entity moves from model output to operator action"
        summary="Use this page to explain the signal, inspect graph and telemetry evidence, then record judgement or route a bounded control."
        steps={[
          { stage: "Entity", title: "Choose one scored key", detail: "Search a concrete IP, service, account, domain, or procurement node that the platform can actually score.", tone: "info" },
          { stage: "Analysis", title: "Read model and graph context", detail: "Review reason codes, graph evidence, tradecraft, and governance posture together.", tone: "accent" },
          { stage: "Judgement", title: "Record analyst adjudication", detail: "Mark malicious, benign, or uncertain before external escalation.", tone: "warning" },
          { stage: "Response", title: "Route bounded control", detail: "Record or execute containment, then verify delivery state and report output.", tone: "danger" },
        ]}
      />

      <div className="panel">
        <div className="topbar-search-row" style={{ width: "100%" }}>
          <div style={{ position: "relative", flex: 1 }}>
            <Search size={14} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--ink-muted)" }} />
            <input
              ref={inputRef}
              className="search"
              style={{ paddingLeft: 34 }}
              placeholder="ip:50.16.16.211, service_id:ecitizen, account_h:…, domain:…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void investigate(query);
                }
              }}
            />
          </div>
          <button className="btn-accent" type="button" disabled={loading || !query.trim()} onClick={() => void investigate(query)}>
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

      {entityKey && !loading && !error && !prediction && (
        <div className="grid-two">
          <div className="panel">
            <div className="panel-header">
              <h3>No direct model prediction yet</h3>
              <span className="muted">{entityKey}</span>
            </div>
            <p className="muted" style={{ lineHeight: 1.6 }}>
              This entity exists in the graph or evidence trail, but the current model did not return a direct prediction record for it.
              That usually means you selected a structural node such as an endpoint, cluster, or helper object rather than a scored service,
              IP, account, or domain.
            </p>
            {parentEntityKey && (
              <div className="list" style={{ marginTop: 12 }}>
                <div className="list-item">
                  <strong>Recommended fallback</strong>
                  <p className="muted" style={{ marginTop: 4 }}>
                    Investigate the parent service instead: <span className="mono">{parentEntityKey}</span>
                  </p>
                  <div className="chip-row" style={{ marginTop: 10 }}>
                    <button
                      className="chip active"
                      type="button"
                      onClick={() => {
                        setQuery(parentEntityKey);
                        void investigate(parentEntityKey);
                      }}
                    >
                      Investigate parent service
                    </button>
                  </div>
                </div>
              </div>
            )}
            {!parentEntityKey && (
              <div className="list" style={{ marginTop: 12 }}>
                <div className="list-item">
                  <strong>What to do next</strong>
                  <p className="muted" style={{ marginTop: 4 }}>
                    Use this entity as structural context, or switch to a directly scored key such as <span className="mono">service_id:…</span>,
                    <span className="mono"> ip:…</span>, <span className="mono">account_h:…</span>, or <span className="mono">domain:…</span>.
                  </p>
                </div>
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Available graph context</h3>
              <span className="muted">{liveGraph?.neighbours?.length ?? 0} neighbours</span>
            </div>
            {liveGraph?.neighbours?.length ? (
              <div className="list">
                {liveGraph.neighbours.slice(0, 6).map((item) => (
                  <div key={item.id} className="list-item">
                    <strong>{item.label}</strong>
                    <p className="muted" style={{ marginTop: 4 }}>{item.type} · {item.id}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                No live Neo4j neighbours are attached to this entity right now. If you expected graph context here, verify the entity key and retry.
              </p>
            )}
          </div>
        </div>
      )}

      {prediction && (
        <>
          <div className="focus-layout">
            <div className={`panel focus-hero ${prediction.score >= 85 ? "focus-hero-danger" : prediction.score >= 60 ? "focus-hero-warning" : "focus-hero-accent"}`}>
              <p className="focus-kicker">{analysisProfile.title}</p>
              <p className="focus-value">{formatRiskScore(prediction.score)} / 100</p>
              <p className="focus-copy">{summaryText}</p>
              <div className="focus-stat-grid">
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Confidence</div>
                  <div className="focus-stat-value">{prediction.confidence != null ? `${Math.round(prediction.confidence * 100)}%` : "—"}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Uncertainty</div>
                  <div className="focus-stat-value">{Math.round(uncertaintyValue)}%</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Path</div>
                  <div className="focus-stat-value">{formatRiskScore(pathScoreValue)}</div>
                </div>
                <div className="focus-stat-card">
                  <div className="focus-stat-label">Fusion</div>
                  <div className="focus-stat-value">{formatRiskScore(fusedScoreValue)}</div>
                </div>
              </div>
              <div className="chip-row" style={{ marginTop: 16 }}>
                <span className="chip">Entity: {prediction.entity_key}</span>
                <span className="chip">Inference: {decisionSourceLabel(prediction.decision_source)}</span>
                <span className="chip">Kill chain: {killChainLabel(prediction.kill_chain_stage)}</span>
                <span className="chip">Window: {formatTimestamp(prediction.window_end ?? prediction.created_at)}</span>
                <span className="chip">Model: {prediction.model_version ?? "—"}</span>
              </div>
            </div>

            <div className="panel priority-stack">
              <div className="panel-header">
                <h3>Operator action board</h3>
                <span className="muted">{actionHookCount} matching active hooks</span>
              </div>

              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">Threat posture</h4>
                    <p className="priority-card-copy">{trustBrief?.operator_decision ?? "Review the evidence chain before acting."}</p>
                  </div>
                  <span className={`risk-badge ${riskSeverityLabel(prediction.score).toLowerCase()}`}>
                    {riskSeverityLabel(prediction.score)}
                  </span>
                </div>
                {(leadingNextActions.length > 0 || leadingWhyItMatters.length > 0) && (
                  <div className="list" style={{ marginTop: 12 }}>
                    {leadingNextActions.map((item) => (
                      <div key={item} className="list-item">
                        <strong>Next move</strong>
                        <p className="muted" style={{ marginTop: 4 }}>{item}</p>
                      </div>
                    ))}
                    {leadingWhyItMatters.map((item) => (
                      <div key={item} className="list-item">
                        <strong>Why it matters</strong>
                        <p className="muted" style={{ marginTop: 4 }}>{item}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">Inference provenance</h4>
                    <p className="priority-card-copy">
                      This assessment is derived from the prediction record, explanation artifact, graph context, and current governance state.
                    </p>
                  </div>
                  <Sparkles size={16} color="var(--accent)" />
                </div>
                <div className="list" style={{ marginTop: 12 }}>
                  <div className="list-item">
                    <strong>Decision source</strong>
                    <p className="muted" style={{ marginTop: 4 }}>
                      {decisionSourceLabel(prediction.decision_source)} · {confidenceSummary} · {uncertaintySummary}
                    </p>
                  </div>
                  <div className="list-item">
                    <strong>Collection window</strong>
                    <p className="muted" style={{ marginTop: 4 }}>
                      Window end {formatTimestamp(prediction.window_end ?? prediction.created_at)} · kill chain {killChainLabel(prediction.kill_chain_stage)}
                    </p>
                  </div>
                  <div className="list-item">
                    <strong>Top model signal</strong>
                    <p className="muted" style={{ marginTop: 4 }}>
                      {humanizeCode(explanation?.top_feature ?? prediction.top_feature ?? "signal_not_attached")}
                    </p>
                  </div>
                  <div className="list-item">
                    <strong>Governance state</strong>
                    <p className="muted" style={{ marginTop: 4 }}>
                      Real-data gate {governance?.real_data_gate_passed ? "passed" : "warning"} · fairness {String(governance?.fairness_status ?? "unknown")} · drift {String(governance?.drift_status ?? "unknown")}
                    </p>
                  </div>
                  {(realRatio != null || avgRealSignalRatio != null) && (
                    <div className="list-item">
                      <strong>Data realism</strong>
                      <p className="muted" style={{ marginTop: 4 }}>
                        {realRatio != null ? `Real-signal ratio ${Math.round(realRatio * 100)}%` : "Real-signal ratio unavailable"}
                        {avgRealSignalRatio != null ? ` · average per-node real coverage ${Math.round(avgRealSignalRatio * 100)}%` : ""}
                      </p>
                    </div>
                  )}
                </div>
              </div>

              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">Analyst adjudication</h4>
                    <p className="priority-card-copy">
                      {trustSummary?.feedback?.latest_label != null
                        ? `Latest review ${trustSummary.feedback.latest_label} · ${trustSummary.feedback.latest_status ?? "recorded"}`
                        : "No analyst review has been recorded yet for this entity."}
                    </p>
                  </div>
                  <Shield size={16} color="var(--accent)" />
                </div>
                <textarea
                  className="search"
                  style={{ minHeight: 82, resize: "vertical", marginTop: 12 }}
                  placeholder="Add plain-English review notes for the next training cycle or case packet."
                  value={feedbackNotes}
                  onChange={(event) => setFeedbackNotes(event.target.value)}
                />
                <div className="priority-card-actions">
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
                {feedbackStatus && <p className="muted" style={{ marginTop: 10 }}>{feedbackStatus}</p>}
              </div>

              <div className="priority-card">
                <div className="priority-card-head">
                  <div>
                    <h4 className="priority-card-title">Control-plane readiness</h4>
                    <p className="priority-card-copy">{trustBrief?.containment_readiness ?? containmentGuidance}</p>
                  </div>
                  <ShieldAlert size={16} color="var(--warning)" />
                </div>
                <div className="detail-grid" style={{ marginTop: 12 }}>
                  <div>
                    <p className="label">Action</p>
                    <select value={actionType} onChange={(event) => setActionType(event.target.value)} style={{ width: "100%" }}>
                      {actionCatalog.map((item) => (
                        <option key={item.key} value={item.key}>{item.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <p className="label">Target ({selectedAction?.target_hint ?? "entity"})</p>
                    <input
                      className="search"
                      value={actionTarget}
                      onChange={(event) => setActionTarget(event.target.value)}
                      placeholder={selectedAction?.target_hint ?? "Containment target"}
                    />
                  </div>
                </div>
                <div className="priority-card-actions">
                  <button className="btn-accent" type="button" disabled={actionBusy || !actionTarget.trim()} onClick={() => void triggerContainment()}>
                    {actionBusy ? <RefreshCw size={13} className="spin" /> : selectedAction?.delivery_mode === "webhook" && actionHookCount === 0 ? "Record action" : "Execute"}
                  </button>
                  <span className="chip">Receipts: {relatedDeliveries.length}</span>
                </div>
                {actionStatus && <p className="muted" style={{ marginTop: 10 }}>{actionStatus}</p>}
                {containmentAccessNote && <p className="muted" style={{ marginTop: 10 }}>{containmentAccessNote}</p>}
                {selectedAction && (
                  <p className="muted" style={{ marginTop: 10 }}>
                    {selectedAction.description}
                    {selectedAction.continuity_preserving ? " Prefer this when service continuity matters." : " Use this when direct containment is worth temporary disruption."}
                  </p>
                )}
              </div>
            </div>
          </div>

          <div className="grid-two">
            <div className="panel">
              <div className="panel-header">
                <h3><Sparkles size={14} /> AI detection rationale</h3>
                <span className="muted">{trustSummary?.evidence_summary?.reason_count ?? primaryReasons.length} model drivers</span>
              </div>
              <div className="panel-subsection">
                <h4>Analysis sources</h4>
                <div className="list">
                  {analysisSources.map((item) => (
                    <div key={item.title} className="list-item">
                      <strong>{item.title}</strong>
                      <p className="muted" style={{ marginTop: 4 }}>{item.detail}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="panel-subsection">
                <h4>Why the model escalated this entity</h4>
                {reasonInsights.length > 0 ? (
                  <div className="list">
                    {reasonInsights.map((item) => (
                      <div key={item.code} className="list-item">
                        <strong>{item.label}</strong>
                        <p className="muted" style={{ marginTop: 4 }}>{item.detail}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No human-readable reason codes are attached yet for this entity.</p>
                )}
              </div>
              <div className="panel-subsection">
                <h4>Telemetry and model observations</h4>
                <div className="list">
                  {trustBrief?.what_system_saw?.map((item) => (
                    <div key={item} className="list-item">
                      <p style={{ margin: 0 }}>{item}</p>
                    </div>
                  ))}
                  {recommendedControls.length > 0 ? (
                    recommendedControls.map((control) => (
                      <div key={control} className="list-item">
                        <strong>Model-recommended control</strong>
                        <p className="muted" style={{ marginTop: 4 }}>{control}</p>
                      </div>
                    ))
                  ) : (
                    <div className="list-item">
                      <strong>No model-recommended control returned</strong>
                      <p className="muted" style={{ marginTop: 4 }}>
                        Use the Defense workspace for manual response execution once an incident run exists.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3><GitBranch size={14} /> Graph, telemetry, and campaign context</h3>
                <span className="muted">{trustSummary?.evidence_summary?.linked_campaign_count ?? 0} linked campaigns</span>
              </div>
              <div className="story-rail story-rail-four">
                <div className="story-card">
                  <p className="story-card-label">Graph route</p>
                  <h4>{pathScore?.hop_count ?? 0} hops</h4>
                  <p>{trustBrief?.graph_meaning ?? "The graph score measures how strongly this entity is linked to risky neighbours and shared events."}</p>
                </div>
                <div className="story-card">
                  <p className="story-card-label">Evidence depth</p>
                  <h4>{trustSummary?.evidence_summary?.evidence_hash_count ?? explanation?.evidence_hashes?.length ?? 0} hashes</h4>
                  <p>{trustSummary?.evidence_summary?.counterfactual_available ? "Counterfactual evidence is available." : "Counterfactual evidence is not attached yet."}</p>
                </div>
                <div className="story-card">
                  <p className="story-card-label">Tradecraft</p>
                  <h4>{techniqueCount} techniques</h4>
                  <p>
                    {topTechnique
                      ? `Top mapped tactic: ${topTechnique}. ${toolCount} tool inference(s) are attached.`
                      : toolCount > 0
                        ? `${toolCount} tool inference(s) are attached, but no lead tactic was returned.`
                        : "No ATT&CK tactic or tool mapping is attached yet."}
                  </p>
                </div>
                <div className="story-card">
                  <p className="story-card-label">Campaign overlap</p>
                  <h4>{trustSummary?.linked_campaigns?.length ?? 0} campaigns</h4>
                  <p>
                    {trustSummary?.linked_campaigns?.length
                      ? "This entity overlaps with active campaign indicators in the current review window."
                      : "No active campaign overlap is attached to this entity right now."}
                  </p>
                </div>
              </div>
              {(toolAttribution?.techniques?.length || toolAttribution?.tools?.length) ? (
                <div className="panel-subsection">
                  <h4>ATT&CK and tool mapping</h4>
                  <div className="chip-row">
                    {toolAttribution?.techniques?.slice(0, 6).map((item) => (
                      <span key={`${item.technique_id}-${item.tactic ?? ""}`} className="chip">
                        {item.technique_id}{item.tactic ? ` · ${humanizeCode(item.tactic)}` : ""}
                      </span>
                    ))}
                    {toolAttribution?.tools?.slice(0, 3).map((item) => (
                      <span key={`${item.software_id}-${item.name}`} className="chip">
                        {item.name}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
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
              <div className="panel-subsection">
                <h4>Live graph neighbours</h4>
                {liveGraph?.neighbours?.length ? (
                  <div className="list">
                    {liveGraph.neighbours.slice(0, 6).map((item) => {
                      const edge = liveGraph.edges.find(
                        (candidate) =>
                          (candidate.source === entityKey && candidate.target === item.id) ||
                          (candidate.target === entityKey && candidate.source === item.id),
                      );
                      return (
                        <div key={item.id} className="list-item">
                          <strong>{item.label}</strong>
                          <p className="muted" style={{ marginTop: 4 }}>
                            {item.type} · {edge?.type ?? "linked"} · {(edge?.evidence?.length ?? 0)} evidence hashes
                          </p>
                          <p className="mono" style={{ marginTop: 4, fontSize: "0.78rem" }}>{item.id}</p>
                        </div>
                      );
                    })}
                    {!pathScore?.path_score ? (
                      <div className="list-item">
                        <strong>Graph note</strong>
                        <p className="muted" style={{ marginTop: 4 }}>
                          Live graph neighbours exist, but the scored path record for this prediction window has not been attached yet.
                        </p>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p className="muted">No live graph neighbours are available from Neo4j for this entity right now.</p>
                )}
              </div>
              {trustSummary?.linked_campaigns?.length ? (
                <div className="panel-subsection">
                  <h4>Linked campaigns</h4>
                  <div className="list">
                    {trustSummary.linked_campaigns.slice(0, 4).map((item) => (
                      <div key={item.campaign_id} className="list-item">
                        <strong>{item.severity} · {formatRiskScore(item.score)} / 100</strong>
                        <p className="muted" style={{ marginTop: 4 }}>{item.flagged_entity_count} flagged entities</p>
                        <p className="mono" style={{ marginTop: 4, fontSize: "0.78rem" }}>{item.campaign_id}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {trustChecks.length > 0 && (
            <details className="panel panel-details">
              <summary>
                <span>Model trust and governance checks</span>
                <span className="muted">Open detailed trust signals</span>
              </summary>
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
            </details>
          )}

          <div className="grid-two">
          <details className="panel panel-details">
            <summary>
              <span><Wrench size={14} /> Detailed ATT&CK and tool attribution</span>
              <span className="muted">
                  {toolAttribution?.summary?.tool_count ?? toolAttribution?.tools?.length ?? 0} tools
              </span>
            </summary>
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
            </details>

            <details className="panel panel-details">
            <summary>
              <span><FileText size={14} /> Case packet and downloads</span>
              <span className="muted">Open export actions</span>
            </summary>
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
            </details>
          </div>

          <details className="panel panel-details">
            <summary>
              <span><Bot size={14} /> Analyst assistant</span>
              <span className="muted">Ask only when you need more detail</span>
            </summary>
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
                "Why did the GNN elevate this node?",
                "What graph evidence matters most here?",
                "Is this GNN inference or heuristic fallback?",
                "How should I brief this cyber entity clearly?",
                "How strong is the governance posture behind this score?",
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
          </details>
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
