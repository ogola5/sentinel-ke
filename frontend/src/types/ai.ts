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
  checks: TrustCheck[];
  recommended_actions: string[];
  generated_at: string;
}
