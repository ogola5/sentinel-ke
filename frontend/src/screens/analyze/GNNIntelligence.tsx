import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AlertTriangle,
  Brain,
  CheckCircle,
  Database,
  HelpCircle,
  Loader,
  Play,
  RefreshCw,
  XCircle,
  Zap,
} from "lucide-react";

import ArchitectureFlow from "../../app/ArchitectureFlow";
import {
  bootstrapDemoData,
  fetchAIFeedback,
  fetchAIForecast,
  fetchAIScenarioForecast,
  fetchAIPredictions,
  fetchGNNTrainingRuns,
  startDemoScenario,
  submitAIFeedback,
  triggerGNNTrain,
} from "../../api/ai";
import type {
  AIFeedback,
  AIPrediction,
  AIScenarioForecast,
  FairnessMetrics,
  GNNTrainingRun,
} from "../../types/ai";
import { clampRiskPercent, formatRiskScore, isHighRisk, riskColor, riskSeverityLabel } from "../../utils/risk";

const ANALYST_ID_STORAGE_KEY = "sentinel_analyst_id";

type Domain = "cyber" | "corruption";
type DomainWindowKey = "Wmid" | "Wcorruption";
type GNNView = "overview" | "review" | "ops";
type CyberScenario = "ddos" | "vpn" | "sim_swap" | "ddos_vpn" | "ddos_vpn_fraud";

const DOMAIN_OPTIONS: Array<{ domain: Domain; windowKey: DomainWindowKey; label: string }> = [
  { domain: "cyber", windowKey: "Wmid", label: "Cyber (Wmid)" },
  { domain: "corruption", windowKey: "Wcorruption", label: "Corruption (Wcorruption)" },
];

const FAIRNESS_COLORS: Record<"PASS" | "WARN" | "FAIL", string> = {
  PASS: "#30d158",
  WARN: "#ff9f0a",
  FAIL: "#ff2d55",
};

const FEEDBACK_OPTIONS = [
  { label: "Confirm threat", value: 1 as const, icon: CheckCircle },
  { label: "False positive", value: 0 as const, icon: XCircle },
  { label: "Uncertain", value: 2 as const, icon: HelpCircle },
];

const CYBER_SCENARIO_OPTIONS: Array<{
  id: CyberScenario;
  label: string;
  summary: string;
}> = [
  {
    id: "ddos",
    label: "DDoS pressure",
    summary: "Simulates a rising burst against KPLC login infrastructure with IP fan-in and degrading service health.",
  },
  {
    id: "vpn",
    label: "VPN login reuse",
    summary: "Simulates repeated successful logins from a rotating IP pool through a VPN-like provider pattern.",
  },
  {
    id: "sim_swap",
    label: "SIM swap / fraud",
    summary: "Simulates a Kenyan mobile-money fraud chain: SIM swap, suspicious login, transfer to mule, then agent cash-out.",
  },
  {
    id: "ddos_vpn",
    label: "DDoS + VPN",
    summary: "Simulates concurrent DDoS pressure and credential reuse through VPN-like access patterns.",
  },
  {
    id: "ddos_vpn_fraud",
    label: "Combined pressure",
    summary: "Simulates DDoS, VPN-style login abuse, and SIM-swap fraud pressure in one combined rehearsal.",
  },
];

const GNN_VIEW_CONTENT: Record<GNNView, {
  kicker: string;
  title: string;
  summary: string;
  steps: [string, string, string];
}> = {
  overview: {
    kicker: "Model snapshot",
    title: "Read model state first.",
    summary: "Confirm artifact, data posture, and queue pressure before acting.",
    steps: [
      "Check the artifact and core metrics.",
      "Read the latest run trend.",
      "Only then move into review.",
    ],
  },
  review: {
    kicker: "Review queue",
    title: "Work the analyst queue.",
    summary: "Start with uncertain or high-risk entities, then label the outcome.",
    steps: [
      "Start with uncertain or high-risk rows.",
      "Read the top driver before labeling.",
      "Submit feedback from the queue.",
    ],
  },
  ops: {
    kicker: "Model operations",
    title: "Seed, retrain, and rehearse here.",
    summary: "Keep model operations separate from daily review.",
    steps: [
      "Seed only when you need fresh data.",
      "Run training for the selected domain.",
      "Open diagnostics only when needed.",
    ],
  },
};

