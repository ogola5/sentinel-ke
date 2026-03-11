/**
 * S14 — Entity Investigation
 *
 * Unified analyst workflow: search an entity → see risk trajectory →
 * graph neighbourhood → AI explanation → evidence paths → legal bundle
 * status → trigger containment — all in one screen.
 *
 * No props needed: screen fetches its own data per entity search.
 */
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  FileText,
  Link2,
  Search,
  Send,
  Shield,
  Zap,
} from "lucide-react";

import { apiFetchJson } from "../api/client";
import { endpoints } from "../api/endpoints";

// ─── Local types ─────────────────────────────────────────────────────────────

type Prediction = {
  id: string;
  entity_key: string;
  entity_type: string;
  score: number;
  confidence: number;
  uncertainty: number;
  kill_chain_stage: string | null;
  reason_codes: string[];
  decision_source: string;
  model_version: string;
  window_end: string;
};

type Explanation = {
  reason_codes: string[];
  evidence_hashes: string[];
  evidence_paths: Array<{
    path: string[];
    node_types: string[];
    shared_events: number;
    hop_count: number;
  }>;
  recommended_controls_json: string[];
  counterfactual_json: {
    target_probability: number;
    current_probability: number;
    required_probability_shift: number;
    recommended_direction: string;
    top_feature_hint: string;
  } | null;
  details_json: Record<string, unknown>;
};

type ToolAttribution = {
  techniques: Array<{ technique_id: string; tactic: string; confidence: number }>;
  tools: Array<{ software_id: string; name: string; type: string; matched_techniques: string[] }>;
  summary: { technique_count: number; tool_count: number; top_tactic: string | null; tactic_distribution: Record<string, number> };
};

type PathScore = {
  path_score: number;
  hop_count: number;
  evidence_entity_keys: string[];
};

type FusionScore = {
  fused_score: number;
  severity: string;
  decision: string;
  signals_json: { gnn_score: number; path_score: number; anomaly_score: number };
};

// ─── Score ring ──────────────────────────────────────────────────────────────

function ScoreRing({ score, label, size = 80 }: { score: number; label: string; size?: number }) {
  const r = size * 0.38;
  const circ = 2 * Math.PI * r;
  const filled = (score / 100) * circ;
  const color =
    score >= 90 ? "var(--red)" :
    score >= 75 ? "#f97316" :
    score >= 55 ? "#facc15" :
    "var(--accent)";

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={6} />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={color} strokeWidth={6}
          strokeDasharray={`${filled} ${circ}`}
          strokeLinecap="round"
        />
        <text
          x={size / 2} y={size / 2 + 5}
          textAnchor="middle"
          fill={color}
          fontSize={size * 0.22}
          fontWeight={700}
          style={{ transform: `rotate(90deg)`, transformOrigin: `${size / 2}px ${size / 2}px` }}
        >
          {Math.round(score)}
        </text>
      </svg>
      <span style={{ fontSize: 11, color: "var(--text-dim)", textAlign: "center" }}>{label}</span>
    </div>
  );
}

// ─── Collapsible section ──────────────────────────────────────────────────────

function Section({ title, badge, children, defaultOpen = true }: {
  title: string;
  badge?: string | number;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ marginBottom: 16, border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        style={{
          width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "10px 14px", background: "rgba(255,255,255,0.03)", border: "none",
          cursor: "pointer", color: "var(--text)",
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 13 }}>
          {title}
          {badge !== undefined && (
            <span style={{ marginLeft: 8, fontSize: 11, background: "var(--accent)", color: "#000", borderRadius: 10, padding: "1px 7px" }}>
              {badge}
            </span>
          )}
        </span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && <div style={{ padding: "12px 14px" }}>{children}</div>}
    </div>
  );
}

// ─── Severity badge ───────────────────────────────────────────────────────────

function SevBadge({ sev }: { sev: string }) {
  const colors: Record<string, string> = {
    critical: "#ef4444", high: "#f97316", medium: "#facc15", low: "#22c55e",
  };
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4,
      background: colors[sev] ?? "var(--accent)", color: "#000",
    }}>
      {sev.toUpperCase()}
    </span>
  );
}

