/**
 * DetailPanel — slide-in right-side detail panel.
 *
 * Usage:
 *   <DetailPanel open={!!selected} title="Event Detail" onClose={() => setSelected(null)}>
 *     <p>…content…</p>
 *   </DetailPanel>
 *
 * Closes on overlay click or Escape key.
 */
import { useEffect, type ReactNode } from "react";

type DetailPanelProps = {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
};

export default function DetailPanel({ open, title, subtitle, onClose, children }: DetailPanelProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  return (
    <>
      {/* Dimmed overlay — click to close */}
      <div
        className={`dp-overlay${open ? " dp-overlay-open" : ""}`}
        aria-hidden="true"
        onClick={open ? onClose : undefined}
      />

      {/* Slide-in panel */}
      <aside
        className={`dp-panel${open ? " dp-panel-open" : ""}`}
        aria-modal="true"
        role="dialog"
        aria-label={title}
      >
        <div className="dp-header">
          <div>
            <h3 className="dp-title">{title}</h3>
            {subtitle && <p className="dp-subtitle">{subtitle}</p>}
          </div>
          <button className="ghost dp-close" type="button" onClick={onClose} aria-label="Close panel">
            ✕
          </button>
        </div>
        <div className="dp-body">{children}</div>
      </aside>
    </>
  );
}
