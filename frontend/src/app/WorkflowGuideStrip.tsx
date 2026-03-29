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
      <div className="workflow-guide-strip-head">
        <div>
          <p className="eyebrow">Screen Guide</p>
          <h3>{title}</h3>
        </div>
        <p className="muted">Focus the operator on one job, one example input, and one next move.</p>
      </div>

      <div className="detail-grid workflow-guide-strip-grid">
        <div className="workflow-guide-block">
          <p className="label">Focus now</p>
          <p>{guide.purpose}</p>
        </div>

        <div className="workflow-guide-block">
          <p className="label">How to work it</p>
          <ol className="workflow-guide-list">
            {guide.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>

        <div className="workflow-guide-block">
          <p className="label">Start here</p>
          {guide.sampleInputs && guide.sampleInputs.length > 0 && onApplyExample ? (
            <div className="chip-row workflow-guide-chip-row">
              {guide.sampleInputs.map((item) => (
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
          ) : guide.examples && guide.examples.length > 0 ? (
            <ul className="workflow-guide-list">
              {guide.examples.slice(0, 2).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>{nextLabel ?? "Stay on this screen until one action is complete."}</p>
          )}

          {nextLabel && (
            <div className="workflow-guide-next">
              <span className="muted">Recommended next</span>
              {guide.nextScreen && onNavigate ? (
                <button className="chip active" type="button" onClick={() => onNavigate(guide.nextScreen!)}>
                  Open {nextLabel}
                </button>
              ) : (
                <p>{nextLabel}</p>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
