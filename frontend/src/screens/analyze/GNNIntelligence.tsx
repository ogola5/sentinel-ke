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

import {
  fetchAIFeedback,
  fetchAIPredictions,
  fetchGNNTrainingRuns,
  seedDemoData,
  submitAIFeedback,
  triggerGNNTrain,
} from "../../api/ai";
import type { AIFeedback, AIPrediction, FairnessMetrics, GNNTrainingRun } from "../../types/ai";
import { clampRiskPercent, formatRiskScore, isHighRisk, riskColor, riskSeverityLabel } from "../../utils/risk";

const ANALYST_ID_STORAGE_KEY = "sentinel_analyst_id";

type Domain = "cyber" | "corruption";
type DomainWindowKey = "Wmid" | "Wcorruption";
type GNNView = "overview" | "review" | "ops";

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

const GNN_VIEW_CONTENT: Record<GNNView, {
  kicker: string;
  title: string;
  summary: string;
  steps: [string, string, string];
}> = {
  overview: {
    kicker: "Model snapshot",
    title: "Start with whether the model is trustworthy enough to use right now.",
    summary: "This view keeps the current model state readable before you move into queue work or retraining.",
    steps: [
      "Check the artifact and headline metrics.",
      "Read the latest run trend before trusting the queue.",
      "Move to Review Queue only after the model state is clear.",
    ],
  },
  review: {
    kicker: "Review queue",
    title: "Work the analyst queue, not the training dashboard.",
    summary: "This view is for entity-level review only: uncertain rows first, then high-risk rows, then analyst feedback.",
    steps: [
      "Start with rows marked uncertain or high risk.",
      "Read the top driver and kill-chain stage before labeling.",
      "Submit analyst feedback directly from the queue.",
    ],
  },
  ops: {
    kicker: "Model operations",
    title: "Use this view only when you need to seed, train, or inspect deeper model caveats.",
    summary: "This keeps retraining controls and diagnostics separate from day-to-day analyst review.",
    steps: [
      "Seed only when the environment needs fresh demo data.",
      "Run training for the selected domain and wait for completion.",
      "Open deeper diagnostics only when you need fairness or loss-curve detail.",
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
  const [showAllMetrics, setShowAllMetrics] = useState(false);

  const analystId = useMemo(() => loadAnalystId(), []);
  const activeWindowKey = DOMAIN_OPTIONS.find((option) => option.domain === activeDomain)?.windowKey ?? "Wmid";

  const load = useCallback(async () => {
    setSyncing(true);
    setFeedbackError("");
    try {
      const [runRows, predictionRows, feedbackRows] = await Promise.all([
        fetchGNNTrainingRuns(24),
        fetchAIPredictions(50, activeWindowKey),
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
    } finally {
      setLoading(false);
      setSyncing(false);
    }
  }, [activeWindowKey, analystId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSeed = async (domain: Domain) => {
    setSeedBusy(true);
    setTrainMsg(null);
    try {
      const response = await seedDemoData(domain);
      setTrainMsg(`Seeding started: ${response.message}`);
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
      const response = await triggerGNNTrain(domain);
      setTrainMsg(`Training accepted (${response.model_version}): ${response.message}`);
    } catch (error: unknown) {
      setTrainMsg(`Train failed: ${String(error)}`);
    } finally {
      setTrainBusy(false);
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

  return (
    <div className="screen">
      <div className="screen-header">
        <h2>
          <Brain size={20} color="var(--accent)" />
          GNN Intelligence Hub
          <span className="subtitle">— network analysis model · active learning review queue</span>
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

      <div className="panel workflow-guide-panel" style={{ background: "rgba(var(--accent-rgb), 0.07)", borderColor: "rgba(var(--accent-rgb), 0.24)" }}>
        <p className="workflow-stage-kicker">{viewContent.kicker}</p>
        <div className="detail-grid">
          <div>
            <strong>{viewContent.title}</strong>
            <p className="workflow-stage-copy" style={{ marginTop: 6 }}>{viewContent.summary}</p>
          </div>
          <div>
            <strong>Best flow</strong>
            <ul className="inspector-compact-list" style={{ marginTop: 8 }}>
              {viewContent.steps.map((step) => <li key={step}>{step}</li>)}
            </ul>
          </div>
        </div>
      </div>

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
          <div className="gnn-ops-grid">
            <div className="panel workflow-stage-panel gnn-train-panel">
              <div className="panel-header">
                <h3><Zap size={14} /> Training controls</h3>
                <span className="muted gnn-train-sub">Seed data then retrain when the environment needs it</span>
              </div>
              <div className={`gnn-train-actions${trainMsg ? " has-msg" : ""}`}>
                <button type="button" className="btn-ghost" onClick={() => void handleSeed("cyber")} disabled={seedBusy || trainBusy}>
                  {seedBusy ? <Loader size={13} className="spin" /> : <Database size={13} />}
                  &nbsp;Seed Cyber Data
                </button>
                <button type="button" className="btn-ghost" onClick={() => void handleSeed("corruption")} disabled={seedBusy || trainBusy}>
                  {seedBusy ? <Loader size={13} className="spin" /> : <Database size={13} />}
                  &nbsp;Seed Corruption Data
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
                <div className={`gnn-train-msg${trainMsg.includes("failed") ? " error" : ""}`}>
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
                  <strong>Graph coverage</strong>
                  <p className="muted">Nodes: {nodeCount ?? "—"} · Edges: {edgeCount ?? "—"} · Positives: {positiveCount ?? "—"}</p>
                </div>
                <div className="list-item">
                  <strong>Real-data gate</strong>
                  <p className="muted">
                    {latestRun?.real_data_gate_passed === false ? "Failed for the latest run." : "No failure recorded on the latest run."}
                    {realRatio != null ? ` Real ratio ${Math.round(realRatio * 100)}%.` : ""}
                    {avgRealSignalRatio != null ? ` Avg per-node real signal ${Math.round(avgRealSignalRatio * 100)}%.` : ""}
                  </p>
                </div>
                <div className="list-item">
                  <strong>Fairness state</strong>
                  <p className="muted">
                    {latestRun?.fairness?.fairness_flag ?? "No fairness result recorded"}
                    {latestRun?.fairness_blocked ? " · deployment blocked" : ""}
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
