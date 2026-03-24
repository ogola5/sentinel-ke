type FlowTone = "accent" | "info" | "warning" | "danger" | "neutral";

export type ArchitectureFlowStep = {
  stage: string;
  title: string;
  detail?: string;
  tone?: FlowTone;
};

const TONE_CLASS: Record<FlowTone, string> = {
  accent: "architecture-step-accent",
  info: "architecture-step-info",
  warning: "architecture-step-warning",
  danger: "architecture-step-danger",
  neutral: "",
};

export default function ArchitectureFlow({
  label,
  title,
  summary,
  steps,
}: {
  label: string;
  title: string;
  summary?: string;
  steps: ArchitectureFlowStep[];
}) {
  return (
    <div className="panel architecture-flow">
      <div className="architecture-flow-header">
        <div>
          <p className="workflow-stage-kicker">{label}</p>
          <h3>{title}</h3>
        </div>
        {summary && <p className="architecture-flow-summary">{summary}</p>}
      </div>
      <div className="architecture-flow-strip">
        {steps.map((step, index) => (
          <div
            key={`${step.stage}-${step.title}`}
            className={`architecture-step ${TONE_CLASS[step.tone ?? "neutral"]}`.trim()}
          >
            <div className="architecture-step-stage">{step.stage}</div>
            <strong>{step.title}</strong>
            {step.detail && <p>{step.detail}</p>}
            {index < steps.length - 1 && <span className="architecture-step-arrow" aria-hidden="true">→</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
