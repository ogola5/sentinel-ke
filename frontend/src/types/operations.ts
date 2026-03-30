export type OpsMetrics = {
  events: number;
  graphDeltas: number;
  anomalies: number;
  mitigations: number;
};

export type OpsAnomaly = {
  id: string;
  serviceId: string;
  endpoint: string;
  score: number;
  reasonCodes: string[];
  windowEnd: string;
};

export type OpsMitigation = {
  id: string;
  kind: string;
  refId: string;
  stakeholders: string[];
  createdAt: string;
};

export type OpsIocExport = {
  records: number;
  actions: number;
  ips: number;
  domains: number;
  providers: number;
  endpoints: number;
};

export type OpsPrediction = {
  id: string;
  entityKey: string;
  predictionType: string;
  score: number;
  reasonCodes: string[];
  evidenceCount: number;
};

export type OpsEconomySignal = {
  id: string;
  signalType: string;
  agency: string;
  sector: string;
  severity: string;
  score: number;
};

export type OpsProcurementAnomaly = {
  id: string;
  tenderId: string;
  vendorId: string;
  agency: string;
  amount: number;
  severity: string;
  score: number;
};

export type OpsGuardrailDecision = {
  id: string;
  tenderId: string;
  vendorId: string;
  decision: string;
  severity: string;
  score: number;
};

export type OpsIntegrityAlert = {
  id: string;
  sourceSystem: string;
  recordType: string;
  alertType: string;
  severity: string;
  status: string;
  confidence: number;
};

export type OpsLeakageAlert = {
  id: string;
  detectorType: string;
  agency: string;
  vendorId: string;
  severity: string;
  score: number;
};

export type OpsLeakageSummary = {
  windowDays: number;
  totalAlerts: number;
  suspectedAmountTotal: number;
  byDetector: Record<string, number>;
  bySeverity: Record<string, number>;
};

export type OperationsSnapshot = {
  metrics: OpsMetrics;
  availability: {
    cyberFeedsOk: boolean;
    integrityFeedsOk: boolean;
    leakageFeedsOk: boolean;
  };
  anomalies: OpsAnomaly[];
  mitigations: OpsMitigation[];
  iocExport: OpsIocExport;
  predictions: OpsPrediction[];
  economySignals: OpsEconomySignal[];
  procurementAnomalies: OpsProcurementAnomaly[];
  guardrailDecisions: OpsGuardrailDecision[];
  integrityAlerts: OpsIntegrityAlert[];
  leakageAlerts: OpsLeakageAlert[];
  leakageSummary: OpsLeakageSummary;
};
