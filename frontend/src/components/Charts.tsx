import type { CSSProperties } from "react";

const buildPoints = (data: number[], width: number, height: number) => {
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  return data
    .map((value, index) => {
      const x = (index / (data.length - 1 || 1)) * width;
      const y = height - ((value - min) / range) * height;
      return `${x},${y}`;
    })
    .join(" ");
};

export const Sparkline = ({
  data,
  height = 64,
  stroke = "var(--accent)",
}: {
  data: number[];
  height?: number;
  stroke?: string;
}) => {
  const width = 200;
  const points = buildPoints(data, width, height);

  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} role="img">
      <polyline points={points} fill="none" stroke={stroke} strokeWidth="2" />
    </svg>
  );
};

export const BarChart = ({
  data,
  height = 64,
  barColor = "var(--accent-2)",
}: {
  data: number[];
  height?: number;
  barColor?: string;
}) => {
  const max = Math.max(...data, 1);
  return (
    <div className="bar-chart" style={{ height }}>
      {data.map((value, index) => (
        <span
          key={`${value}-${index}`}
          className="bar"
          style={{
            height: `${(value / max) * 100}%`,
            background: barColor,
          }}
        />
      ))}
    </div>
  );
};

export const Meter = ({
  value,
  label,
  tone = "var(--accent)",
}: {
  value: number;
  label: string;
  tone?: string;
}) => {
  const style: CSSProperties = {
    background: `linear-gradient(90deg, ${tone} ${value * 100}%, rgba(0,0,0,0.08) ${
      value * 100
    }%)`,
  };

  return (
    <div className="meter">
      <div className="meter-label">
        <span>{label}</span>
        <span>{Math.round(value * 100)}%</span>
      </div>
      <div className="meter-track" style={style} />
    </div>
  );
};

export const SmallStack = ({
  data,
  labels,
}: {
  data: number[];
  labels: string[];
}) => {
  const total = data.reduce((sum, value) => sum + value, 0) || 1;
  return (
    <div className="stacked-bar">
      {data.map((value, index) => (
        <div
          key={`${labels[index]}-${value}`}
          className="stack-segment"
          style={{ width: `${(value / total) * 100}%` }}
          title={`${labels[index]} ${value}%`}
        />
      ))}
    </div>
  );
};