function FairnessBadge({
  fairness,
  blocked,
}: {
  fairness?: FairnessMetrics;
  blocked?: boolean;
}) {
  if (!fairness) return null;
  const flag = fairness.fairness_flag;
  const color = FAIRNESS_COLORS[flag];
  return (
    <div className="metric-card" style={{ borderLeft: `4px solid ${color}` }}>
      <div className="metric-label">Fairness</div>
      <div className="metric-value" style={{ color }}>{flag}</div>
      <div className="metric-sub">
        Max disparity: {(fairness.max_positive_rate_disparity * 100).toFixed(1)}%
        &nbsp;·&nbsp;{fairness.types_evaluated} groups
      </div>
      {blocked && (
        <div style={{ marginTop: 4, fontSize: 11, color: "#ff2d55", fontWeight: 600 }}>
          Deployment blocked by fairness policy
        </div>
      )}
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asNumber(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function metricNumber(source: unknown, ...keys: string[]): number | null {
  if (keys.length === 0) return asNumber(source);
  const record = asRecord(source);
  for (const key of keys) {
    const parsed = asNumber(record[key]);
    if (parsed != null) return parsed;
  }
  return null;
}

function asNumberArray(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => Number(entry))
    .filter((entry) => Number.isFinite(entry));
}

function clampPercent(value: number | null | undefined): number {
  if (value == null) return 0;
  return Math.max(0, Math.min(100, value * 100));
}

function uncertaintyColor(uncertainty: number | null | undefined): string {
  if ((uncertainty ?? 0) >= 0.75) return "var(--risk-critical)";
  if ((uncertainty ?? 0) >= 0.5) return "var(--warning)";
  return "var(--accent)";
}

function shortKey(key: string): string {
  return key.length > 14 ? `${key.slice(0, 6)}…${key.slice(-6)}` : key;
}

function feedbackClass(label: number): "confirmed" | "false_positive" | "uncertain" {
  if (label === 1) return "confirmed";
  if (label === 0) return "false_positive";
  return "uncertain";
}

function feedbackLabelText(label: number): string {
  if (label === 1) return "Threat confirmed";
  if (label === 0) return "False positive";
  return "Marked uncertain";
}

function loadAnalystId(): string {
  const fromEnv = String(import.meta.env.VITE_ANALYST_ID ?? "").trim();
  if (fromEnv) return fromEnv;
  if (typeof window === "undefined") return "sentinel-ui-analyst";

  const fromStorage = window.localStorage.getItem(ANALYST_ID_STORAGE_KEY)?.trim();
  if (fromStorage) return fromStorage;

  const generated = `sentinel-ui-${Math.random().toString(36).slice(2, 10)}`;
  window.localStorage.setItem(ANALYST_ID_STORAGE_KEY, generated);
  return generated;
}

function describeDataRealism(
  realRatio: number | null,
  avgRealSignalRatio: number | null,
  feedbackOverrideCount: number | null,
  feedbackConsumedCount: number | null,
): string {
  let base = "No current provenance statement is attached to this run.";
  if (realRatio != null) {
    if (realRatio >= 0.7) {
      base = "This run is mostly driven by real or mixed-source signals.";
    } else if (realRatio >= 0.35) {
      base = "This run uses a mixed real-plus-synthetic dataset.";
    } else {
      base = "This run is still mostly synthetic or demo-oriented and should be used for triage, not proof.";
    }
  }
  const extras: string[] = [];
  if (realRatio != null) extras.push(`Real-signal ratio ${Math.round(realRatio * 100)}%.`);
  if (avgRealSignalRatio != null) extras.push(`Average per-node real coverage ${Math.round(avgRealSignalRatio * 100)}%.`);
  if (feedbackOverrideCount != null && feedbackOverrideCount > 0) {
    extras.push(
      `${feedbackOverrideCount} analyst feedback label${feedbackOverrideCount === 1 ? "" : "s"} influenced training${feedbackConsumedCount != null ? `, including ${feedbackConsumedCount} newly consumed` : ""}.`,
    );
  }
  return [base, ...extras].join(" ");
}

function describeModelMeaning(domain: Domain): string {
  if (domain === "corruption") {
    return "This GNN looks for risky relationships across suppliers, payments, procurement entities, and governance signals. A higher score means the entity deserves more integrity review, not automatic enforcement.";
  }
  return "This GNN looks at linked cyber entities and shared activity, not isolated alerts. A higher score means the entity deserves more analyst attention, not that an attack is certain.";
}

function describeUncertaintyMeaning(): string {
  return "Uncertainty is the model’s caution signal. High uncertainty means the analyst should slow down, read the evidence, and avoid treating the score as proof.";
}

function scenarioLabelFor(scenario: CyberScenario): string {
  return CYBER_SCENARIO_OPTIONS.find((option) => option.id === scenario)?.label ?? scenario;
}

interface Props {
  healthGnnLoaded: boolean;
  healthModelVersion: string | null;
  healthGnnMetrics: Record<string, unknown>;
}

export default function GNNIntelligence({
  healthGnnLoaded,
  healthModelVersion,
  healthGnnMetrics,
}: Props) {
  const [runs, setRuns] = useState<GNNTrainingRun[]>([]);
  const [predictions, setPredictions] = useState<AIPrediction[]>([]);
  const [feedbackByPrediction, setFeedbackByPrediction] = useState<Record<string, AIFeedback>>({});
  const [activeDomain, setActiveDomain] = useState<Domain>("cyber");
  const [view, setView] = useState<GNNView>("overview");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [trainMsg, setTrainMsg] = useState<string | null>(null);
  const [trainBusy, setTrainBusy] = useState(false);
  const [seedBusy, setSeedBusy] = useState(false);
  const [feedbackBusyId, setFeedbackBusyId] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [showAllMetrics, setShowAllMetrics] = useState(false);
  const [forecast, setForecast] = useState<Record<string, unknown> | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [selectedScenario, setSelectedScenario] = useState<CyberScenario>("sim_swap");
  const [scenarioForecast, setScenarioForecast] = useState<AIScenarioForecast | null>(null);
  const [scenarioForecastLoading, setScenarioForecastLoading] = useState(false);
  const [scenarioBusy, setScenarioBusy] = useState(false);

  const analystId = useMemo(() => loadAnalystId(), []);
  const activeWindowKey = DOMAIN_OPTIONS.find((option) => option.domain === activeDomain)?.windowKey ?? "Wmid";

  const load = useCallback(async () => {
    setSyncing(true);
    setFeedbackError("");
    setLoadError("");
    try {
      const [runRows, predictionRows, feedbackRows] = await Promise.all([
        fetchGNNTrainingRuns(24, { strict: true }),
        fetchAIPredictions(50, activeWindowKey, { strict: true }),
        fetchAIFeedback(analystId, 200),
      ]);
      setRuns(runRows);
      setPredictions(predictionRows);
      setFeedbackByPrediction(
        feedbackRows.reduce<Record<string, AIFeedback>>((acc, row) => {
          acc[row.prediction_id] = row;
          return acc;
        }, {}),
      );
    } catch (err) {
      setRuns([]);
      setPredictions([]);
      setFeedbackByPrediction({});
      setLoadError(err instanceof Error ? err.message : "gnn_data_load_failed");
    } finally {
      setLoading(false);
      setSyncing(false);
    }
  }, [activeWindowKey, analystId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (view !== "ops" || forecast !== null) return;
    setForecastLoading(true);
    fetchAIForecast(30, 7)
      .then((data) => setForecast(data))
      .catch(() => setForecast(null))
      .finally(() => setForecastLoading(false));
  }, [view, forecast]);

  const loadScenarioForecast = useCallback(async (scenario: CyberScenario) => {
    setScenarioForecastLoading(true);
    try {
      const data = await fetchAIScenarioForecast(scenario, 48, 24);
      setScenarioForecast(data);
      return data;
    } finally {
      setScenarioForecastLoading(false);
    }
  }, []);

  useEffect(() => {
    if (view !== "ops" || activeDomain !== "cyber") return;
    void loadScenarioForecast(selectedScenario);
  }, [activeDomain, loadScenarioForecast, selectedScenario, view]);

  const handleSeed = async (domain: Domain) => {
    setSeedBusy(true);
    setTrainMsg(null);
    try {
      const response = await bootstrapDemoData(
        domain,
        domain === "cyber" ? selectedScenario : "ddos_vpn_fraud",
      );
      setTrainMsg(
        domain === "cyber"
          ? `Bootstrap started for ${scenarioLabelFor(selectedScenario)}: ${response.message}`
          : `Bootstrap started: ${response.message}`,
      );
    } catch (error: unknown) {
      setTrainMsg(`Seed failed: ${String(error)}`);
    } finally {
      setSeedBusy(false);
    }
  };

  const handleTrain = async (domain: Domain) => {
    setTrainBusy(true);
    setTrainMsg(null);
    try {
      const response = asRecord(
        await triggerGNNTrain(domain, 25, {
          waitForCompletion: true,
          allowDemoRealDataOverride: true,
          allowDemoFairnessOverride: true,
        }),
      );
      const status = String(response.status ?? "unknown");
      const modelVersion = String(response.model_version ?? "unknown");
      const runId = String(response.gnn_run_id ?? "");
      const predictionsCreated = metricNumber(response, "predictions_created", "predictions");
      const overrideApplied = response.real_data_gate_override_applied === true;
      const fairnessOverrideApplied = response.fairness_gate_override_applied === true;

      if (status === "ok") {
        setTrainMsg(
          `Training completed (${modelVersion})${runId ? ` · run ${runId}` : ""}${predictionsCreated != null ? ` · ${predictionsCreated} predictions written` : ""}${overrideApplied ? " · demo real-data override applied" : ""}${fairnessOverrideApplied ? " · demo fairness override applied" : ""}.`,
        );
      } else if (status === "blocked") {
        const gate = String(response.gate ?? "unknown");
        const detail = String(response.detail ?? "Training was blocked by governance.");
        setTrainMsg(`Training blocked by ${gate}: ${detail}`);
      } else {
        const detail = String(response.detail ?? "Training failed.");
        setTrainMsg(`Train failed: ${detail}`);
      }
      await load();
      if (domain === "cyber") {
        await loadScenarioForecast(selectedScenario);
      }
    } catch (error: unknown) {
      setTrainMsg(`Train failed: ${String(error)}`);
    } finally {
      setTrainBusy(false);
    }
  };

  const handleScenarioReplay = async () => {
    setScenarioBusy(true);
    setTrainMsg(null);
    try {
      const response = await startDemoScenario(selectedScenario);
      setTrainMsg(
        `Scenario replay started for ${scenarioLabelFor(selectedScenario)}: ${response.message ?? "Synthetic events are being ingested now."}`,
      );
      window.setTimeout(() => {
        void loadScenarioForecast(selectedScenario);
      }, 1200);
    } catch (error: unknown) {
      setTrainMsg(`Scenario replay failed: ${String(error)}`);
    } finally {
      setScenarioBusy(false);
    }
  };

  const handleFeedback = async (predictionId: string, feedbackLabel: 0 | 1 | 2) => {
    setFeedbackBusyId(predictionId);
    setFeedbackError("");
    const response = await submitAIFeedback(predictionId, feedbackLabel, analystId);
    if (!response) {
      setFeedbackError("Feedback submission failed. Check API key and backend auth.");
      setFeedbackBusyId(null);
      return;
    }
    setFeedbackByPrediction((prev) => ({ ...prev, [predictionId]: response }));
    setFeedbackBusyId(null);
  };

  const filteredRuns = useMemo(
    () => runs.filter((run) => (run.window_key ?? "") === activeWindowKey),
    [runs, activeWindowKey],
  );

  const latestRun = filteredRuns[0] ?? null;
  const latestMetrics = asRecord(latestRun?.metrics);
  const latestProvenance = asRecord(latestRun?.provenance ?? latestMetrics.provenance);
  const latestFeedbackMetrics = asRecord(latestMetrics.feedback);

  const auc = latestRun?.auc ?? metricNumber(healthGnnMetrics, "auc");
  const precision = latestRun?.precision ?? metricNumber(healthGnnMetrics, "precision");
  const recall = latestRun?.recall ?? metricNumber(latestMetrics, "recall") ?? metricNumber(healthGnnMetrics, "recall");
  const f1 = latestRun?.f1 ?? metricNumber(latestMetrics, "f1") ?? metricNumber(healthGnnMetrics, "f1");
  const ece = metricNumber(latestMetrics, "calibration_ece", "ece") ?? metricNumber(healthGnnMetrics, "calibration_ece", "ece");
  const brierScore = metricNumber(latestMetrics, "brier_score", "brier") ?? metricNumber(healthGnnMetrics, "brier_score", "brier");
  const nodeCount = latestRun?.node_count ?? metricNumber(healthGnnMetrics, "node_count");
  const edgeCount = latestRun?.edge_count ?? metricNumber(healthGnnMetrics, "edge_count");
  const positiveCount = latestRun?.positive_count ?? metricNumber(healthGnnMetrics, "positive_count");
  const featureDim = latestRun?.feature_dim ?? metricNumber(healthGnnMetrics, "feature_dim");
  const modelVersion = latestRun?.model_version ?? healthModelVersion ?? "—";
  const predictionType = latestRun?.prediction_type ?? (typeof healthGnnMetrics.prediction_type === "string" ? healthGnnMetrics.prediction_type : "—");
  const realRatio = metricNumber(latestProvenance, "real_ratio");
  const avgRealSignalRatio = metricNumber(latestProvenance, "avg_real_signal_ratio");
  const feedbackOverrideCount = metricNumber(latestFeedbackMetrics, "override_count");
  const feedbackConsumedCount = metricNumber(latestFeedbackMetrics, "consumed_count", "new_feedback_count");
  const realGateOverrideApplied =
    asRecord(latestRun?.real_data_gate ?? latestMetrics.real_data_gate).override_applied === true;
  const fairnessGateOverrideApplied =
    asRecord(latestRun?.metrics?.fairness_gate ?? latestMetrics.fairness_gate).override_applied === true;

  const epochTrainLosses = asNumberArray(latestMetrics.epoch_train_losses);
  const epochValLosses = asNumberArray(latestMetrics.epoch_val_losses);
  const epochChartData = epochTrainLosses.map((trainLoss, index) => ({
    epoch: index + 1,
    train: Math.round(trainLoss * 10000) / 10000,
    val: epochValLosses[index] != null ? Math.round(epochValLosses[index] * 10000) / 10000 : undefined,
  }));

  const radialData = [
    { name: "AUC", value: clampPercent(auc), fill: "var(--accent)" },
    { name: "Precision", value: clampPercent(precision), fill: "var(--info)" },
    { name: "Recall", value: clampPercent(recall), fill: "var(--warning)" },
  ];

  const runsChartData = filteredRuns
    .slice()
    .reverse()
    .map((run, index) => ({
      idx: index + 1,
      auc: run.auc != null ? Math.round(run.auc * 1000) / 10 : null,
      precision: run.precision != null ? Math.round(run.precision * 1000) / 10 : null,
      recall: run.recall != null ? Math.round(run.recall * 1000) / 10 : null,
    }));

  const sortedPredictions = useMemo(
    () =>
      predictions
        .slice()
        .sort(
          (left, right) =>
            (right.uncertainty ?? 0) - (left.uncertainty ?? 0) ||
            right.score - left.score,
        ),
    [predictions],
  );

  const highRiskCount = sortedPredictions.filter((prediction) => isHighRisk(prediction.score)).length;
  const needsReviewCount = sortedPredictions.filter((prediction) => (prediction.uncertainty ?? 0) >= 0.5).length;
  const abstainedCount = sortedPredictions.filter((prediction) => prediction.abstained).length;
  const viewContent = GNN_VIEW_CONTENT[view];
  const dataRealismStatement = describeDataRealism(
    realRatio,
    avgRealSignalRatio,
    feedbackOverrideCount,
    feedbackConsumedCount,
  );
  const modelMeaningStatement = describeModelMeaning(activeDomain);
  const uncertaintyMeaningStatement = describeUncertaintyMeaning();
  const selectedScenarioOption = CYBER_SCENARIO_OPTIONS.find((option) => option.id === selectedScenario) ?? CYBER_SCENARIO_OPTIONS[0];

  return (
    <div className="screen">
      <div className="screen-header">
        <h2>
          <Brain size={20} color="var(--accent)" />
          GNN Intelligence Hub
          <span className="subtitle">— graph scores, review queue, and model operations</span>
        </h2>
        <div className="screen-header-actions">
          <div className="gnn-domain-tabs">
            {DOMAIN_OPTIONS.map((option) => (
              <button
                key={option.domain}
                type="button"
                className={activeDomain === option.domain ? "gnn-domain-tab active" : "gnn-domain-tab"}
                onClick={() => setActiveDomain(option.domain)}
              >
                {option.label}
              </button>
            ))}
          </div>
          <button type="button" className="btn-ghost" onClick={() => void load()} disabled={syncing}>
            {syncing ? <Loader size={14} className="spin" /> : <RefreshCw size={14} />}
            &nbsp;Refresh
          </button>
        </div>
      </div>

      <ArchitectureFlow
        label={viewContent.kicker}
        title={viewContent.title}
        summary={viewContent.summary}
        steps={[
          { stage: "Input", title: activeDomain === "cyber" ? "Canonical security events" : "Procurement and integrity events", detail: activeDomain === "cyber" ? "Telemetry is normalized before modeling." : "Awards, payments, registry links, and outcomes feed the same graph.", tone: "info" },
          { stage: "Graph", title: "Entity snapshots", detail: `The model reads ${activeWindowKey} graph features rather than flat logs.`, tone: "accent" },
          { stage: "Model", title: "Score and uncertainty", detail: "Risk, confidence, and caveats are written back into the platform.", tone: "warning" },
          { stage: "Review", title: "Analyst feedback", detail: "Review decisions and labels feed the next training cycle.", tone: "danger" },
        ]}
      />

      <div className="chip-row">
        {[
          { id: "overview", label: "Overview" },
          { id: "review", label: "Review Queue" },
          { id: "ops", label: "Model Ops" },
        ].map((item) => (
          <button
            key={item.id}
            type="button"
            className={view === item.id ? "chip active" : "chip ghost"}
            onClick={() => setView(item.id as GNNView)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="workflow-summary-banner">
        <div>
          <strong>{modelVersion}</strong>
          <span className="muted">{predictionType} · {activeWindowKey}</span>
        </div>
        <div>
          <strong>{sortedPredictions.length}</strong>
          <span className="muted">Entities in the current review set</span>
        </div>
        <div>
          <strong>{latestRun?.created_at ? new Date(latestRun.created_at).toLocaleString() : "—"}</strong>
          <span className="muted">Latest run written to the platform</span>
        </div>
      </div>

      {loadError && (
        <div className="panel" style={{ borderColor: "rgba(255,77,90,.35)" }}>
          <span className="muted" style={{ fontSize: "0.82rem" }}>{loadError}</span>
        </div>
      )}

      {view === "overview" && (
        <div className="workflow-stack">
          {!healthGnnLoaded && (
            <div className="panel gnn-no-artifact-banner">
              <div className="gnn-no-artifact-inner">
                <AlertTriangle size={16} />
                <span>
                  No trained GNN artifact is loaded. Use Model Ops to seed data and train the selected domain.
                </span>
              </div>
            </div>
          )}

          <div className="grid-two">
            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Model meaning</h3>
                <span className="muted">{activeDomain === "cyber" ? "Cyber graph" : "Integrity graph"}</span>
              </div>
              <div className="list">
                <div className="list-item">
                  <strong>What the model is doing</strong>
                  <p className="muted" style={{ marginTop: 4 }}>{modelMeaningStatement}</p>
                </div>
                <div className="list-item">
                  <strong>How to read the score</strong>
                  <p className="muted" style={{ marginTop: 4 }}>
                    Low means monitor. Mid-range means investigate. High means review now and prepare action. The score is an attention signal, not proof.
                  </p>
                </div>
                <div className="list-item">
                  <strong>How to read uncertainty</strong>
                  <p className="muted" style={{ marginTop: 4 }}>{uncertaintyMeaningStatement}</p>
                </div>
              </div>
            </div>

            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Data posture</h3>
                <span className="muted">Real feeds, simulation, and review labels</span>
              </div>
              <div className="list">
                <div className="list-item">
                  <strong>Provenance statement</strong>
                  <p className="muted" style={{ marginTop: 4 }}>{dataRealismStatement}</p>
                </div>
                <div className="list-item">
                  <strong>Judge-safe framing</strong>
                  <p className="muted" style={{ marginTop: 4 }}>
                    Present this as a mixed-source operational model. The strength is visible provenance and a review loop, not a claim of perfect ground truth.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="metric-grid">
            <div className="metric-card accent">
              <div className="metric-label">AUC</div>
              <div className="metric-value">{auc != null ? auc.toFixed(3) : "—"}</div>
              <div className="metric-sub">Area under ROC curve</div>
            </div>
            <div className="metric-card accent">
              <div className="metric-label">F1 Score</div>
              <div className="metric-value">{f1 != null ? f1.toFixed(3) : "—"}</div>
              <div className="metric-sub">Balanced quality for the latest run</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">High-risk queue</div>
              <div className={`metric-value${highRiskCount > 0 ? " gnn-metric-danger" : ""}`}>{highRiskCount}</div>
              <div className="metric-sub">Scores at or above 70 / 100</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Needs review</div>
              <div className={`metric-value${needsReviewCount > 0 ? " gnn-metric-warn" : ""}`}>{needsReviewCount}</div>
              <div className="metric-sub">Uncertainty threshold exceeded</div>
            </div>
            <div className="metric-card info">
              <div className="metric-label">Real-signal ratio</div>
              <div className="metric-value">{realRatio != null ? `${Math.round(realRatio * 100)}%` : "—"}</div>
              <div className="metric-sub">Real + mixed nodes in the latest run</div>
            </div>
            <div className="metric-card info">
              <div className="metric-label">Feedback labels used</div>
              <div className="metric-value">{feedbackOverrideCount != null ? feedbackOverrideCount : "—"}</div>
              <div className="metric-sub">
                {feedbackConsumedCount != null ? `${feedbackConsumedCount} newly consumed` : "Analyst overrides applied"}
              </div>
            </div>
          </div>

          <div className="gnn-charts-grid">
            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Model performance</h3>
                <span className="muted">{modelVersion}</span>
              </div>
              {auc != null ? (
                <ResponsiveContainer width="100%" height={220}>
                  <RadialBarChart cx="50%" cy="50%" innerRadius={40} outerRadius={90} data={radialData} startAngle={90} endAngle={-270}>
                    <RadialBar dataKey="value" cornerRadius={6} background={{ fill: "rgba(31,63,46,0.35)" }} />
                    <Legend iconType="circle" layout="horizontal" verticalAlign="bottom" wrapperStyle={{ fontSize: "0.75rem", opacity: 0.7 }} />
                    <Tooltip
                      formatter={(value: number | string | undefined) => [`${Number(value ?? 0)}%`]}
                      contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8 }}
                    />
                  </RadialBarChart>
                </ResponsiveContainer>
              ) : (
                <div className="state-box"><Brain size={28} /><p>No model metrics yet.</p></div>
              )}
            </div>

            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Training history</h3>
                <span className="muted">{filteredRuns.length} runs</span>
              </div>
              {runsChartData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={runsChartData} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="idx" tick={{ fontSize: 10, fill: "var(--ink-muted)" }} />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "var(--ink-muted)" }} unit="%" />
                    <Tooltip
                      contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                      formatter={(value: number | string | undefined) => [`${Number(value ?? 0).toFixed(1)}%`]}
                    />
                    <Line type="monotone" dataKey="auc" name="AUC" stroke="var(--accent)" strokeWidth={2} dot={{ r: 3 }} />
                    <Line type="monotone" dataKey="precision" name="Precision" stroke="var(--info)" strokeWidth={2} dot={{ r: 3 }} />
                    <Line type="monotone" dataKey="recall" name="Recall" stroke="var(--warning)" strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="state-box"><Zap size={24} /><p>No training history yet.</p></div>
              )}
            </div>
          </div>
        </div>
      )}

      {view === "review" && (
        <div className="workflow-stack">
          {feedbackError && (
            <div className="panel" style={{ borderColor: "rgba(255,140,66,.35)" }}>
              <div style={{ color: "var(--risk-high)", fontSize: "0.85rem" }}>{feedbackError}</div>
            </div>
          )}

          <div className="workflow-summary-banner">
            <div>
              <strong>{needsReviewCount}</strong>
              <span className="muted">Rows currently above the uncertainty threshold</span>
            </div>
            <div>
              <strong>{highRiskCount}</strong>
              <span className="muted">Rows already above the risk escalation threshold</span>
            </div>
            <div>
              <strong>{abstainedCount}</strong>
              <span className="muted">Rows skipped because the model abstained</span>
            </div>
          </div>

          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>Entity review queue</h3>
              <span className="muted">
                {sortedPredictions.length} predictions · {activeDomain === "cyber" ? "Cyber / Wmid" : "Corruption / Wcorruption"}
                {needsReviewCount > 0 && <span className="gnn-uncertain-badge">&nbsp;· {needsReviewCount} need review</span>}
              </span>
            </div>
            {loading ? (
              <div className="state-box"><Loader size={22} /><p>Loading predictions…</p></div>
            ) : sortedPredictions.length === 0 ? (
              <div className="state-box"><Brain size={28} /><p>No predictions yet. Train the model or run inference first.</p></div>
            ) : (
              <div className="gnn-table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Entity</th>
                      <th>Risk Score</th>
                      <th>Uncertainty</th>
                      <th>Confidence</th>
                      <th>Kill-Chain</th>
                      <th>Top Driver</th>
                      <th>Status</th>
                      <th>Analyst Feedback</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedPredictions.map((prediction) => {
                      const uncertainty = prediction.uncertainty ?? 0;
                      const isHighUncertain = uncertainty >= 0.5;
                      const feedback = feedbackByPrediction[prediction.id];
                      const busy = feedbackBusyId === prediction.id;
                      return (
                        <tr key={prediction.id} className={isHighUncertain ? "gnn-row-uncertain" : undefined}>
                          <td>
                            <span className="mono gnn-entity-key">{shortKey(prediction.entity_key)}</span>
                            <span className="muted gnn-pred-type">{prediction.prediction_type}</span>
                          </td>
                          <td>
                            <div className="score-bar-wrap">
                              <div className="score-bar-track">
                                <div
                                  className="score-bar-fill"
                                  style={{ width: `${clampRiskPercent(prediction.score)}%`, background: riskColor(prediction.score) }}
                                />
                              </div>
                              <span className="gnn-score-label" style={{ color: riskColor(prediction.score) }}>
                                {formatRiskScore(prediction.score)}
                              </span>
                            </div>
                          </td>
                          <td>
                            <div className="score-bar-wrap">
                              <div className="score-bar-track">
                                <div
                                  className="score-bar-fill"
                                  style={{ width: `${uncertainty * 100}%`, background: uncertaintyColor(uncertainty) }}
                                />
                              </div>
                              <span className="gnn-score-label" style={{ color: uncertaintyColor(uncertainty) }}>
                                {uncertainty.toFixed(3)}
                              </span>
                            </div>
                          </td>
                          <td className="gnn-cell-sm">
                            {prediction.confidence != null ? `${Math.round(prediction.confidence * 100)}%` : "—"}
                          </td>
                          <td>
                            {prediction.kill_chain_stage ? (
                              <span className="risk-badge info">{prediction.kill_chain_stage}</span>
                            ) : (
                              <span className="muted">—</span>
                            )}
                          </td>
                          <td>
                            {prediction.top_feature ? (
                              <span className="mono gnn-top-feature">{prediction.top_feature}</span>
                            ) : (
                              <span className="muted">—</span>
                            )}
                          </td>
                          <td>
                            {prediction.abstained ? (
                              <span className="risk-badge medium">Abstained</span>
                            ) : (
                              <span className={`risk-badge ${riskSeverityLabel(prediction.score).toLowerCase()}`}>
                                {riskSeverityLabel(prediction.score)}
                              </span>
                            )}
                          </td>
                          <td>
                            {feedback ? (
                              <span className={`gnn-feedback-done ${feedbackClass(feedback.feedback_label)}`}>
                                {feedbackLabelText(feedback.feedback_label)}
                              </span>
                            ) : (
                              <div className="gnn-feedback-btns">
                                {FEEDBACK_OPTIONS.map((option) => {
                                  const Icon = option.icon;
                                  return (
                                    <button
                                      key={option.value}
                                      type="button"
                                      className={`gnn-fb-btn ${feedbackClass(option.value) === "confirmed" ? "confirm" : feedbackClass(option.value) === "false_positive" ? "reject" : "uncertain"}`}
                                      title={option.label}
                                      disabled={busy}
                                      onClick={() => void handleFeedback(prediction.id, option.value)}
                                    >
                                      {busy ? <Loader size={11} className="spin" /> : <Icon size={13} />}
                                    </button>
                                  );
                                })}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {view === "ops" && (
        <div className="workflow-stack">
          {activeDomain === "cyber" && (
            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Scenario rehearsal and next 24 hours</h3>
                <span className="muted">
                  {selectedScenarioOption.label} · simulate now, then forecast hourly pressure for the next day
                </span>
              </div>

              <div className="workflow-summary-banner" style={{ marginBottom: 14 }}>
                <div>
                  <strong>{selectedScenarioOption.label}</strong>
                  <span className="muted">Selected Kenyan scenario</span>
                </div>
                <div>
                  <strong>48h</strong>
                  <span className="muted">Lookback window for the hourly signal</span>
                </div>
                <div>
                  <strong>24h</strong>
                  <span className="muted">Forecast horizon shown to the operator</span>
                </div>
              </div>

              <div className="list" style={{ marginBottom: 14 }}>
                <div className="list-item">
                  <strong>What this scenario simulates</strong>
                  <p className="muted" style={{ marginTop: 4 }}>{selectedScenarioOption.summary}</p>
                </div>
              </div>

              <div className="detail-grid" style={{ marginBottom: 14 }}>
                <label className="field">
                  <span className="muted" style={{ display: "block", marginBottom: 6 }}>Scenario</span>
                  <select
                    value={selectedScenario}
                    onChange={(event) => setSelectedScenario(event.target.value as CyberScenario)}
                    disabled={scenarioBusy || seedBusy || trainBusy}
                    style={{ width: "100%", padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--panel-elevated)", color: "var(--ink)" }}
                  >
                    {CYBER_SCENARIO_OPTIONS.map((option) => (
                      <option key={option.id} value={option.id}>{option.label}</option>
                    ))}
                  </select>
                </label>
              </div>

              <div className={`gnn-train-actions${trainMsg ? " has-msg" : ""}`} style={{ marginBottom: 14 }}>
                <button type="button" className="btn-ghost" onClick={() => void handleScenarioReplay()} disabled={scenarioBusy || seedBusy || trainBusy}>
                  {scenarioBusy ? <Loader size={13} className="spin" /> : <Play size={13} />}
                  &nbsp;Simulate selected scenario
                </button>
                <button type="button" className="btn-ghost" onClick={() => void handleSeed("cyber")} disabled={scenarioBusy || seedBusy || trainBusy}>
                  {seedBusy ? <Loader size={13} className="spin" /> : <Database size={13} />}
                  &nbsp;Bootstrap + retrain cyber demo
                </button>
                <button type="button" className="btn-train-cyber" onClick={() => void loadScenarioForecast(selectedScenario)} disabled={scenarioForecastLoading || scenarioBusy || seedBusy || trainBusy}>
                  {scenarioForecastLoading ? <Loader size={13} className="spin" /> : <RefreshCw size={13} />}
                  &nbsp;Forecast next 24 hours
                </button>
              </div>

              {scenarioForecastLoading && (
                <div className="state-box"><Loader size={18} className="spin" /><p>Building hourly scenario forecast…</p></div>
              )}

              {!scenarioForecastLoading && scenarioForecast && (() => {
                const alertRec = scenarioForecast.alert_recommendation ?? {};
                const alertLevel = String(alertRec.level ?? "");
                const alertMsg = String(alertRec.message ?? "");
                const alertColor = alertLevel === "CRITICAL" ? "var(--risk-critical)" : alertLevel === "HIGH" ? "var(--risk-high)" : alertLevel === "ELEVATED" ? "var(--warning)" : "var(--accent)";
                const historyPoints = Array.isArray(scenarioForecast.history) ? scenarioForecast.history.slice(-24) : [];
                const forecastPoints = Array.isArray(scenarioForecast.forecast) ? scenarioForecast.forecast : [];
                const combined = [
                  ...historyPoints.map((point) => ({ timestamp: point.timestamp, score: point.score, type: "history" as const })),
                  ...forecastPoints.map((point) => ({ timestamp: point.timestamp, score: point.forecast_score, type: "forecast" as const })),
                ];
                return (
                  <>
                    {alertMsg && (
                      <div style={{ marginBottom: 12, padding: "8px 12px", borderRadius: 6, background: `${alertColor}18`, borderLeft: `3px solid ${alertColor}` }}>
                        <span style={{ fontSize: "0.78rem", fontWeight: 600, color: alertColor }}>{alertLevel}</span>
                        <span style={{ fontSize: "0.78rem", marginLeft: 8, color: "var(--ink-muted)" }}>{alertMsg}</span>
                      </div>
                    )}
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8, marginBottom: 14 }}>
                      {[
                        { label: "Trend", value: String(scenarioForecast.trend_direction ?? "—") },
                        { label: "Confidence", value: typeof scenarioForecast.forecast_confidence === "number" ? `${Math.round(scenarioForecast.forecast_confidence * 100)}%` : "—" },
                        { label: "Matching events", value: String(scenarioForecast.source_summary?.matching_events ?? "0") },
                        { label: "Active hours", value: String(scenarioForecast.source_summary?.hours_with_activity ?? "0") },
                      ].map((stat) => (
                        <div key={stat.label} className="metric-card" style={{ padding: "8px 10px" }}>
                          <div className="metric-label">{stat.label}</div>
                          <div className="metric-value" style={{ fontSize: "1rem" }}>{stat.value}</div>
                        </div>
                      ))}
                    </div>
                    {combined.length > 0 && (
                      <ResponsiveContainer width="100%" height={180}>
                        <LineChart data={combined} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(171,199,182,0.12)" />
                          <XAxis dataKey="timestamp" tick={{ fontSize: 9 }} tickFormatter={(value: string) => value.slice(11, 16)} />
                          <YAxis tick={{ fontSize: 9 }} domain={[0, 100]} />
                          <Tooltip
                            formatter={(value: number | string | undefined) => [`${Number(value ?? 0)}`, "Scenario pressure"]}
                            labelFormatter={(value: unknown) => typeof value === "string" ? new Date(value).toLocaleString() : String(value ?? "")}
                            labelStyle={{ fontSize: 10 }}
                            contentStyle={{ fontSize: 10 }}
                          />
                          <Legend wrapperStyle={{ fontSize: 10 }} />
                          <Line
                            type="monotone"
                            dataKey="score"
                            name="Scenario pressure"
                            stroke="#4cb5f5"
                            strokeWidth={2}
                            dot={(props: { cx?: number; cy?: number; payload?: { type?: string } }) => {
                              const { cx = 0, cy = 0, payload } = props;
                              return payload?.type === "forecast"
                                ? <circle key={`dot-${cx}-${cy}`} cx={cx} cy={cy} r={3} fill="#f0bf4c" stroke="none" />
                                : <circle key={`dot-${cx}-${cy}`} cx={cx} cy={cy} r={2} fill="#4cb5f5" stroke="none" />;
                            }}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    )}
                    <p className="muted" style={{ fontSize: "0.75rem", marginTop: 8 }}>
                      {scenarioForecast.scenario_explanation}
                    </p>
                    <p className="muted" style={{ fontSize: "0.75rem", marginTop: 6 }}>
                      {scenarioForecast.recommended_operator_posture}
                    </p>
                  </>
                );
              })()}
            </div>
          )}

          {/* ── Risk Forecast ─────────────────────────────────────────────── */}
          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>Platform risk forecast</h3>
              <span className="muted">
                {forecastLoading
                  ? "Loading…"
                  : forecast
                    ? `${String(forecast.trend_direction ?? "—")} · confidence grade ${String(forecast.confidence_grade ?? "—")}`
                    : "7-day threat risk projection"}
              </span>
            </div>

            {forecastLoading && (
              <div className="state-box"><Loader size={18} className="spin" /><p>Fetching forecast…</p></div>
            )}

            {!forecastLoading && !forecast && (
              <div className="state-box"><Brain size={22} /><p>No forecast data yet. Train the model first.</p></div>
            )}

            {!forecastLoading && forecast && (() => {
              const alertRec = asRecord(forecast.alert_recommendation);
              const alertLevel = String(alertRec.level ?? "");
              const alertMsg   = String(alertRec.message ?? "");
              const fPoints = Array.isArray(forecast.forecast) ? forecast.forecast as Array<Record<string, unknown>> : [];
              const hPoints = Array.isArray(forecast.history)  ? forecast.history  as Array<Record<string, unknown>> : [];
              const alertColor = alertLevel === "CRITICAL" ? "var(--risk-critical)" : alertLevel === "HIGH" ? "var(--risk-high)" : alertLevel === "MEDIUM" ? "var(--warning)" : "var(--accent)";
              const combined = [
                ...hPoints.slice(-14).map(p => ({ date: String(p.date ?? ""), score: asNumber(p.score) ?? asNumber(p.avg_score) ?? 0, type: "history" as const })),
                ...fPoints.map(p => ({ date: String(p.date ?? ""), score: asNumber(p.forecast_score) ?? 0, type: "forecast" as const })),
              ];
              return (
                <>
                  {alertMsg && (
                    <div style={{ marginBottom: 12, padding: "8px 12px", borderRadius: 6, background: alertColor + "18", borderLeft: `3px solid ${alertColor}` }}>
                      <span style={{ fontSize: "0.78rem", fontWeight: 600, color: alertColor }}>{alertLevel}</span>
                      <span style={{ fontSize: "0.78rem", marginLeft: 8, color: "var(--ink-muted)" }}>{alertMsg}</span>
                    </div>
                  )}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8, marginBottom: 14 }}>
                    {[
                      { label: "Trend",       value: String(forecast.trend_direction ?? "—") },
                      { label: "Net change",  value: typeof forecast.net_change_forecast === "number" ? (forecast.net_change_forecast > 0 ? `+${forecast.net_change_forecast}` : String(forecast.net_change_forecast)) : "—" },
                      { label: "Confidence",  value: typeof forecast.forecast_confidence === "number" ? `${Math.round(forecast.forecast_confidence * 100)}%` : "—" },
                      { label: "Volatility",  value: typeof forecast.volatility === "number" ? String(forecast.volatility) : "—" },
                    ].map(stat => (
                      <div key={stat.label} className="metric-card" style={{ padding: "8px 10px" }}>
                        <div className="metric-label">{stat.label}</div>
                        <div className="metric-value" style={{ fontSize: "1rem" }}>{stat.value}</div>
                      </div>
                    ))}
                  </div>
                  {combined.length > 0 && (
                    <ResponsiveContainer width="100%" height={160}>
                      <LineChart data={combined} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(171,199,182,0.12)" />
                        <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(v: string) => v.slice(5)} />
                        <YAxis tick={{ fontSize: 9 }} domain={[0, 100]} />
                        <Tooltip
                          formatter={(v: number | string | undefined, name: string | undefined) => [`${Number(v ?? 0)}`, name === "score" ? "Risk score" : (name ?? "Metric")]}
                          labelStyle={{ fontSize: 10 }}
                          contentStyle={{ fontSize: 10 }}
                        />
                        <Legend wrapperStyle={{ fontSize: 10 }} />
                        <Line
                          type="monotone"
                          dataKey="score"
                          name="Risk score"
                          stroke="#2fd67d"
                          strokeWidth={2}
                          dot={(props: { cx?: number; cy?: number; payload?: { type?: string } }) => {
                            const { cx = 0, cy = 0, payload } = props;
                            return payload?.type === "forecast"
                              ? <circle key={`dot-${cx}-${cy}`} cx={cx} cy={cy} r={3} fill="#f0bf4c" stroke="none" />
                              : <circle key={`dot-${cx}-${cy}`} cx={cx} cy={cy} r={2} fill="#2fd67d" stroke="none" />;
                          }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  )}
                  <p className="muted" style={{ fontSize: "0.7rem", marginTop: 6 }}>
                    Green = historical · Yellow dots = forecast horizon
                  </p>
                </>
              );
            })()}
          </div>

          <div className="gnn-ops-grid">
            <div className="panel workflow-stage-panel gnn-train-panel">
              <div className="panel-header">
                <h3><Zap size={14} /> Training controls</h3>
                <span className="muted gnn-train-sub">Bootstrap a usable demo state, then retrain only when the environment needs it</span>
              </div>
              <div className={`gnn-train-actions${trainMsg ? " has-msg" : ""}`}>
                <button type="button" className="btn-ghost" onClick={() => void handleSeed("cyber")} disabled={seedBusy || trainBusy}>
                  {seedBusy ? <Loader size={13} className="spin" /> : <Database size={13} />}
                  &nbsp;Bootstrap selected cyber demo
                </button>
                <button type="button" className="btn-ghost" onClick={() => void handleSeed("corruption")} disabled={seedBusy || trainBusy}>
                  {seedBusy ? <Loader size={13} className="spin" /> : <Database size={13} />}
                  &nbsp;Bootstrap Corruption Demo
                </button>
                <button type="button" className="btn-train-cyber" onClick={() => void handleTrain("cyber")} disabled={trainBusy || seedBusy}>
                  {trainBusy ? <Loader size={13} className="spin" /> : <Play size={13} />}
                  &nbsp;Train Cyber GNN
                </button>
                <button type="button" className="btn-train-corruption" onClick={() => void handleTrain("corruption")} disabled={trainBusy || seedBusy}>
                  {trainBusy ? <Loader size={13} className="spin" /> : <Play size={13} />}
                  &nbsp;Train Corruption GNN
                </button>
              </div>
              {trainMsg && (
                <div className={`gnn-train-msg${trainMsg.toLowerCase().includes("failed") || trainMsg.toLowerCase().includes("blocked") ? " error" : ""}`}>
                  {trainMsg}
                </div>
              )}
            </div>

            <div className="panel workflow-stage-panel">
              <div className="panel-header">
                <h3>Operational caveats</h3>
                <span className="muted">Read before retraining</span>
              </div>
              <div className="list">
                <div className="list-item">
                  <strong>Plain-language state</strong>
                  <p className="muted">{dataRealismStatement}</p>
                </div>
                <div className="list-item">
                  <strong>Graph coverage</strong>
                  <p className="muted">Nodes: {nodeCount ?? "—"} · Edges: {edgeCount ?? "—"} · Positives: {positiveCount ?? "—"}</p>
                </div>
                <div className="list-item">
                  <strong>Real-data gate</strong>
                  <p className="muted">
                    {latestRun?.real_data_gate_passed === false ? "The latest run did not naturally pass the real-data gate." : "No real-data gate failure was recorded on the latest run."}
                    {realRatio != null ? ` Real ratio ${Math.round(realRatio * 100)}%.` : ""}
                    {avgRealSignalRatio != null ? ` Avg per-node real signal ${Math.round(avgRealSignalRatio * 100)}%.` : ""}
                    {realGateOverrideApplied ? " Demo override was applied so the run completed despite low real-data coverage." : ""}
                  </p>
                </div>
                <div className="list-item">
                  <strong>Fairness state</strong>
                  <p className="muted">
                    {latestRun?.fairness?.fairness_flag ?? "No fairness result recorded"}
                    {latestRun?.fairness_blocked ? " · deployment blocked" : ""}
                    {fairnessGateOverrideApplied ? " · demo override allowed the run to complete" : ""}
                  </p>
                </div>
                <div className="list-item">
                  <strong>Analyst feedback</strong>
                  <p className="muted">
                    {feedbackOverrideCount != null ? `${feedbackOverrideCount} override labels applied.` : "No analyst feedback overrides recorded."}
                    {feedbackConsumedCount != null ? ` ${feedbackConsumedCount} newly consumed in training.` : ""}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {!healthGnnLoaded && (
            <div className="panel gnn-no-artifact-banner">
              <div className="gnn-no-artifact-inner">
                <AlertTriangle size={16} />
                <span>
                  No trained GNN artifact found. Use the training controls above to generate one before relying on the review queue.
                </span>
              </div>
            </div>
          )}

          <div className="panel workflow-stage-panel">
            <div className="panel-header">
              <h3>Model diagnostics</h3>
              <span className="muted">Deeper quality checks live here, not in the review queue</span>
            </div>
            <div className="gnn-metrics-toggle">
              <button
                type="button"
                className="chip ghost"
                onClick={() => setShowAllMetrics((v) => !v)}
              >
                {showAllMetrics ? "Hide detailed metrics ↑" : "Show detailed metrics ↓"}
              </button>
            </div>
            {showAllMetrics && (
              <div className="metric-grid">
                <div className="metric-card info">
                  <div className="metric-label">Precision</div>
                  <div className="metric-value">{precision != null ? precision.toFixed(3) : "—"}</div>
                  <div className="metric-sub">Positive precision</div>
                </div>
                <div className="metric-card info">
                  <div className="metric-label">Recall</div>
                  <div className="metric-value">{recall != null ? recall.toFixed(3) : "—"}</div>
                  <div className="metric-sub">Threat recall</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">ECE</div>
                  <div className="metric-value">{ece != null ? ece.toFixed(4) : "—"}</div>
                  <div className="metric-sub">Calibration error</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Brier Score</div>
                  <div className="metric-value">{brierScore != null ? brierScore.toFixed(4) : "—"}</div>
                  <div className="metric-sub">Probabilistic accuracy</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Graph nodes</div>
                  <div className="metric-value">{nodeCount ?? "—"}</div>
                  <div className="metric-sub">{predictionType}</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Edges</div>
                  <div className="metric-value">{edgeCount ?? "—"}</div>
                  <div className="metric-sub">Co-occurrence links</div>
                </div>
                <div className="metric-card warn">
                  <div className="metric-label">Positives</div>
                  <div className="metric-value">{positiveCount ?? "—"}</div>
                  <div className="metric-sub">Labelled threat nodes</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Feature dim</div>
                  <div className="metric-value">{featureDim ?? "—"}</div>
                  <div className="metric-sub">Input vector size</div>
                </div>
                <FairnessBadge fairness={latestRun?.fairness} blocked={latestRun?.fairness_blocked} />
              </div>
            )}

            <details className="collapsible-panel">
              <summary>
                Training loss curves
                <span className="muted">
                  {epochChartData.length > 0 ? `${epochChartData.length} epochs` : "No curves yet"}
                </span>
              </summary>
              {epochChartData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={epochChartData} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                    <XAxis
                      dataKey="epoch"
                      tick={{ fontSize: 10, fill: "var(--ink-muted)" }}
                      label={{ value: "Epoch", position: "insideBottomRight", offset: -4, fontSize: 10, fill: "var(--ink-muted)" }}
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: "var(--ink-muted)" }}
                      domain={["auto", "auto"]}
                      label={{ value: "Loss", angle: -90, position: "insideLeft", offset: 12, fontSize: 10, fill: "var(--ink-muted)" }}
                    />
                    <Tooltip
                      contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                      formatter={(value: number | string | undefined) => [typeof value === "number" ? value.toFixed(5) : String(value ?? "")]}
                    />
                    <Line type="monotone" dataKey="train" name="Train loss" stroke="var(--accent)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                    {epochValLosses.length > 0 && (
                      <Line type="monotone" dataKey="val" name="Val loss" stroke="var(--info)" strokeWidth={2} dot={false} strokeDasharray="5 3" activeDot={{ r: 4 }} />
                    )}
                    <Legend iconType="line" layout="horizontal" verticalAlign="top" align="right" wrapperStyle={{ fontSize: "0.75rem", opacity: 0.7 }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="state-box"><Zap size={24} /><p>Retrain the GNN to generate epoch-by-epoch loss curves here.</p></div>
              )}
            </details>
          </div>
        </div>
      )}
    </div>
  );
}
