export const normalizeRiskScore = (value: number | null | undefined): number => {
  if (value == null || Number.isNaN(Number(value))) return 0;
  const numeric = Number(value);
  if (numeric <= 1 && numeric >= 0) {
    return numeric * 100;
  }
  return numeric;
};

export const clampRiskPercent = (value: number | null | undefined): number =>
  Math.max(0, Math.min(100, normalizeRiskScore(value)));

export const formatRiskScore = (value: number | null | undefined, digits = 1): string =>
  clampRiskPercent(value).toFixed(digits);

export const riskSeverity = (value: number | null | undefined): "critical" | "high" | "medium" | "low" => {
  const score = clampRiskPercent(value);
  if (score >= 90) return "critical";
  if (score >= 75) return "high";
  if (score >= 55) return "medium";
  return "low";
};

export const riskSeverityLabel = (value: number | null | undefined): string => {
  const severity = riskSeverity(value);
  if (severity === "critical") return "Critical";
  if (severity === "high") return "High";
  if (severity === "medium") return "Medium";
  return "Low";
};

export const riskColor = (value: number | null | undefined): string => {
  const severity = riskSeverity(value);
  if (severity === "critical") return "var(--risk-critical)";
  if (severity === "high") return "var(--risk-high)";
  if (severity === "medium") return "var(--risk-medium)";
  return "var(--risk-low)";
};

export const isHighRisk = (value: number | null | undefined, threshold = 70): boolean =>
  clampRiskPercent(value) >= threshold;
