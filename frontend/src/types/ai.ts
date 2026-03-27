export interface FairnessMetrics {
  fairness_flag: "PASS" | "WARN" | "FAIL";
  max_positive_rate_disparity: number;
  max_recall_disparity: number;
  types_evaluated: number;
  by_type?: Record<string, {
    positive_rate: number;
    actual_positive_rate: number;
    precision: number;
    recall: number;
    count: number;
    positive_count: number;
  }>;
}

export interface GNNTrainingRun {
  id: string;
  model_version: string;
  prediction_type: string;
  source_backend?: string | null;
  window_key?: string | null;
  window_end?: string | null;
  auc: number | null;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  train_loss: number | null;
  val_loss: number | null;
  epochs: number | null;
  node_count: number | null;
  edge_count: number | null;
  positive_count: number | null;
  feature_dim: number | null;
  artifact_path: string | null;
  params?: Record<string, unknown> | null;
  fairness?: FairnessMetrics;
  fairness_blocked?: boolean;
  provenance?: Record<string, unknown> | null;
  real_data_gate?: Record<string, unknown> | null;
  real_data_gate_passed?: boolean;
  metrics?: {
    epoch_train_losses?: number[];
    epoch_val_losses?: number[];
    [key: string]: unknown;
  } | null;
  created_at: string;
}

export interface GNNLivePredictionSummary {
  prediction_type: string;
  window_key?: string | null;
  window_end?: string | null;
  model_version?: string | null;
  prediction_count: number;
  flagged_count: number;
  high_risk_count: number;
  abstained_count: number;
  avg_score: number;
  max_score: number;
  latest_created_at?: string | null;
}

export interface GNNDomainSummary {
  prediction_type: string;
  domain_label: string;
  available: boolean;
  status: "ok" | "warn" | "missing";
  status_reasons: string[];
  latest_run: GNNTrainingRun | null;
  latest_live_predictions: GNNLivePredictionSummary | null;
  run_prediction_alignment: {
    window_matches: boolean;
    model_version_matches: boolean;
  };
}

export interface GNNDomainHealth {
  prediction_type: string;
  domain_label: string;
  status: "ok" | "warn" | "missing";
  status_reasons: string[];
  latest_run_created_at?: string | null;
  latest_run_window_end?: string | null;
  latest_prediction_window_end?: string | null;
  latest_prediction_count?: number | null;
  high_risk_count?: number | null;
  flagged_count?: number | null;
  run_prediction_alignment: {
    window_matches: boolean;
    model_version_matches: boolean;
  };
  fairness_blocked?: boolean | null;
  real_data_gate_passed?: boolean | null;
}

export interface JudgeLaneKPIEvidence {
  training_metrics?: {
    auc?: number | null;
    precision?: number | null;
    recall?: number | null;
    f1?: number | null;
  };
  operating_metrics?: {
    f1?: number | null;
    recall?: number | null;
    accuracy?: number | null;
    precision?: number | null;
    sample_count?: number | null;
    threshold_mode?: string | null;
  };
  thresholds?: {
    path?: string | null;
    available?: boolean;
    window_key?: string | null;
    window_end?: string | null;
    entity_type_count?: number | null;
    items?: Array<{
      entity_type?: string | null;
      threshold_score?: number | null;
      method?: string | null;
      sample_count?: number | null;
      positive_count?: number | null;
    }>;
  };
  baselines?: {
    path?: string | null;
    available?: boolean;
    window_key?: string | null;
    coverage_count?: number | null;
    latest_updated_at?: string | null;
  };
}

export interface GNNScientificWindowSummary {
  run_id?: string | null;
  model_version?: string | null;
  window_key?: string | null;
  window_end?: string | null;
  created_at?: string | null;
  node_count?: number | null;
  edge_count?: number | null;
  positive_count?: number | null;
  benchmarkable?: boolean;
  eligible?: boolean;
  fairness_blocked?: boolean;
  real_data_gate_passed?: boolean;
  dual_class_holdout?: boolean;
  class_thin_holdout?: boolean;
  holdout_positive_count?: number | null;
  holdout_negative_count?: number | null;
  eval_samples?: number | null;
  auc?: number | null;
  pr_auc?: number | null;
  operating_f1?: number | null;
  operating_precision?: number | null;
  operating_recall?: number | null;
  scientific_score?: number | null;
}

export interface GNNScientificSummary {
  prediction_type: string;
  domain_label: string;
  status: "strong" | "moderate" | "limited" | "weak" | "missing" | string;
  headline: string;
  window_count: number;
  eligible_window_count: number;
  benchmarkable_window_count: number;
  dual_class_holdout_count: number;
  class_thin_holdout_count: number;
  aggregates?: {
    mean_auc?: number | null;
    median_auc?: number | null;
    mean_pr_auc?: number | null;
    mean_operating_f1?: number | null;
    mean_operating_precision?: number | null;
    mean_operating_recall?: number | null;
    mean_scientific_score?: number | null;
  };
  windows: GNNScientificWindowSummary[];
}

