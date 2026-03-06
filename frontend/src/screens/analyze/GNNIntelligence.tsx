import { useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  RadialBarChart,
  RadialBar,
  Legend,
} from "recharts";
import { Brain, Check, HelpCircle, Loader, RefreshCw, TriangleAlert, X } from "lucide-react";
import { fetchAIFeedback, fetchAIPredictions, fetchGNNTrainingRuns, submitAIFeedback } from "../../api/ai";
import type { AIFeedback, AIPrediction, GNNTrainingRun } from "../../types/ai";

const ANALYST_ID_STORAGE_KEY = "sentinel_analyst_id";

const DOMAIN_OPTIONS = [
  { id: "Wmid", label: "Cyber (Wmid)" },
  { id: "Wcorruption", label: "Corruption (Wcorruption)" },
] as const;

const FEEDBACK_OPTIONS = [
  { label: "Confirm threat", short: "Confirm", value: 1, icon: Check },
  { label: "False positive", short: "False+", value: 0, icon: X },
  { label: "Uncertain", short: "Uncertain", value: 2, icon: HelpCircle },
] as const;

type DomainWindowKey = (typeof DOMAIN_OPTIONS)[number]["id"];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asNumber(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
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

function feedbackTone(label: number): string {
  if (label === 1) return "critical";
  if (label === 0) return "low";
  return "medium";
}

function feedbackLabelText(label: number): string {
  return FEEDBACK_OPTIONS.find((option) => option.value === label)?.label ?? "Queued";
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
  const [activeWindowKey, setActiveWindowKey] = useState<DomainWindowKey>("Wmid");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [feedbackBusyId, setFeedbackBusyId] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState("");

  const analystId = useMemo(() => loadAnalystId(), []);

  const load = async (windowKey: DomainWindowKey) => {
    setSyncing(true);
    setFeedbackError("");
    try {
      const [runRows, predictionRows, feedbackRows] = await Promise.all([
        fetchGNNTrainingRuns(24),
        fetchAIPredictions(50, windowKey),
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
  };

  useEffect(() => {
    void load(activeWindowKey);
  }, [activeWindowKey, analystId]);

  const filteredRuns = useMemo(
    () => runs.filter((run) => (run.window_key ?? "") === activeWindowKey),
    [runs, activeWindowKey],
  );

  const latestRun = filteredRuns[0] ?? runs[0] ?? null;
  const latestMetrics = asRecord(latestRun?.metrics);

  const auc = latestRun?.auc ?? asNumber(healthGnnMetrics.auc);
  const precision = latestRun?.precision ?? asNumber(healthGnnMetrics.precision);
  const recall = latestRun?.recall ?? asNumber(latestMetrics.recall);
  const f1 = latestRun?.f1 ?? asNumber(latestMetrics.f1);
  const ece = asNumber(latestMetrics.ece);
  const brier = asNumber(latestMetrics.brier);
  const nodeCount = latestRun?.node_count ?? asNumber(healthGnnMetrics.node_count);
  const edgeCount = latestRun?.edge_count ?? asNumber(healthGnnMetrics.edge_count);
  const positiveCount = latestRun?.positive_count ?? asNumber(healthGnnMetrics.positive_count);
  const featureDim = latestRun?.feature_dim ?? asNumber(healthGnnMetrics.feature_dim);
  const modelVersion = latestRun?.model_version ?? healthModelVersion ?? "—";
  const predictionType =
    latestRun?.prediction_type ?? (typeof healthGnnMetrics.prediction_type === "string" ? healthGnnMetrics.prediction_type : "—");

  const radialData = [
    { name: "AUC", value: clampPercent(auc), fill: "var(--accent)" },
    { name: "Precision", value: clampPercent(precision), fill: "var(--info)" },
    { name: "Recall", value: clampPercent(recall), fill: "var(--warning)" },
  ];

  const runsChartData = filteredRuns
    .slice()
    .reverse()
    .map((run, idx) => ({
      idx: idx + 1,
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

  const handleFeedback = async (predictionId: string, feedbackLabel: number) => {
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

  return (
    <div>
      <div className="screen-header">
        <h2>
          <Brain size={20} color="var(--accent)" />
          GNN Intelligence Hub
          <span className="subtitle">— network analysis model · active learning review queue</span>
        </h2>
        <div className="chip-row" style={{ gap: 8 }}>
          {DOMAIN_OPTIONS.map((domain) => (
            <button
              key={domain.id}
              type="button"
              className={activeWindowKey === domain.id ? "chip active" : "chip ghost"}
              onClick={() => setActiveWindowKey(domain.id)}
            >
              {domain.label}
            </button>
          ))}
          <button className="btn-ghost" onClick={() => void load(activeWindowKey)} disabled={syncing}>
            {syncing ? <Loader size={14} className="spin" /> : <RefreshCw size={14} />}
            &nbsp;Refresh
          </button>
        </div>
      </div>

      {!healthGnnLoaded && (
        <div className="panel" style={{ marginBottom: 16, borderColor: "rgba(255,209,71,.35)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--warning)" }}>
            <TriangleAlert size={16} />
            <span style={{ fontSize: "0.85rem" }}>
              No trained GNN artifact found. Run the training worker to generate a model.
            </span>
          </div>
        </div>
      )}

      <div className="metric-grid">
        <div className="metric-card accent">
          <div className="metric-label">AUC</div>
          <div className="metric-value">{auc != null ? auc.toFixed(3) : "—"}</div>
          <div className="metric-sub">Area under ROC</div>
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
          <div className="metric-sub">Balanced detection score</div>
        </div>
        <div className="metric-card warn">
          <div className="metric-label">ECE</div>
          <div className="metric-value">{ece != null ? ece.toFixed(3) : "—"}</div>
          <div className="metric-sub">Calibration error</div>
        </div>
        <div className="metric-card warn">
          <div className="metric-label">Brier Score</div>
          <div className="metric-value">{brier != null ? brier.toFixed(3) : "—"}</div>
          <div className="metric-sub">Probabilistic loss</div>
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
          <div className="metric-sub">Labeled threat nodes</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Feature dim</div>
          <div className="metric-value">{featureDim ?? "—"}</div>
          <div className="metric-sub">Input vector size</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">High-risk preds</div>
          <div className="metric-value" style={{ color: highRiskCount > 0 ? "var(--risk-high)" : undefined }}>
            {highRiskCount}
          </div>
          <div className="metric-sub">Score ≥ 0.70</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Need review</div>
          <div className="metric-value" style={{ color: needsReviewCount > 0 ? "var(--warning)" : undefined }}>
            {needsReviewCount}
          </div>
          <div className="metric-sub">Uncertainty ≥ 0.50</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
        <div className="panel">
          <div className="panel-header">
            <h3>Model Performance</h3>
            <span className="muted">{modelVersion}</span>
          </div>
          {auc != null ? (
            <ResponsiveContainer width="100%" height={220}>
              <RadialBarChart
                cx="50%"
                cy="50%"
                innerRadius={40}
                outerRadius={90}
                data={radialData}
                startAngle={90}
                endAngle={-270}
              >
                <RadialBar dataKey="value" cornerRadius={6} background={{ fill: "rgba(31,63,46,0.35)" }} />
                <Legend
                  iconType="circle"
                  layout="horizontal"
                  verticalAlign="bottom"
                  wrapperStyle={{ fontSize: "0.75rem", opacity: 0.7 }}
                />
                <Tooltip
                  formatter={(value: number | string | undefined) => [`${Number(value ?? 0).toFixed(1)}%`]}
                  contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8 }}
                />
              </RadialBarChart>
            </ResponsiveContainer>
          ) : (
            <div className="state-box">
              <Brain size={28} />
              <p>No model metrics yet</p>
            </div>
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
            <div className="state-box">
              <Brain size={24} />
              <p>No training history for {activeWindowKey}</p>
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Entity Predictions</h3>
          <span className="muted">
            {sortedPredictions.length} predictions · {needsReviewCount} need review
          </span>
        </div>
        {feedbackError && <p style={{ color: "var(--danger)", marginTop: 0 }}>{feedbackError}</p>}
        {loading ? (
          <div className="state-box">
            <Loader size={22} />
            <p>Loading predictions…</p>
          </div>
        ) : sortedPredictions.length === 0 ? (
          <div className="state-box">
            <Brain size={28} />
            <p>No predictions yet. Run inference consumer to generate scores.</p>
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Entity Key</th>
                  <th>Type</th>
                  <th>Risk Score</th>
                  <th>Confidence</th>
                  <th>Uncertainty</th>
                  <th>Kill-Chain Stage</th>
                  <th>Status</th>
                  <th>Analyst Feedback</th>
                </tr>
              </thead>
              <tbody>
                {sortedPredictions.map((prediction) => {
                  const uncertainty = prediction.uncertainty ?? 0;
                  const requiresReview = uncertainty >= 0.5;
                  const submittedFeedback = feedbackByPrediction[prediction.id] ?? null;

                  return (
                    <tr
                      key={prediction.id}
                      style={
                        requiresReview
                          ? {
                              borderLeft: `4px solid ${uncertaintyColor(uncertainty)}`,
                              background: "rgba(255, 184, 77, 0.08)",
                            }
                          : undefined
                      }
                    >
                      <td>
                        <span className="mono" style={{ fontSize: "0.78rem" }}>
                          {shortKey(prediction.entity_key)}
                        </span>
                      </td>
                      <td>
                        <span className="muted" style={{ fontSize: "0.78rem" }}>
                          {prediction.entity_type ?? prediction.prediction_type}
                        </span>
                      </td>
                      <td>
                        <div className="score-bar-wrap">
                          <div className="score-bar-track">
                            <div
                              className="score-bar-fill"
                              style={{ width: `${prediction.score * 100}%`, background: scoreColor(prediction.score) }}
                            />
                          </div>
                          <span style={{ fontSize: "0.78rem", color: scoreColor(prediction.score), minWidth: 36 }}>
                            {prediction.score.toFixed(2)}
                          </span>
                        </div>
                      </td>
                      <td style={{ fontSize: "0.78rem" }}>
                        {prediction.confidence != null ? prediction.confidence.toFixed(2) : "—"}
                      </td>
                      <td>
                        <div className="score-bar-wrap">
                          <div className="score-bar-track">
                            <div
                              className="score-bar-fill"
                              style={{ width: `${clampPercent(uncertainty)}%`, background: uncertaintyColor(uncertainty) }}
                            />
                          </div>
                          <span style={{ fontSize: "0.78rem", color: uncertaintyColor(uncertainty), minWidth: 44 }}>
                            {uncertainty.toFixed(2)}
                          </span>
                        </div>
                      </td>
                      <td>
                        {prediction.kill_chain_stage ? (
                          <span className="risk-badge info">{prediction.kill_chain_stage}</span>
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
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                            {FEEDBACK_OPTIONS.map((option) => {
                              const Icon = option.icon;
                              const active = submittedFeedback?.feedback_label === option.value;
                              return (
                                <button
                                  key={option.value}
                                  type="button"
                                  className={active ? "chip active" : "chip ghost"}
                                  style={{ fontSize: "0.72rem", paddingInline: 8, opacity: feedbackBusyId === prediction.id ? 0.7 : 1 }}
                                  disabled={feedbackBusyId === prediction.id}
                                  title={option.label}
                                  onClick={() => void handleFeedback(prediction.id, option.value)}
                                >
                                  {feedbackBusyId === prediction.id && active ? (
                                    <Loader size={12} className="spin" />
                                  ) : (
                                    <Icon size={12} />
                                  )}
                                  &nbsp;{option.short}
                                </button>
                              );
                            })}
                          </div>
                          {submittedFeedback && (
                            <span className={`risk-badge ${feedbackTone(submittedFeedback.feedback_label)}`}>
                              {feedbackLabelText(submittedFeedback.feedback_label)} · {submittedFeedback.status}
                            </span>
                          )}
                        </div>
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
