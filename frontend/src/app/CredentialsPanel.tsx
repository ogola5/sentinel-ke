import type { ClientCredentials } from "../api/client";

export default function CredentialsPanel({
  credentials,
  onChange,
  onSave,
  onClear,
}: {
  credentials: ClientCredentials;
  onChange: (key: keyof ClientCredentials, value: string) => void;
  onSave: () => void;
  onClear: () => void;
}) {
  return (
    <div className="panel connection-panel">
      <div className="panel-header">
        <h3>Client Credentials</h3>
        <span className="muted">Stored in localStorage</span>
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
      <div className="chip-row">
        <button className="ghost" type="button" onClick={onSave}>
          Save & Resync
        </button>
        <button className="ghost" type="button" onClick={onClear}>
          Clear
        </button>
      </div>
    </div>
  );
}
