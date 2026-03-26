export interface PlaybookRun {
  id: string;
  incident_key: string;
  section_code: string | null;
  severity: "critical" | "high" | "medium" | "low";
  status: "running" | "completed" | "failed";
  created_by: string;
  started_at: string;
  completed_at: string | null;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface DefenseActionDefinition {
  key: string;
  label: string;
  description: string;
  delivery_mode: "webhook" | "internal" | "internal_dispatch";
  continuity_preserving: boolean;
  target_hint: string;
  category: "network" | "service" | "identity" | "email" | "host";
}

export interface ContainmentActionRecord {
  id?: string;
  run_id?: string | null;
  section_code: string | null;
  action_type: string;
  target: string;
  status: "queued" | "executed" | "no_integration" | "failed";
  executed_by?: string | null;
  executed_at?: string;
  details_json: Record<string, unknown>;
  created_at?: string;
}

export interface WebhookRecord {
  id: string;
  section_code: string;
  action_type: string;
  webhook_url: string;
  is_active: boolean;
  created_at: string;
}

export interface WebhookDeliveryRecord {
  id: string;
  action_id: string | null;
  section_code: string | null;
  action_type: string;
  target: string;
  webhook_url: string;
  status: "pending" | "delivered" | "no_integration" | "failed";
  http_status_code: number | null;
  attempt_count: number;
  last_attempted_at: string | null;
  delivered_at: string | null;
  error_message: string | null;
  response_body?: Record<string, unknown>;
  created_at: string;
}

export interface BackupAttestationRecord {
  id: string;
  section_code: string | null;
  asset_id: string;
  backup_id: string;
  immutable: boolean;
  backup_hash?: string | null;
  storage_tier?: string | null;
  status: string;
  rpo_hours?: number | null;
  attested_at: string;
  created_at?: string;
}

export interface RestoreDrillRecord {
  id: string;
  section_code: string | null;
  asset_id: string;
  backup_id: string;
  success: boolean;
  rto_target_minutes: number;
  rto_actual_minutes?: number | null;
  operator_id?: string | null;
  notes?: string | null;
  completed_at?: string | null;
  created_at: string;
}

export interface VulnFinding {
  id: string;
  section_code: string | null;
  asset_id: string;
  cve_id: string;
  source: string;
  severity: string;
  epss: number | null;
  kev: boolean;
  status: string;
  discovered_at: string;
  due_at: string | null;
  patched_at: string | null;
  risk_score: number;
  created_at: string;
}

export interface IncidentActionExecutionResult {
  run_id: string;
  status: "completed" | "failed" | "running";
  actions: Array<{
    action_type: string;
    target: string;
    status: "executed" | "no_integration" | "failed";
    details: Record<string, unknown>;
  }>;
}
