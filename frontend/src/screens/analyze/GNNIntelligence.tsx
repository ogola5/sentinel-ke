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

const ANALYST_ID_STORAGE_KEY = "sentinel_analyst_id";

type Domain = "cyber" | "corruption";
type DomainWindowKey = "Wmid" | "Wcorruption";

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

function riskClass(score: number): string {
  if (score >= 0.8) return "critical";
  if (score >= 0.6) return "high";
  if (score >= 0.4) return "medium";
  return "low";
}

function scoreColor(score: number): string {
  if (score >= 0.8) return "var(--risk-critical)";
  if (score >= 0.6) return "var(--risk-high)";
  if (score >= 0.4) return "var(--risk-medium)";
  return "var(--risk-low)";
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
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [trainMsg, setTrainMsg] = useState<string | null>(null);
  const [trainBusy, setTrainBusy] = useState(false);
  const [seedBusy, setSeedBusy] = useState(false);
  const [feedbackBusyId, setFeedbackBusyId] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState("");

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

  const highRiskCount = sortedPredictions.filter((prediction) => prediction.score >= 0.7).length;
  const needsReviewCount = sortedPredictions.filter((prediction) => (prediction.uncertainty ?? 0) >= 0.5).length;
  const abstainedCount = sortedPredictions.filter((prediction) => prediction.abstained).length;

  return (
    <div>
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

      <div className="panel gnn-train-panel">
        <div className="panel-header">
          <h3><Zap size={14} /> Training Controls</h3>
          <span className="muted gnn-train-sub">Seed data then retrain — central admin only</span>
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

      {feedbackError && (
        <div className="panel" style={{ marginBottom: 16, borderColor: "rgba(255,140,66,.35)" }}>
          <div style={{ color: "var(--risk-high)", fontSize: "0.85rem" }}>{feedbackError}</div>
        </div>
      )}

      {!healthGnnLoaded && (
        <div className="panel gnn-no-artifact-banner">
          <div className="gnn-no-artifact-inner">
            <AlertTriangle size={16} />
            <span>
              No trained GNN artifact found. Use the seeding and training controls above to generate a model.
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
        <div className="metric-card accent">
          <div className="metric-label">F1 Score</div>
          <div className="metric-value">{f1 != null ? f1.toFixed(3) : "—"}</div>
          <div className="metric-sub">Harmonic mean of precision and recall</div>
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
        <div className="metric-card">
          <div className="metric-label">High-risk</div>
          <div className={`metric-value${highRiskCount > 0 ? " gnn-metric-danger" : ""}`}>{highRiskCount}</div>
          <div className="metric-sub">Score ≥ 0.70</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Uncertain</div>
          <div className={`metric-value${needsReviewCount > 0 ? " gnn-metric-warn" : ""}`}>{needsReviewCount}</div>
          <div className="metric-sub">Need analyst review</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Abstained</div>
          <div className="metric-value">{abstainedCount}</div>
          <div className="metric-sub">High uncertainty skipped</div>
        </div>
        <FairnessBadge fairness={latestRun?.fairness} blocked={latestRun?.fairness_blocked} />
      </div>

      <div className="gnn-charts-grid">
        <div className="panel">
          <div className="panel-header">
            <h3>Model Performance</h3>
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
            <div className="state-box"><Brain size={28} /><p>No model metrics yet</p></div>
          )}
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Training History</h3>
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
            <div className="state-box"><Zap size={24} /><p>No training history yet</p></div>
          )}
        </div>
      </div>

      <div className="panel gnn-loss-panel">
        <div className="panel-header">
          <h3>Training Loss Curves</h3>
          <span className="muted">
            {epochChartData.length > 0
              ? `${epochChartData.length} epochs · ${latestRun?.model_version ?? "latest"}`
              : "train → retrain to generate curves"}
          </span>
        </div>
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
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Entity Predictions</h3>
          <span className="muted">
            {sortedPredictions.length} predictions · {activeDomain === "cyber" ? "Cyber / Wmid" : "Corruption / Wcorruption"}
            {needsReviewCount > 0 && <span className="gnn-uncertain-badge">&nbsp;· {needsReviewCount} need review</span>}
          </span>
        </div>
        {loading ? (
          <div className="state-box"><Loader size={22} /><p>Loading predictions…</p></div>
        ) : sortedPredictions.length === 0 ? (
          <div className="state-box"><Brain size={28} /><p>No predictions yet — run the inference consumer or train the GNN.</p></div>
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
                              style={{ width: `${prediction.score * 100}%`, background: scoreColor(prediction.score) }}
                            />
                          </div>
                          <span className="gnn-score-label" style={{ color: scoreColor(prediction.score) }}>
                            {prediction.score.toFixed(2)}
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
                      <td className="gnn-cell-sm">{prediction.confidence != null ? prediction.confidence.toFixed(2) : "—"}</td>
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
                          <span className={`risk-badge ${riskClass(prediction.score)}`}>{riskClass(prediction.score)}</span>
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
  );
}
