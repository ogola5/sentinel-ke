import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  FileText,
  GitBranch,
  Search,
  Shield,
  Sparkles,
  Wrench,
} from "lucide-react";

import {
  fetchEntityFusion,
  fetchEntityPaths,
  fetchEntityPredictions,
  fetchPredictionExplanation,
  fetchToolAttribution,
  queryAICopilot,
} from "../api/ai";
import { downloadReport, generateReport } from "../api/reports";
import type { AIPrediction } from "../types/ai";
import { formatPercent } from "../utils/formatters";
import { clampRiskPercent, formatRiskScore, riskColor, riskSeverityLabel } from "../utils/risk";

type InvestigationProps = {
  initialEntityKey: string | null;
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

export default function EntityInvestigation({ initialEntityKey }: InvestigationProps) {
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

    try {
      const directPredictions = await fetchEntityPredictions(trimmed, { limit: 1, predictionType: "risk_gnn" });
      const fallbackPredictions = directPredictions.length > 0
        ? directPredictions
        : await fetchEntityPredictions(trimmed, { limit: 1, predictionType: "corruption_risk" });
      const latestPrediction = fallbackPredictions[0] ?? null;
      setPrediction(latestPrediction);

      const [explanationPayload, toolPayload, pathPayload, fusionPayload, reportPayload] = await Promise.all([
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
      ]);

      setExplanation((explanationPayload as ExplanationRecord | null) ?? null);
      setToolAttribution((toolPayload as ToolAttributionRecord | null) ?? null);
      setPathScore(extractFirstItem<PathScoreRecord>(pathPayload));
      setFusion(extractFirstItem<FusionRecord>(fusionPayload));
      setReportPreview(reportPayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "investigation_failed");
      setPrediction(null);
      setExplanation(null);
      setToolAttribution(null);
      setPathScore(null);
      setFusion(null);
      setReportPreview(null);
    } finally {
      setLoading(false);
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
    const pathValue = pathScore?.path_score != null ? formatRiskScore(pathScore.path_score) : "not available";
    const fusedValue = fusion?.fused_score != null ? formatRiskScore(fusion.fused_score) : "not available";

    return [
      `${entityKey} is currently scored ${formatRiskScore(prediction.score)} / 100 (${riskSeverityLabel(prediction.score)}).`,
      prediction.kill_chain_stage ? `The current kill-chain stage is ${prediction.kill_chain_stage}.` : null,
      reasons.length > 0 ? `Main reasons: ${reasons.join(", ").toLowerCase().replaceAll("_", " ")}.` : null,
      evidenceCount > 0 ? `${evidenceCount} supporting evidence records are attached to the explanation.` : null,
      `Path score is ${pathValue} and fused decision score is ${fusedValue}.`,
      toolCount > 0 ? `${toolCount} likely attacker tools are currently mapped from the observed techniques.` : null,
      "This is an investigative indicator, not final proof.",
    ].filter(Boolean).join(" ");
  }, [entityKey, explanation, fusion, pathScore, prediction, toolAttribution]);

  const predictionScore = clampRiskPercent(prediction?.score);
  const pathScoreValue = clampRiskPercent(pathScore?.path_score);
  const fusedScoreValue = clampRiskPercent(fusion?.fused_score);
  const uncertaintyValue = Math.max(0, Math.min(100, (prediction?.uncertainty ?? 0) * 100));
  const reportSummary = (reportPreview?.summary as Record<string, unknown> | undefined) ?? {};
  const reportFindings = Array.isArray(reportPreview?.findings) ? (reportPreview?.findings as Array<Record<string, unknown>>) : [];

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
            <div className="chip-row">
              <span className="chip">Entity: {prediction.entity_key}</span>
              <span className="chip">Prediction: {prediction.prediction_type}</span>
              <span className="chip">Model: {prediction.model_version ?? "—"}</span>
              <span className="chip">Decision source: {prediction.decision_source ?? "—"}</span>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Decision posture</h3>
              <span className="muted">Corrected score scales from the backend</span>
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
                <span className="muted">{explanation?.evidence_hashes?.length ?? 0} evidence hashes</span>
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
            {copilotAnswer && (
              <div className="panel-subsection">
                <div className="list-item">
                  <p style={{ lineHeight: 1.7, margin: 0 }}>{copilotAnswer}</p>
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
