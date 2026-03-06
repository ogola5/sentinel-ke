import { useEffect, useState, useCallback } from "react";
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
import { Brain, RefreshCw, Loader, AlertTriangle, Zap, Play, Database, CheckCircle, XCircle, HelpCircle } from "lucide-react";
import { fetchAIPredictions, fetchGNNTrainingRuns, triggerGNNTrain, seedDemoData, submitFeedback } from "../../api/ai";
import type { AIPrediction, FairnessMetrics, GNNTrainingRun } from "../../types/ai";

type FeedbackState = "confirmed" | "false_positive" | "uncertain";
type Domain = "cyber" | "corruption";
const DOMAIN_WINDOW: Record<Domain, string> = { cyber: "Wmid", corruption: "Wcorruption" };

const FAIRNESS_COLORS: Record<"PASS" | "WARN" | "FAIL", string> = {
  PASS: "#30d158",
  WARN: "#ff9f0a",
  FAIL: "#ff2d55",
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
          ⚠ Deployment blocked by fairness policy
        </div>
      )}
    </div>
  );
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

function shortKey(key: string): string {
  return key.length > 14 ? `${key.slice(0, 6)}…${key.slice(-6)}` : key;
}

interface Props {
  healthGnnLoaded: boolean;
  healthModelVersion: string | null;
  healthGnnMetrics: Record<string, unknown>;
}