export interface JudgeLaneSummary {
  prediction_type: string;
  domain_label: string;
  status: "ok" | "warn" | "missing" | string;
  status_reasons: string[];
  latest_run: {
    id?: string | null;
    model_version?: string | null;
    source_backend?: string | null;
    window_key?: string | null;
    window_end?: string | null;
    created_at?: string | null;
    node_count?: number | null;
    edge_count?: number | null;
    positive_count?: number | null;
    auc?: number | null;
    precision?: number | null;
    recall?: number | null;
    f1?: number | null;
  } | null;
  live_prediction_alignment: {
    window_matches?: boolean;
    model_version_matches?: boolean;
    latest_window_key?: string | null;
    latest_window_end?: string | null;
    prediction_count?: number | null;
    flagged_count?: number | null;
    high_risk_count?: number | null;
    abstained_count?: number | null;
    avg_score?: number | null;
    max_score?: number | null;
  };
  kpi_evidence: JudgeLaneKPIEvidence;
  scientific_evidence?: GNNScientificSummary;
  robustness_trust_signals: {
    fairness_blocked?: boolean | null;
    fairness_flag?: string | null;
    max_positive_rate_disparity?: number | null;
    real_data_gate_passed?: boolean | null;
    benchmarkable?: boolean | null;
    benchmark_reasons?: string[];
    drift_status?: string | null;
    drift_score?: number | null;
    rollout_mode?: string | null;
    rollout_status?: string | null;
  };
  honest_caveats: string[];
}

export interface JudgeBenchmarkEvidenceItem {
  benchmark_id: string;
  label: string;
  domain: string;
  status: "ok" | "missing" | string;
  dataset?: string | null;
  description?: string | null;
  model?: string | null;
  recorded_at?: string | null;
  headline?: string | null;
  honest_caveat?: string | null;
  artifact_path?: string | null;
  metrics?: {
    auc?: number | null;
    pr_auc?: number | null;
    f1?: number | null;
    precision?: number | null;
    recall?: number | null;
    sample_count?: number | null;
    evaluation_scope?: string | null;
    holdout_positive_count?: number | null;
    holdout_negative_count?: number | null;
  };
  run_config?: {
    window_key?: string | null;
    max_rows?: number | null;
    csv_supplied?: boolean;
    csv_name?: string | null;
    csv_sha256?: string | null;
    snapshot_inserted?: number | null;
  };
}

export interface JudgeReadinessPayload {
  status: "ok" | "warn" | "missing" | string;
  headline: string;
  lanes: JudgeLaneSummary[];
  benchmark_evidence?: {
    available?: boolean;
    items: JudgeBenchmarkEvidenceItem[];
  };
  honest_caveats: string[];
  evidence_endpoints: {
    latest_runs?: string;
    domain_health?: string;
    scientific_summary?: string;
    benchmarks?: string;
    thresholds?: string;
    baselines?: string;
    trust_summary?: string;
  };
  generated_at: string;
}

export interface OperationalHealthSnapshot {
  gnn_loaded: boolean;
  gnn_model_version?: string | null;
  gnn_prediction_type?: string | null;
  schema_contract_ok: boolean;
  schema_missing_count: number;
  federation_signed_requests_required: boolean;
  legal_anchor_integrity?: string | null;
  federation_partners?: number | null;
}

export interface AIPrediction {
  id: string;
  entity_key: string;
  entity_type?: string | null;
  prediction_type: string;
  model_version?: string | null;
  window_key?: string | null;
  window_end?: string | null;
  score: number;
  confidence: number | null;
  uncertainty: number | null;
  abstained: boolean;
  kill_chain_stage: string | null;
  decision_source: string | null;
  reason_codes: string[];
  explanation_method?: string | null;
  top_feature?: string | null;
  details?: Record<string, unknown>;
  created_at: string;
}

export interface CryptoPosture {
  id?: string;
  section_code?: string | null;
  tls_mode: string;
  pqc_mode: string;
  kms_provider: string;
  signing_alg?: string;
  password_kdf?: string;
  key_rotation_days: number;
  compliant?: boolean;
  details_json?: Record<string, unknown>;
  algorithms?: Record<string, unknown>;
  token_format?: Record<string, unknown>;
  mfa_encryption?: Record<string, unknown>;
  nist_compliance?: Record<string, boolean>;
  created_at?: string;
}

export interface SelfTestResult {
  test: string;
  passed: boolean;
  duration_ms?: number;
  detail?: string | null;
}

export interface AIFeedback {
  id: string;
  prediction_id: string;
  entity_key: string;
  feedback_label: number;
  analyst_id: string;
  notes?: string | null;
  status: string;
  used_in_training?: boolean;
  created_at: string;
}

export interface AIDriftReport {
  id: string;
  prediction_type: string;
  model_version: string;
  window_key: string;
  window_end: string;
  drift_score: number;
  status: string;
  metrics?: Record<string, unknown>;
  created_at: string;
}

