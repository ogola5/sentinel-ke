import { SCREEN_CHROME, type ScreenGuide, type ScreenId } from "./navigation";

type Props = {
  title: string;
  guide: ScreenGuide;
  onNavigate?: (screen: ScreenId) => void;
  onApplyExample?: (value: string) => void;
};

export default function WorkflowGuideStrip({ title, guide, onNavigate, onApplyExample }: Props) {
  const nextLabel = guide.nextScreen ? SCREEN_CHROME[guide.nextScreen].title : guide.next;

  return (
    <section className="panel workflow-guide-panel workflow-guide-strip">
      <div className="workflow-guide-compact-row">
        <div className="workflow-guide-compact-copy">
          <p className="eyebrow">Screen Guide</p>
          <h3>{title}</h3>
          <p className="workflow-guide-compact-purpose">{guide.purpose}</p>
        </div>

        <div className="workflow-guide-compact-actions">
          {guide.sampleInputs && guide.sampleInputs.length > 0 && onApplyExample ? (
            <div className="chip-row workflow-guide-chip-row">
              {guide.sampleInputs.slice(0, 2).map((item) => (
                <button
                  key={item.value}
                  className="chip ghost"
                  type="button"
                  onClick={() => onApplyExample(item.value)}
                  title={item.value}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ) : null}

          {nextLabel && (
            guide.nextScreen && onNavigate ? (
              <button className="chip active" type="button" onClick={() => onNavigate(guide.nextScreen!)}>
                Open {nextLabel}
              </button>
            ) : (
              <p className="muted workflow-guide-next-label">Next: {nextLabel}</p>
            )
          )}
        </div>
      </div>

      <details className="panel-details workflow-guide-details">
        <summary>
          <span>How to work this page</span>
          <span className="muted">3 steps</span>
        </summary>

        <div className="detail-grid workflow-guide-strip-grid">
          <div className="workflow-guide-block">
            <p className="label">Steps</p>
            <ol className="workflow-guide-list">
              {guide.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>

          <div className="workflow-guide-block">
            <p className="label">Examples</p>
            {guide.examples && guide.examples.length > 0 ? (
              <ul className="workflow-guide-list">
                {guide.examples.slice(0, 3).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>{nextLabel ?? "Stay on this screen until one action is complete."}</p>
            )}
          </div>
        </div>
      </details>
    </section>
  );
}