export default function GNNIntelligence({ healthGnnLoaded, healthModelVersion, healthGnnMetrics }: Props) {
  const [runs, setRuns] = useState<GNNTrainingRun[]>([]);
  const [predictions, setPredictions] = useState<AIPrediction[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [trainMsg, setTrainMsg] = useState<string | null>(null);
  const [trainBusy, setTrainBusy] = useState(false);
  const [seedBusy, setSeedBusy] = useState(false);
  const [activeDomain, setActiveDomain] = useState<Domain>("cyber");
  const [feedbackState, setFeedbackState] = useState<Record<string, FeedbackState>>({});
  const [feedbackBusy, setFeedbackBusy] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setSyncing(true);
    const wk = DOMAIN_WINDOW[activeDomain];
    const [r, p] = await Promise.all([fetchGNNTrainingRuns(12), fetchAIPredictions(50, wk)]);
    setRuns(r);
    setPredictions(p);
    setLoading(false);
    setSyncing(false);
  }, [activeDomain]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSeed = async (domain: "cyber" | "corruption") => {
    setSeedBusy(true);
    setTrainMsg(null);
    try {
      const r = await seedDemoData(domain);
      setTrainMsg(`Seeding started: ${r.message}`);
    } catch (e: unknown) {
      setTrainMsg(`Seed failed: ${String(e)}`);
    } finally {
      setSeedBusy(false);
    }
  };

  const handleTrain = async (domain: "cyber" | "corruption") => {
    setTrainBusy(true);
    setTrainMsg(null);
    try {
      const r = await triggerGNNTrain(domain);
      setTrainMsg(`Training accepted (${r.model_version}): ${r.message}`);
    } catch (e: unknown) {
      setTrainMsg(`Train failed: ${String(e)}`);
    } finally {
      setTrainBusy(false);
    }
  };

  const handleFeedback = async (pred: AIPrediction, label: FeedbackState) => {
    setFeedbackBusy((p) => ({ ...p, [pred.id]: true }));
    try {
      const numLabel: 0 | 1 | 2 = label === "confirmed" ? 1 : label === "false_positive" ? 0 : 2;
      await submitFeedback(pred.id, numLabel, "analyst");
      setFeedbackState((p) => ({ ...p, [pred.id]: label }));
    } catch {
      // silently ignore — prediction row stays un-labelled
    } finally {
      setFeedbackBusy((p) => ({ ...p, [pred.id]: false }));
    }
  };

  const latestRun = runs[0] ?? null;

  const auc = latestRun?.auc ?? (healthGnnMetrics.auc as number | null) ?? null;
  const precision = latestRun?.precision ?? (healthGnnMetrics.precision as number | null) ?? null;
  const f1 = latestRun?.f1 ?? (healthGnnMetrics.f1 as number | null) ?? null;
  const recall = latestRun?.recall ?? (healthGnnMetrics.recall as number | null) ?? null;
  const ece = (latestRun?.metrics?.calibration_ece ?? healthGnnMetrics.calibration_ece) as number | null;
  const brierScore = (latestRun?.metrics?.brier_score ?? healthGnnMetrics.brier_score) as number | null;
  const nodeCount = latestRun?.node_count ?? (healthGnnMetrics.node_count as number | null) ?? null;
  const edgeCount = latestRun?.edge_count ?? (healthGnnMetrics.edge_count as number | null) ?? null;
  const positiveCount = latestRun?.positive_count ?? (healthGnnMetrics.positive_count as number | null) ?? null;
  const featureDim = latestRun?.feature_dim ?? (healthGnnMetrics.feature_dim as number | null) ?? null;
  const modelVersion = latestRun?.model_version ?? healthModelVersion ?? "—";
  const predictionType = latestRun?.prediction_type ?? (healthGnnMetrics.prediction_type as string | null) ?? "—";

  // Epoch loss curve data from metrics_json
  const epochTrainLosses = latestRun?.metrics?.epoch_train_losses ?? [];
  const epochValLosses   = latestRun?.metrics?.epoch_val_losses   ?? [];
  const epochChartData   = epochTrainLosses.map((tl, i) => ({
    epoch: i + 1,
    train: Math.round(tl * 10000) / 10000,
    val:   epochValLosses[i] != null ? Math.round(epochValLosses[i] * 10000) / 10000 : undefined,
  }));

  const radialData = [
    { name: "AUC", value: Math.round((auc ?? 0) * 100), fill: "var(--accent)" },
    { name: "Precision", value: Math.round((precision ?? 0) * 100), fill: "var(--info)" },
  ];

  const runsChartData = runs
    .slice()
    .reverse()
    .map((r, i) => ({
      idx: i + 1,
      auc: r.auc != null ? Math.round(r.auc * 1000) / 10 : null,
      precision: r.precision != null ? Math.round(r.precision * 1000) / 10 : null,
      label: r.model_version,
    }));

  const abstainedCount = predictions.filter((p) => p.abstained).length;
  const highRiskCount = predictions.filter((p) => p.score >= 0.7).length;
  const highUncertainCount = predictions.filter((p) => (p.uncertainty ?? 0) >= 0.5).length;

  return (
    <div>
      <div className="screen-header">
        <h2>
          <Brain size={20} color="var(--accent)" />
          GNN Intelligence Hub
          <span className="subtitle">— Graph Neural Network · MC-Dropout uncertainty</span>
        </h2>
        <div className="screen-header-actions">
          {/* Domain tabs */}
          <div className="gnn-domain-tabs">
            <button
              type="button"
              className={activeDomain === "cyber" ? "gnn-domain-tab active" : "gnn-domain-tab"}
              onClick={() => setActiveDomain("cyber")}
            >
              Cyber (Wmid)
            </button>
            <button
              type="button"
              className={activeDomain === "corruption" ? "gnn-domain-tab active" : "gnn-domain-tab"}
              onClick={() => setActiveDomain("corruption")}
            >
              Corruption (Wcorruption)
            </button>
          </div>
          <button type="button" className="btn-ghost" onClick={() => void load()} disabled={syncing}>
            {syncing ? <Loader size={14} className="spin" /> : <RefreshCw size={14} />}
            &nbsp;Refresh
          </button>
        </div>
      </div>

      {/* Train / Seed action panel */}
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

      {/* Model status banner */}
      {!healthGnnLoaded && (
        <div className="panel gnn-no-artifact-banner">
          <div className="gnn-no-artifact-inner">
            <AlertTriangle size={16} />
            <span>
              No trained GNN artifact found. Use &ldquo;Seed Cyber Data&rdquo; then &ldquo;Train Cyber GNN&rdquo; above to generate a model.
            </span>
          </div>
        </div>
      )}

      {/* Metric cards — now includes F1, Recall, ECE, Brier */}
      <div className="metric-grid">
        <div className="metric-card accent">
          <div className="metric-label">AUC</div>
          <div className="metric-value">{auc != null ? auc.toFixed(3) : "—"}</div>
          <div className="metric-sub">Area under ROC curve</div>
        </div>
        <div className="metric-card info">
          <div className="metric-label">Precision</div>
          <div className="metric-value">{precision != null ? precision.toFixed(3) : "—"}</div>
          <div className="metric-sub">TP / (TP + FP)</div>
        </div>
        <div className="metric-card info">
          <div className="metric-label">Recall</div>
          <div className="metric-value">{recall != null ? recall.toFixed(3) : "—"}</div>
          <div className="metric-sub">TP / (TP + FN)</div>
        </div>
        <div className="metric-card accent">
          <div className="metric-label">F1 Score</div>
          <div className="metric-value">{f1 != null ? f1.toFixed(3) : "—"}</div>
          <div className="metric-sub">Harmonic mean P/R</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">ECE</div>
          <div className="metric-value">{ece != null ? ece.toFixed(4) : "—"}</div>
          <div className="metric-sub">Calibration error ↓</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Brier Score</div>
          <div className="metric-value">{brierScore != null ? brierScore.toFixed(4) : "—"}</div>
          <div className="metric-sub">Probabilistic accuracy ↓</div>
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
          <div className={`metric-value${highRiskCount > 0 ? " gnn-metric-danger" : ""}`}>
            {highRiskCount}
          </div>
          <div className="metric-sub">Score ≥ 0.70</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Uncertain</div>
          <div className={`metric-value${highUncertainCount > 0 ? " gnn-metric-warn" : ""}`}>
            {highUncertainCount}
          </div>
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
        {/* Radial performance gauge */}
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

        {/* Training run history */}
        <div className="panel">
          <div className="panel-header">
            <h3>Training History</h3>
            <span className="muted">{runs.length} runs</span>
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
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="state-box"><Zap size={24} /><p>No training history yet</p></div>
          )}
        </div>
      </div>

      {/* Epoch loss curves */}
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
              <XAxis dataKey="epoch" tick={{ fontSize: 10, fill: "var(--ink-muted)" }} label={{ value: "Epoch", position: "insideBottomRight", offset: -4, fontSize: 10, fill: "var(--ink-muted)" }} />
              <YAxis tick={{ fontSize: 10, fill: "var(--ink-muted)" }} domain={["auto", "auto"]} label={{ value: "Loss", angle: -90, position: "insideLeft", offset: 12, fontSize: 10, fill: "var(--ink-muted)" }} />
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

      {/* Predictions table — with uncertainty bar + analyst feedback */}
      <div className="panel">
        <div className="panel-header">
          <h3>Entity Predictions</h3>
          <span className="muted">
            {predictions.length} predictions · {activeDomain === "cyber" ? "Cyber / Wmid" : "Corruption / Wcorruption"}
            {highUncertainCount > 0 && <span className="gnn-uncertain-badge">&nbsp;· {highUncertainCount} need review</span>}
          </span>
        </div>
        {loading ? (
          <div className="state-box"><Loader size={22} /><p>Loading predictions…</p></div>
        ) : predictions.length === 0 ? (
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
                {predictions.map((p) => {
                  const u = p.uncertainty ?? 0;
                  const isHighUncertain = u >= 0.5;
                  const fb = feedbackState[p.id];
                  const busy = feedbackBusy[p.id] ?? false;
                  const uColor = u >= 0.75 ? "var(--risk-critical)" : u >= 0.5 ? "var(--warning)" : "var(--risk-low)";
                  return (
                    <tr key={p.id} className={isHighUncertain ? "gnn-row-uncertain" : undefined}>
                      <td>
                        <span className="mono gnn-entity-key">{shortKey(p.entity_key)}</span>
                        <span className="muted gnn-pred-type">{p.prediction_type}</span>
                      </td>
                      <td>
                        <div className="score-bar-wrap">
                          <div className="score-bar-track">
                            <div className="score-bar-fill" style={{ width: `${p.score * 100}%`, background: scoreColor(p.score) }} />
                          </div>
                          <span className="gnn-score-label" style={{ color: scoreColor(p.score) }}>{p.score.toFixed(2)}</span>
                        </div>
                      </td>
                      <td>
                        <div className="score-bar-wrap">
                          <div className="score-bar-track">
                            <div className="score-bar-fill" style={{ width: `${u * 100}%`, background: uColor }} />
                          </div>
                          <span className="gnn-score-label" style={{ color: uColor }}>{u.toFixed(3)}</span>
                        </div>
                      </td>
                      <td className="gnn-cell-sm">{p.confidence != null ? p.confidence.toFixed(2) : "—"}</td>
                      <td>
                        {p.kill_chain_stage
                          ? <span className="risk-badge info">{p.kill_chain_stage}</span>
                          : <span className="muted">—</span>}
                      </td>
                      <td>
                        {p.top_feature
                          ? <span className="mono gnn-top-feature">{p.top_feature}</span>
                          : <span className="muted">—</span>}
                      </td>
                      <td>
                        {p.abstained
                          ? <span className="risk-badge medium">Abstained</span>
                          : <span className={`risk-badge ${riskClass(p.score)}`}>{riskClass(p.score)}</span>}
                      </td>
                      <td>
                        {fb ? (
                          <span className={`gnn-feedback-done ${fb}`}>
                            {fb === "confirmed" ? "✓ Threat" : fb === "false_positive" ? "✗ FP" : "? Uncertain"}
                          </span>
                        ) : (
                          <div className="gnn-feedback-btns">
                            <button
                              type="button"
                              className="gnn-fb-btn confirm"
                              title="Confirm threat"
                              disabled={busy}
                              onClick={() => void handleFeedback(p, "confirmed")}
                            >
                              {busy ? <Loader size={11} className="spin" /> : <CheckCircle size={13} />}
                            </button>
                            <button
                              type="button"
                              className="gnn-fb-btn reject"
                              title="Mark false positive"
                              disabled={busy}
                              onClick={() => void handleFeedback(p, "false_positive")}
                            >
                              {busy ? <Loader size={11} className="spin" /> : <XCircle size={13} />}
                            </button>
                            <button
                              type="button"
                              className="gnn-fb-btn uncertain"
                              title="Mark uncertain"
                              disabled={busy}
                              onClick={() => void handleFeedback(p, "uncertain")}
                            >
                              {busy ? <Loader size={11} className="spin" /> : <HelpCircle size={13} />}
                            </button>
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
