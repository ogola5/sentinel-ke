import type { ServiceIndicator } from "../types/domain";
import { Meter, Sparkline } from "../components/Charts";
import { formatPercent, formatScore } from "../utils/formatters";

const stageClass = (stage: string) => {
  if (stage === "active") return "stage stage-active";
  if (stage === "emerging") return "stage stage-emerging";
  if (stage === "rehearsal") return "stage stage-rehearsal";
  return "stage";
};

type TimelineProps = {
  indicators: ServiceIndicator[];
  selectedService: string;
  onSelectService: (serviceId: string) => void;
  onOpenCampaign: () => void;
  onShowInfra: () => void;
};

export default function Timeline({
  indicators,
  selectedService,
  onSelectService,
  onOpenCampaign,
  onShowInfra,
}: TimelineProps) {
  const current = indicators.find((item) => item.serviceId === selectedService) ?? indicators[0];
  const latestIndex = current.reqRate.length - 1;
  const evidenceRefs = [
    "ev_9d3f4a2",
    "ev_5af7d21",
    "ev_2c8bde1",
  ];

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S2</p>
          <h2>Timeline / Indicators</h2>
          <p className="subtle">AI baseline, early warning, and risk trajectory.</p>
        </div>
        <div className={stageClass(current.stage)}>Stage: {current.stage}</div>
      </div>

      <div className="panel controls-row">
        <div>
          <p className="label">Service</p>
          <div className="chip-row">
            {indicators.map((item) => (
              <button
                key={item.serviceId}
                className={
                  item.serviceId === selectedService ? "chip active" : "chip ghost"
                }
                type="button"
                onClick={() => onSelectService(item.serviceId)}
              >
                {item.serviceId}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="label">Endpoint</p>
          <p className="stat mono">{current.endpoint}</p>
        </div>
        <div>
          <p className="label">Latest req rate</p>
          <p className="stat">{current.reqRate[latestIndex]}/min</p>
        </div>
        <div>
          <p className="label">Unique IPs</p>
          <p className="stat">{current.uniqueIps[latestIndex]}</p>
        </div>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>Request rate</h3>
            <span className="muted">Baseline vs surge</span>
          </div>
          <Sparkline data={current.reqRate} />
          <div className="chart-meta">
            {current.window.map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
          <button className="ghost" type="button" onClick={onOpenCampaign}>
            Open Campaign
          </button>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Unique IP count</h3>
            <span className="muted">Distribution change</span>
          </div>
          <Sparkline data={current.uniqueIps} stroke="var(--accent-2)" />
          <div className="chart-meta">
            {current.window.map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
          <button className="ghost" type="button" onClick={onShowInfra}>
            Show related infra cluster
          </button>
        </div>
      </div>

      <div className="grid-three">
        <div className="panel">
          <div className="panel-header">
            <h3>Endpoint convergence</h3>
            <span className="muted">Shared target intensity</span>
          </div>
          <Sparkline data={current.endpointConvergence} stroke="var(--danger)" />
          <p className="metric">{current.endpointConvergence[latestIndex]}%</p>
        </div>
        <div className="panel">
          <div className="panel-header">
            <h3>ASN concentration</h3>
            <span className="muted">Operator inference</span>
          </div>
          <Sparkline data={current.asnConcentration} stroke="var(--warning)" />
          <p className="metric">{current.asnConcentration[latestIndex]}%</p>
        </div>
        <div className="panel">
          <div className="panel-header">
            <h3>AI scores</h3>
            <span className="muted">M1 anomaly + M2 DDoS risk</span>
          </div>
          <div className="score-block">
            <div>
              <p className="label">Anomaly score</p>
              <p className="stat mono">{formatScore(current.anomalyScore[latestIndex])}</p>
            </div>
            <div>
              <p className="label">DDoS risk</p>
              <p className="stat mono">{formatPercent(current.ddosRisk[latestIndex], 2)}</p>
            </div>
          </div>
          <Meter value={current.ddosRisk[latestIndex]} label="Risk trajectory" />
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>AI explainability</h3>
          <span className="muted">Top contributing factors</span>
        </div>
        <div className="factors">
          {current.factors.map((factor) => (
            <span key={factor} className="factor">
              {factor}
            </span>
          ))}
        </div>
        <div className="panel-subsection">
          <h4>Evidence refs</h4>
          <div className="list">
            {evidenceRefs.map((ref) => (
              <div key={ref} className="list-item mono">
                {ref}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
