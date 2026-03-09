import { X } from "lucide-react";
import type { ClientCredentials } from "../api/client";

export default function CredentialsPanel({
  credentials,
  onChange,
  onSave,
  onClear,
  onClose,
}: {
  credentials: ClientCredentials;
  onChange: (key: keyof ClientCredentials, value: string) => void;
  onSave: () => void;
  onClear: () => void;
  onClose: () => void;
}) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Client Credentials</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="muted" style={{ fontSize: "0.72rem" }}>Stored in localStorage</span>
            <button className="ghost icon-btn" type="button" onClick={onClose} title="Close">
              <X size={14} />
            </button>
          </div>
        </div>
        <div className="grid-two">
          {(["apiKey", "accessToken", "legalGrantToken", "legalTarget"] as const).map((key) => (
            <label key={key}>
              <p className="label">{key}</p>
              <input
                className="search"
                value={credentials[key]}
                onChange={(event) => onChange(key, event.target.value)}
              />
            </label>
          ))}
        </div>
        <div className="chip-row" style={{ marginTop: 16 }}>
          <button className="ghost" type="button" onClick={onSave}>
            Save & Resync
          </button>
          <button className="ghost" type="button" onClick={onClear}>
            Clear
          </button>
        </div>
      </div>
    </div>
  );
}