// ─── Main screen ─────────────────────────────────────────────────────────────

export default function EntityInvestigation() {
  const [query, setQuery] = useState("");
  const [entityKey, setEntityKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [toolAttr, setToolAttr] = useState<ToolAttribution | null>(null);
  const [pathScore, setPathScore] = useState<PathScore | null>(null);
  const [fusionScore, setFusionScore] = useState<FusionScore | null>(null);
  const [containmentStatus, setContainmentStatus] = useState<string | null>(null);
  const [containmentLoading, setContainmentLoading] = useState(false);

  // Copilot
  const [copilotQuestion, setCopilotQuestion] = useState("");
  const [copilotAnswer, setCopilotAnswer] = useState<string | null>(null);
  const [copilotLoading, setCopilotLoading] = useState(false);
  const [copilotError, setCopilotError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);

  // Focus input on mount
  useEffect(() => { inputRef.current?.focus(); }, []);

  async function investigate(key: string) {
    const trimmed = key.trim();
    if (!trimmed) return;
    setEntityKey(trimmed);
    setLoading(true);
    setError(null);
    setPrediction(null);
    setExplanation(null);
    setToolAttr(null);
    setPathScore(null);
    setFusionScore(null);
    setContainmentStatus(null);

    try {
      // 1. Latest prediction for this entity
      const predsJson = await apiFetchJson<{ items: Prediction[] }>(
        endpoints.aiPredictions(1, 0) + `&entity_key=${encodeURIComponent(trimmed)}&prediction_type=risk_gnn`
      );
      const pred: Prediction | null = predsJson?.items?.[0] ?? null;
      setPrediction(pred);

      if (pred) {
        // 2. Explanation
        try {
          setExplanation(await apiFetchJson<Explanation>(endpoints.aiPredictionExplanation(pred.id)));
        } catch (_) { /* optional */ }

        // 3. Tool attribution
        try {
          setToolAttr(await apiFetchJson<ToolAttribution>(`/v1/ai/tool-attribution?entity_key=${encodeURIComponent(trimmed)}`));
        } catch (_) { /* optional */ }

        // 4. Path score (from attack path table)
        try {
          const pj = await apiFetchJson<{ items: PathScore[] }>(`/v1/ai/paths?entity_key=${encodeURIComponent(trimmed)}&limit=1`);
          setPathScore(pj?.items?.[0] ?? null);
        } catch (_) { /* optional */ }

        // 5. Decision fusion
        try {
          const fj = await apiFetchJson<{ items: FusionScore[] }>(`/v1/ai/fusion?entity_key=${encodeURIComponent(trimmed)}&limit=1`);
          setFusionScore(fj?.items?.[0] ?? null);
        } catch (_) { /* optional */ }
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  async function triggerContainment() {
    if (!prediction) return;
    setContainmentLoading(true);
    setContainmentStatus(null);
    try {
      const json = await apiFetchJson<{ status: string }>("/v1/ai/containment/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entity_key: prediction.entity_key,
          prediction_id: prediction.id,
          reason: "analyst_escalation",
        }),
      });
      setContainmentStatus(json?.status ?? "queued");
    } catch (err) {
      setContainmentStatus(`error: ${err}`);
    } finally {
      setContainmentLoading(false);
    }
  }

  async function askCopilot() {
    const q = copilotQuestion.trim();
    if (!q) return;
    setCopilotLoading(true);
    setCopilotAnswer(null);
    setCopilotError(null);
    try {
      const context: Record<string, unknown> = {};
      if (prediction) {
        context.entity_key = prediction.entity_key;
        context.entity_type = prediction.entity_type;
        context.gnn_score = prediction.score;
        context.kill_chain_stage = prediction.kill_chain_stage;
        context.reason_codes = prediction.reason_codes;
      }
      if (fusionScore) {
        context.fused_score = fusionScore.fused_score;
        context.severity = fusionScore.severity;
        context.decision = fusionScore.decision;
      }
      if (toolAttr) {
        context.techniques = toolAttr.techniques.map((t) => t.technique_id);
        context.tools = toolAttr.tools.map((t) => t.name);
      }
      const res = await apiFetchJson<{ answer: string; model: string }>("/v1/ai/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, context }),
      });
      setCopilotAnswer(res.answer);
    } catch (err) {
      setCopilotError(String(err));
    } finally {
      setCopilotLoading(false);
    }
  }

  const sev =
    !prediction ? "low" :
    prediction.score >= 90 ? "critical" :
    prediction.score >= 75 ? "high" :
    prediction.score >= 55 ? "medium" : "low";

  return (
    <div className="panel" style={{ maxWidth: 900, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>
          S14 · Entity Investigation
        </h2>
        <p style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 4 }}>
          Enter any entity key to drill through risk score → graph neighbourhood
          → AI explanation → evidence paths → tool attribution → containment.
        </p>
      </div>

      {/* Search bar */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <div style={{ flex: 1, position: "relative" }}>
          <Search size={14} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text-dim)" }} />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && investigate(query)}
            placeholder="e.g.  ip:197.232.1.1  |  account_h:abc123  |  service_id:kplc-portal"
            style={{
              width: "100%", padding: "8px 10px 8px 30px",
              background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 6, color: "var(--text)", fontSize: 13,
              boxSizing: "border-box",
            }}
          />
        </div>
        <button
          type="button"
          onClick={() => investigate(query)}
          disabled={loading}
          className="btn-primary"
          style={{ padding: "8px 18px", fontSize: 13 }}
        >
          {loading ? "Investigating…" : "Investigate"}
        </button>
      </div>

      {/* How to read guide */}
      {!entityKey && (
        <div style={{
          background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)",
          borderRadius: 8, padding: 16, marginBottom: 20,
        }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>How to use this screen</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
            {[
              { icon: <Search size={14} />, title: "Search any entity", body: "Paste any entity key from the Live Feed, Graph Explorer, or Campaigns screen." },
              { icon: <Zap size={14} />, title: "Risk & fusion scores", body: "GNN score, path-propagated score, and fused decision (GNN 60% + path 25% + anomaly 15%)." },
              { icon: <Link2 size={14} />, title: "Graph neighbourhood", body: "1-hop and 2-hop evidence paths showing which entities co-occurred in the same events." },
              { icon: <FileText size={14} />, title: "AI explanation", body: "Reason codes, feature attributions, counterfactual (what would flip the decision), D3FEND controls." },
              { icon: <AlertTriangle size={14} />, title: "Tool attribution", body: "MITRE ATT&CK techniques observed, matched to known attacker tools / malware families." },
              { icon: <Shield size={14} />, title: "Containment", body: "One-click escalation to auto-containment. Action queued in dry-run mode — no live blocking without operator approval." },
            ].map((t) => (
              <div key={t.title} style={{ background: "rgba(255,255,255,0.02)", borderRadius: 6, padding: "10px 12px" }}>
                <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4, color: "var(--accent)" }}>
                  {t.icon}
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{t.title}</span>
                </div>
                <p style={{ fontSize: 11, color: "var(--text-dim)", margin: 0, lineHeight: 1.5 }}>{t.body}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ padding: "10px 14px", background: "rgba(239,68,68,0.1)", border: "1px solid #ef4444", borderRadius: 6, marginBottom: 16, fontSize: 13, color: "#ef4444" }}>
          {error}
        </div>
      )}

      {/* Entity not found */}
      {entityKey && !loading && !prediction && !error && (
        <div className="state-box">
          <AlertTriangle size={24} style={{ color: "var(--text-dim)" }} />
          <p>No GNN prediction found for <code>{entityKey}</code></p>
          <p style={{ fontSize: 12, color: "var(--text-dim)" }}>
            The entity may not yet have been scored. Run the inference worker or check the spelling.
          </p>
        </div>
      )}

      {/* Results */}
      {prediction && (
        <>
          {/* Risk score banner */}
          <div style={{
            display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap",
            padding: 16, background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)",
            borderRadius: 8, marginBottom: 16,
          }}>
            <ScoreRing score={prediction.score} label="GNN Risk" />
            {fusionScore && <ScoreRing score={fusionScore.fused_score} label="Fused Score" />}
            {pathScore && <ScoreRing score={pathScore.path_score} label="Path Score" size={64} />}
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                <SevBadge sev={fusionScore?.severity ?? sev} />
                <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
                  {prediction.entity_type} · {prediction.entity_key}
                </span>
              </div>
              {prediction.kill_chain_stage && (
                <div style={{ fontSize: 12, marginBottom: 4 }}>
                  <span style={{ color: "var(--text-dim)" }}>Kill-chain: </span>
                  <span style={{ color: "var(--accent)", fontWeight: 600 }}>{prediction.kill_chain_stage}</span>
                </div>
              )}
              {fusionScore && (
                <div style={{ fontSize: 12, marginBottom: 4 }}>
                  <span style={{ color: "var(--text-dim)" }}>Decision: </span>
                  <span style={{ fontWeight: 600 }}>{fusionScore.decision.toUpperCase()}</span>
                  <span style={{ color: "var(--text-dim)", marginLeft: 8 }}>
                    GNN {Math.round(fusionScore.signals_json.gnn_score)} / Path {Math.round(fusionScore.signals_json.path_score)} / Anomaly {Math.round(fusionScore.signals_json.anomaly_score)}
                  </span>
                </div>
              )}
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                {prediction.reason_codes.slice(0, 5).map((rc) => (
                  <span key={rc} style={{ fontSize: 10, background: "rgba(255,255,255,0.06)", borderRadius: 4, padding: "2px 6px" }}>{rc}</span>
                ))}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                <Clock size={11} style={{ marginRight: 4 }} />
                {new Date(prediction.window_end).toLocaleString()}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                Model: {prediction.model_version} · {prediction.decision_source}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                Confidence: {Math.round(prediction.confidence * 100)}% · Uncertainty: {Math.round(prediction.uncertainty * 100)}%
              </div>
            </div>
          </div>

          {/* Containment panel */}
          <div style={{
            display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap",
            padding: "10px 14px", background: "rgba(239,68,68,0.06)",
            border: "1px solid rgba(239,68,68,0.3)", borderRadius: 8, marginBottom: 16,
          }}>
            <Shield size={16} style={{ color: "#ef4444" }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>Containment</div>
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                Dry-run mode active — actions are logged but not dispatched to partner firewalls without live webhook registration.
              </div>
            </div>
            {containmentStatus && (
              <span style={{
                fontSize: 12, padding: "3px 10px", borderRadius: 4,
                background: containmentStatus === "queued" ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
                color: containmentStatus === "queued" ? "#22c55e" : "#ef4444",
                display: "flex", alignItems: "center", gap: 4,
              }}>
                <CheckCircle size={11} /> {containmentStatus}
              </span>
            )}
            <button
              type="button"
              onClick={triggerContainment}
              disabled={containmentLoading}
              style={{
                padding: "6px 14px", fontSize: 12, fontWeight: 600, border: "none",
                borderRadius: 6, background: "#ef4444", color: "#fff", cursor: "pointer",
              }}
            >
              {containmentLoading ? "Queuing…" : "Escalate to Containment"}
            </button>
          </div>

          {/* Graph neighbourhood */}
          {explanation && explanation.evidence_paths.length > 0 && (
            <Section title="Graph Neighbourhood (Evidence Paths)" badge={explanation.evidence_paths.length}>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {explanation.evidence_paths.slice(0, 12).map((p, i) => (
                  <div key={i} style={{
                    display: "flex", gap: 8, alignItems: "center", padding: "6px 10px",
                    background: "rgba(255,255,255,0.02)", borderRadius: 6, fontSize: 12,
                  }}>
                    <span style={{ color: "var(--text-dim)", minWidth: 24 }}>{p.hop_count}h</span>
                    <div style={{ flex: 1, display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {p.path.map((node, ni) => (
                        <span key={ni} style={{ display: "flex", gap: 4, alignItems: "center" }}>
                          <span style={{
                            fontSize: 11, background: "rgba(255,255,255,0.06)",
                            borderRadius: 4, padding: "1px 6px", maxWidth: 180,
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                          }}>{node}</span>
                          {ni < p.path.length - 1 && <Link2 size={10} style={{ color: "var(--text-dim)" }} />}
                        </span>
                      ))}
                    </div>
                    <span style={{ fontSize: 11, color: "var(--text-dim)" }}>{p.shared_events} events</span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* AI Explanation */}
          {explanation && (
            <Section title="AI Explanation" defaultOpen={true}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {/* Reason codes */}
                <div>
                  <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 6 }}>Reason Codes</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {explanation.reason_codes.map((rc) => (
                      <span key={rc} style={{ fontSize: 10, background: "rgba(255,255,255,0.06)", borderRadius: 4, padding: "2px 6px" }}>{rc}</span>
                    ))}
                  </div>
                </div>
                {/* Counterfactual */}
                {explanation.counterfactual_json && (
                  <div>
                    <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 6 }}>Counterfactual</div>
                    <div style={{ fontSize: 12 }}>
                      <div>Current probability: <strong>{(explanation.counterfactual_json.current_probability * 100).toFixed(1)}%</strong></div>
                      <div>Decision threshold: <strong>{(explanation.counterfactual_json.target_probability * 100).toFixed(1)}%</strong></div>
                      <div>Required shift: <strong>{(explanation.counterfactual_json.required_probability_shift * 100).toFixed(1)}pp {explanation.counterfactual_json.recommended_direction}</strong></div>
                      <div style={{ color: "var(--text-dim)", marginTop: 4 }}>Top feature hint: {explanation.counterfactual_json.top_feature_hint}</div>
                    </div>
                  </div>
                )}
                {/* Recommended controls */}
                {explanation.recommended_controls_json?.length > 0 && (
                  <div style={{ gridColumn: "1 / -1" }}>
                    <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 6 }}>D3FEND Defensive Controls</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {explanation.recommended_controls_json.map((c) => (
                        <span key={c} style={{ fontSize: 10, background: "rgba(34,197,94,0.1)", color: "#22c55e", borderRadius: 4, padding: "2px 6px" }}>{c}</span>
                      ))}
                    </div>
                  </div>
                )}
                {/* Evidence hashes */}
                {explanation.evidence_hashes?.length > 0 && (
                  <div style={{ gridColumn: "1 / -1" }}>
                    <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 6 }}>Evidence Hashes ({explanation.evidence_hashes.length})</div>
                    <div style={{ fontFamily: "monospace", fontSize: 10, color: "var(--text-dim)", lineHeight: 1.8 }}>
                      {explanation.evidence_hashes.slice(0, 8).map((h) => (
                        <div key={h}>{h}</div>
                      ))}
                      {explanation.evidence_hashes.length > 8 && (
                        <div>…and {explanation.evidence_hashes.length - 8} more</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </Section>
          )}

          {/* Tool attribution */}
          {toolAttr && (toolAttr.techniques.length > 0 || toolAttr.tools.length > 0) && (
            <Section title="ATT&CK Techniques & Tool Attribution" badge={toolAttr.summary.tool_count > 0 ? `${toolAttr.summary.tool_count} tools` : undefined}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                {/* Techniques */}
                <div>
                  <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 8 }}>Observed Techniques</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {toolAttr.techniques.map((t) => (
                      <div key={t.technique_id} style={{ display: "flex", gap: 8, fontSize: 12, alignItems: "center" }}>
                        <span style={{ fontFamily: "monospace", fontSize: 11, color: "var(--accent)", minWidth: 60 }}>{t.technique_id}</span>
                        <span style={{ flex: 1, color: "var(--text-dim)" }}>{t.tactic}</span>
                        <span style={{ fontSize: 10 }}>{Math.round(t.confidence * 100)}%</span>
                      </div>
                    ))}
                  </div>
                </div>
                {/* Tools */}
                <div>
                  <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 8 }}>Inferred Tools / Malware</div>
                  {toolAttr.tools.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {toolAttr.tools.map((sw) => (
                        <div key={sw.software_id} style={{ padding: "6px 8px", background: "rgba(255,255,255,0.03)", borderRadius: 6 }}>
                          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                            <span style={{ fontSize: 12, fontWeight: 600 }}>{sw.name}</span>
                            <span style={{ fontSize: 10, background: sw.type === "malware" ? "rgba(239,68,68,0.15)" : "rgba(255,255,255,0.06)", color: sw.type === "malware" ? "#ef4444" : "var(--text-dim)", borderRadius: 4, padding: "1px 5px" }}>{sw.type}</span>
                          </div>
                          <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 2 }}>
                            {sw.matched_techniques.join(", ")}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: 12, color: "var(--text-dim)" }}>No tool matches for observed techniques.</p>
                  )}
                </div>
              </div>
              {toolAttr.summary.top_tactic && (
                <div style={{ marginTop: 10, fontSize: 12, color: "var(--text-dim)" }}>
                  Top tactic: <strong style={{ color: "var(--text)" }}>{toolAttr.summary.top_tactic}</strong>
                  {" · "}
                  {Object.entries(toolAttr.summary.tactic_distribution).map(([t, c]) => `${t}(${c})`).join(", ")}
                </div>
              )}
            </Section>
          )}

          {/* Sentinel Analyst */}
          <Section title="Sentinel Analyst" defaultOpen={false}>
            <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 10 }}>
              Ask the local Sentinel analyst engine about this entity — ATT&CK techniques, recommended actions,
              legal authority, threat timing, or attack tooling. The entity's current scores and signals are auto-included.
            </div>
            <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
              <input
                value={copilotQuestion}
                onChange={(e) => setCopilotQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !copilotLoading && askCopilot()}
                placeholder="e.g. What response actions should I take? Which malware is most likely?"
                style={{
                  flex: 1, padding: "8px 10px", background: "var(--surface)",
                  border: "1px solid var(--border)", borderRadius: 6,
                  color: "var(--text)", fontSize: 13,
                }}
              />
              <button
                type="button"
                onClick={askCopilot}
                disabled={copilotLoading || !copilotQuestion.trim()}
                className="btn-primary"
                style={{ padding: "8px 14px", fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}
              >
                <Send size={13} />
                {copilotLoading ? "Thinking…" : "Ask"}
              </button>
            </div>
            {copilotError && (
              <div style={{ padding: "8px 12px", background: "rgba(239,68,68,0.1)", border: "1px solid #ef4444", borderRadius: 6, fontSize: 12, color: "#ef4444", marginBottom: 8 }}>
                {copilotError}
              </div>
            )}
            {copilotAnswer && (
              <div style={{
                padding: "12px 14px", background: "rgba(34,197,94,0.05)",
                border: "1px solid rgba(34,197,94,0.2)", borderRadius: 8,
              }}>
                <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 8, color: "#22c55e", fontSize: 12, fontWeight: 600 }}>
                  <Bot size={14} /> Sentinel Analyst
                </div>
                <div style={{ fontSize: 13, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
                  {copilotAnswer}
                </div>
              </div>
            )}
          </Section>

          {/* Legal note */}
          <div style={{
            padding: "10px 14px", background: "rgba(255,255,255,0.02)",
            border: "1px solid var(--border)", borderRadius: 6,
            fontSize: 11, color: "var(--text-dim)", lineHeight: 1.6,
          }}>
            <strong style={{ color: "var(--text)" }}>Legal notice:</strong>{" "}
            AI risk scores are indicators only — not final proof of malicious activity.
            Evidence hashes and explanation records are preserved for forensic review.
            All containment actions are logged in the audit trail.
            Refer to the active legal order before acting on recommendations.
          </div>
        </>
      )}
    </div>
  );
}
