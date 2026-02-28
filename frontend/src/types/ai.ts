export interface GNNTrainingRun {
  id: string;
  model_version: string;
  prediction_type: string;
  auc: number | null;
  precision: number | null;
  node_count: number | null;
  edge_count: number | null;
  positive_count: number | null;
  feature_dim: number | null;
  artifact_path: string | null;
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
