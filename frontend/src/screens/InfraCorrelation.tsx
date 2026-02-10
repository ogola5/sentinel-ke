import type { InfraCluster } from "../types/domain";
import { Meter, SmallStack } from "../components/Charts";
import { formatConfidence } from "../utils/formatters";

type InfraCorrelationProps = {
  clusters: InfraCluster[];
  selectedId: string;
  onSelect: (clusterId: string) => void;
  onOpenGraph: () => void;
  onOpenEvidence: (cluster: InfraCluster) => void;
};

export default function InfraCorrelation({
  clusters,
  selectedId,
  onSelect,
  onOpenGraph,
  onOpenEvidence,
}: InfraCorrelationProps) {
  const selected = clusters.find((cluster) => cluster.id === selectedId) ?? clusters[0];

  return (
    <section className="screen">
      <div className="screen-header">
        <div>
          <p className="eyebrow">S5</p>
          <h2>Infrastructure & VPN Correlation</h2>
          <p className="subtle">Operator inference without unmasking real IPs.</p>
        </div>
        <div className="claim">
          VPN is not broken; operator correlation is inferred from infrastructure reuse.
        </div>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>Infra clusters</h3>
            <span className="muted">Correlation confidence</span>
          </div>
          <div className="campaign-list">
            {clusters.map((cluster) => (
              <button
                key={cluster.id}
                className={cluster.id === selected.id ? "campaign-card active" : "campaign-card"}
                type="button"
                onClick={() => onSelect(cluster.id)}
              >
                <div>
                  <p className="label">{cluster.id}</p>
                  <p className="muted">{cluster.type}</p>
                </div>
                <div className="stat">{formatConfidence(cluster.confidence)}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>{selected.id}</h3>
            <span className="muted">{selected.provider}</span>
          </div>
          <div className="detail-grid">
            <div>
              <p className="label">ASN</p>
              <p className="stat mono">{selected.asn}</p>
            </div>
            <div>
              <p className="label">Confidence</p>
              <p className="stat">{formatConfidence(selected.confidence)}</p>
            </div>
            <div>
              <p className="label">Members</p>
              <p className="stat">{selected.members.length} IPs</p>
            </div>
            <div>
              <p className="label">Provider</p>
              <p className="stat">{selected.provider}</p>
            </div>
          </div>
          <Meter value={selected.confidence / 100} label="Cluster confidence" />
          <div className="panel-subsection">
            <h4>Members</h4>
            <div className="chip-row">
              {selected.members.map((member) => (
                <span key={member} className="chip">
                  {member}
                </span>
              ))}
            </div>
          </div>
          <div className="panel-subsection">
            <h4>Why linked</h4>
            <div className="factors">
              {selected.reasons.map((reason) => (
                <span key={reason} className="factor">
                  {reason}
                </span>
              ))}
            </div>
            <button className="ghost" type="button" onClick={() => onOpenEvidence(selected)}>
              Evidence references
            </button>
          </div>
        </div>
      </div>

      <div className="grid-two">
        <div className="panel">
          <div className="panel-header">
            <h3>IP rotation</h3>
            <span className="muted">Operator stays constant</span>
          </div>
          <div className="rotation-table">
            {selected.rotation.map((rotation) => (
              <div key={rotation.ip} className="rotation-row">
                <span className="mono">{rotation.ip}</span>
                <span>{rotation.window}</span>
                <span className="chip">{rotation.provider}</span>
              </div>
            ))}
          </div>
          <button className="ghost" type="button" onClick={onOpenGraph}>
            Open members in graph
          </button>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Provider / ASN view</h3>
            <span className="muted">Traffic share</span>
          </div>
          <SmallStack data={[62, 21, 17]} labels={["VPN", "Hosting", "Residential"]} />
          <div className="stack-legend">
            <span>VPN 62%</span>
            <span>Hosting 21%</span>
            <span>Residential 17%</span>
          </div>
          <p className="muted">
            Recommended mitigations target ASN-level levers instead of attempting de-anonymization.
          </p>
        </div>
      </div>
    </section>
  );
}