export interface AIScenarioForecastPoint {
  timestamp: string;
  forecast_score: number;
  lower_80?: number;
  upper_80?: number;
  lower_95?: number;
  upper_95?: number;
  horizon_hour: number;
}

export interface AIScenarioHistoryPoint {
  timestamp: string;
  score: number;
  event_count: number;
  ddos_count?: number;
  login_count?: number;
  sim_swap_count?: number;
  transaction_count?: number;
  distinct_ips?: number;
  distinct_devices?: number;
  distinct_accounts?: number;
  smoothed_score?: number;
}

export interface AIScenarioForecast {
  status: string;
  scenario: string;
  normalized_scenario: string;
  display_name: string;
  generated_at: string;
  lookback_hours: number;
  history_hours: number;
  horizon_hours: number;
  trend_direction?: string;
  net_change_forecast?: number;
  volatility?: number;
  forecast_confidence?: number;
  confidence_grade?: string;
  methodology_note?: string;
  scenario_explanation?: string;
  recommended_operator_posture?: string;
  source_summary?: {
    matching_events: number;
    hours_with_activity: number;
    scenario_alias_applied?: boolean;
  };
  alert_recommendation?: {
    level?: string;
    message?: string;
    peak_forecast_score?: number;
  };
  history: AIScenarioHistoryPoint[];
  forecast: AIScenarioForecastPoint[];
}

export interface TrustCheck {
  label: string;
  status: "pass" | "warn" | "fail";
  detail: string;
  action?: string | null;
}

export interface EntityTrustSummary {
  entity_key: string;
  prediction_type: string;
  prediction: {
    id: string;
    score: number;
    confidence: number;
    uncertainty: number;
    severity: string;
    kill_chain_stage?: string | null;
    decision_source?: string | null;
    model_version?: string | null;
    window_end?: string | null;
  };
  operator_brief: {
    headline: string;
    what_system_saw: string[];
    why_it_matters: string[];
    next_actions: string[];
    caveat: string;
    operator_decision?: string;
    likelihood_indicator?: string;
    graph_meaning?: string;
    data_realism?: string;
    containment_readiness?: string;
  };
  evidence_summary: {
    reason_count: number;
    evidence_hash_count: number;
    evidence_path_count: number;
    counterfactual_available: boolean;
    linked_campaign_count: number;
    technique_count: number;
    tool_count: number;
  };
  action_summary: {
    recommended_controls: string[];
    containment_webhook_count: number;
    fusion_decision?: string | null;
    fusion_score?: number | null;
  };
  governance: {
    model_version?: string | null;
    rollout_mode?: string | null;
    rollout_status?: string | null;
    real_data_gate_passed?: boolean;
    fairness_status?: string;
    drift_status?: string;
    drift_score?: number | null;
    label_strategy?: Record<string, unknown>;
    fairness?: Record<string, unknown>;
    real_data_gate?: Record<string, unknown>;
    provenance?: Record<string, unknown>;
    feedback_metrics?: Record<string, unknown>;
  };
  trust_checks: TrustCheck[];
  linked_campaigns: Array<{
    campaign_id: string;
    score: number;
    severity: string;
    flagged_entity_count: number;
    window_end: string;
  }>;
  feedback: {
    count: number;
    latest_status?: string | null;
    latest_label?: number | null;
  };
  generated_at: string;
}

export interface PlatformTrustSummary {
  overall_status: "pass" | "warn" | "fail";
  headline: string;
  freshness: {
    prediction_age_hours?: number | null;
    graph_age_hours?: number | null;
    intel_age_hours?: number | null;
    latest_prediction_at?: string | null;
    latest_prediction_source?: string | null;
    latest_explanation_at?: string | null;
    latest_graph_snapshot_at?: string | null;
    latest_threat_intel_at?: string | null;
    threat_intel_source_count: number;
  };
  action_readiness: {
    active_webhooks: number;
    executed_actions_24h: number;
    pending_actions: number;
    incident_runs_24h: number;
  };
  resilience: {
    backup_attestations_30d: number;
    latest_restore_success: boolean;
    latest_restore_at?: string | null;
  };
  model_governance: Array<{
    prediction_type: string;
    model_version?: string | null;
    window_end?: string | null;
    fairness_status: string;
    real_data_gate_passed: boolean;
    real_ratio?: number;
    avg_real_signal_ratio?: number;
    feedback_override_count?: number;
    feedback_consumed_count?: number;
    drift_status: string;
    rollout_mode?: string | null;
    rollout_status?: string | null;
    label_caveat?: string | null;
    status: "pass" | "warn" | "fail";
  }>;
  worker_freshness?: Array<{
    worker_name?: string;
    freshness?: string;
    last_status?: string | null;
    last_heartbeat_at?: string | null;
    age_seconds?: number | null;
  }>;
  checks: TrustCheck[];
  recommended_actions: string[];
  generated_at: string;
}
