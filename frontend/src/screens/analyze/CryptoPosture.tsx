import { useEffect, useState } from "react";
import { Lock, RefreshCw, ShieldCheck, ShieldAlert, Loader, CheckCircle, XCircle, Cpu } from "lucide-react";
import { fetchCryptoPosture, runCryptoSelfTest } from "../../api/ai";
import type { CryptoPosture as CryptoPostureType, SelfTestResult } from "../../types/ai";

const PQC_ALGORITHMS = ["ml-kem-768", "ml-dsa-65", "kyber768", "dilithium", "crystals"];
const LEGACY_WEAK   = ["sha1", "md5", "rc4", "des", "3des", "rsa-1024", "ec-p256"];

function classifyAlgo(value: string): "pqc-ready" | "pqc-legacy" | "pqc-broken" {
  const v = value.toLowerCase();
  if (PQC_ALGORITHMS.some((a) => v.includes(a))) return "pqc-ready";
  if (LEGACY_WEAK.some((a) => v.includes(a))) return "pqc-broken";
  return "pqc-legacy";
}

function algoLabel(cls: "pqc-ready" | "pqc-legacy" | "pqc-broken"): string {
  if (cls === "pqc-ready")  return "PQC-Ready";
  if (cls === "pqc-broken") return "Weak / Legacy";
  return "Transition";
}

interface AlgoCardProps {
  label: string;
  value: string;
  note?: string;
}
function AlgoCard({ label, value, note }: AlgoCardProps) {
  const cls = classifyAlgo(value);
  return (
    <div className={`algo-card ${cls}`}>
      <div className="algo-label">{label}</div>
      <div className="algo-value">{value || "—"}</div>
      {note && <div className="algo-sub">{note}</div>}
      <div style={{ marginTop: 8 }}>
        <span
          className="risk-badge"
          style={{
            background: cls === "pqc-ready" ? "rgba(49,255,144,.12)" : cls === "pqc-broken" ? "rgba(255,77,90,.12)" : "rgba(255,209,71,.12)",
            color: cls === "pqc-ready" ? "var(--accent)" : cls === "pqc-broken" ? "var(--danger)" : "var(--warning)",
            border: `1px solid ${cls === "pqc-ready" ? "rgba(49,255,144,.3)" : cls === "pqc-broken" ? "rgba(255,77,90,.3)" : "rgba(255,209,71,.3)"}`,
          }}
        >
          {algoLabel(cls)}
        </span>
      </div>
    </div>
  );
}

export default function CryptoPosture() {
  const [posture, setPosture] = useState<CryptoPostureType | null>(null);
  const [selfTest, setSelfTest] = useState<SelfTestResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);

  const load = async () => {
    setLoading(true);
    const p = await fetchCryptoPosture();
    setPosture(p);
    setLoading(false);
  };

  const handleSelfTest = async () => {
    setTesting(true);
    const results = await runCryptoSelfTest();
    setSelfTest(results);
    setTesting(false);
  };

  useEffect(() => {
    void load();
  }, []);

  const passCount = selfTest.filter((t) => t.passed).length;

  return (
    <div>
      <div className="screen-header">
        <h2>
          <Lock size={20} color="var(--info)" />
          Crypto Posture
          <span className="subtitle">— Post-quantum readiness · ML-KEM-768 · ML-DSA-65</span>
        </h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn-ghost" onClick={() => void load()}>
            <RefreshCw size={13} /> &nbsp;Refresh
          </button>
          <button className="btn-accent" onClick={() => void handleSelfTest()} disabled={testing}>
            {testing ? <Loader size={13} /> : <Cpu size={13} />}
            &nbsp;Run Self-Test
          </button>
        </div>
      </div>

      {loading ? (
        <div className="state-box">
          <Loader size={24} />
          <p>Loading crypto posture…</p>
        </div>
      ) : posture == null ? (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div className="state-box">
            <ShieldAlert size={28} color="var(--warning)" />
            <p>No crypto posture snapshot found.</p>
            <p>POST /v1/crypto/posture to capture the current posture.</p>
          </div>
        </div>
      ) : (
        <>
          {/* Compliance banner */}
          <div
            className="panel"
            style={{
              marginBottom: 16,
              borderColor: posture.compliant ? "rgba(49,255,144,.38)" : "rgba(255,209,71,.38)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {posture.compliant ? (
                <ShieldCheck size={22} color="var(--accent)" />
              ) : (
                <ShieldAlert size={22} color="var(--warning)" />
              )}
              <div>
                <div style={{ fontWeight: 700, fontSize: "0.95rem" }}>
                  {posture.compliant ? "Compliant — PQC hybrid mode active" : "Non-compliant — Remediation required"}
                </div>
                <div className="muted" style={{ fontSize: "0.8rem", marginTop: 2 }}>
                  Key rotation: every {posture.key_rotation_days} days · KMS: {posture.kms_provider}
                </div>
              </div>
              <span className={`risk-badge ${posture.compliant ? "low" : "medium"}`} style={{ marginLeft: "auto" }}>
                {posture.compliant ? "Compliant" : "Review Required"}
              </span>
            </div>
          </div>

          {/* Algorithm inventory */}
          <div className="panel" style={{ marginBottom: 16 }}>
            <div className="panel-header">
              <h3>Algorithm Inventory</h3>
            </div>
            <div className="algo-grid">
              <AlgoCard label="TLS mode" value={posture.tls_mode} note="Transport layer security" />
              <AlgoCard label="PQC mode" value={posture.pqc_mode} note="Post-quantum crypto layer" />
              <AlgoCard label="KMS provider" value={posture.kms_provider} note="Key management system" />
              <AlgoCard label="Signing algorithm" value={posture.signing_alg ?? "unknown"} note="Document / token signing" />
              <AlgoCard label="Password KDF" value={posture.password_kdf ?? "unknown"} note="Key derivation function" />
            </div>
          </div>
        </>
      )}

      {/* Self-test results */}
      {selfTest.length > 0 && (
        <div className="panel">
          <div className="panel-header">
            <h3>Self-Test Results</h3>
            <span className="muted">
              {passCount}/{selfTest.length} passed
            </span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Test</th>
                <th>Result</th>
                <th>Duration</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {selfTest.map((t, i) => (
                <tr key={i}>
                  <td>
                    <span style={{ fontSize: "0.82rem", fontFamily: "JetBrains Mono, monospace" }}>{t.test}</span>
                  </td>
                  <td>
                    {t.passed ? (
                      <span style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--accent)" }}>
                        <CheckCircle size={14} /> Pass
                      </span>
                    ) : (
                      <span style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--danger)" }}>
                        <XCircle size={14} /> Fail
                      </span>
                    )}
                  </td>
                  <td className="muted" style={{ fontSize: "0.78rem" }}>
                    {t.duration_ms != null ? `${t.duration_ms.toFixed(1)} ms` : "—"}
                  </td>
                  <td className="muted" style={{ fontSize: "0.78rem" }}>
                    {t.detail ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selfTest.length === 0 && !loading && (
        <div className="panel">
          <div className="state-box">
            <Lock size={26} />
            <p>Click "Run Self-Test" to execute ML-KEM-768 + ML-DSA-65 live tests</p>
          </div>
        </div>
      )}
    </div>
  );
}
