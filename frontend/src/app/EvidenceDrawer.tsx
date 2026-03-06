import type { EvidenceItem } from "../types/domain";
import { sourceLabel } from "./navigation";

export default function EvidenceDrawer({
  open,
  title,
  items,
  onClose,
}: {
  open: boolean;
  title: string;
  items: EvidenceItem[];
  onClose: () => void;
}) {
  return (
    <div className={open ? "evidence-drawer open" : "evidence-drawer"}>
      <div className="drawer-header">
        <div>
          <p className="label">Evidence</p>
          <h3>{title}</h3>
        </div>
        <button className="ghost" type="button" onClick={onClose}>
          Close ×
        </button>
      </div>
      <div className="drawer-content">
        {items.length === 0 ? (
          <p className="muted">No evidence loaded.</p>
        ) : (
          items.map((item) => (
            <div key={item.event_hash} className="evidence-item">
              <span className="mono">{item.event_hash}</span>
              <span className="chip">{sourceLabel(item.source)}</span>
              <span>{item.detail}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
