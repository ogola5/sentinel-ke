export const formatPercent = (value: number, digits = 0) =>
  `${(value * 100).toFixed(digits)}%`;

export const formatScore = (value: number) => value.toFixed(2);

export const formatConfidence = (value: number) => `${Math.round(value)}%`;

export const shortHash = (hash: string) =>
  hash.length > 10 ? `${hash.slice(0, 6)}...${hash.slice(-3)}` : hash;
