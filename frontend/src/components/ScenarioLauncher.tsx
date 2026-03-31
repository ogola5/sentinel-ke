import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Bug,
  Database,
  Loader,
  Play,
  Radar,
  ShieldAlert,
  Smartphone,
} from "lucide-react";

import type { ScreenId } from "../app/navigation";
import { bootstrapDemoData, startDemoScenario } from "../api/ai";
import { DEMO_SCENARIOS, type DemoScenarioCard, type DemoScenarioId } from "../demo/scenarios";

type ScenarioLauncherProps = {
  onNavigate?: (screen: ScreenId) => void;
};

const PRIMARY_SCENARIO_IDS: DemoScenarioId[] = [
  "ddos",
  "federated_vpn",
  "federated_sim_swap",
  "federated_malware",
  "ddos_vpn_fraud",
];

const SCREEN_LABELS: Record<ScreenId, string> = {
  command: "Command",
  live: "Live Feed",
  graph: "Threat Graph",
  investigate: "Investigate",
  campaigns: "Campaigns",
  cases: "Cases",
  defense: "Defense",
  ops: "Dashboard",
  reports: "Reports",
  timeline: "Service Indicators",
  infra: "Infra Correlation",
  gnn: "GNN Intelligence",
  crypto: "Crypto Posture",
  corruption: "Corruption Intel",
  federation: "Federation",
  audit: "Audit",
  exec: "Crisis Brief",
  onboard: "Agency Onboarding",
  users: "User Management",
};

function scenarioIcon(scenarioId: DemoScenarioId) {
  if (scenarioId === "ddos") return AlertTriangle;
  if (scenarioId === "malware" || scenarioId === "federated_malware") return Bug;
  if (scenarioId === "vpn" || scenarioId === "federated_vpn") return Radar;
  if (scenarioId === "sim_swap" || scenarioId === "federated_sim_swap") return Smartphone;
  return ShieldAlert;
}

export default function ScenarioLauncher({ onNavigate }: ScenarioLauncherProps) {
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [statusTone, setStatusTone] = useState<"info" | "success" | "error">("info");

  const scenarios = useMemo(
    () => DEMO_SCENARIOS.filter((scenario) => PRIMARY_SCENARIO_IDS.includes(scenario.id)),
    [],
  );

  const runScenario = async (scenario: DemoScenarioCard) => {
    setBusyAction(`run:${scenario.id}`);
    setStatusTone("info");
    setStatusMessage(null);
    try {
      const response = await startDemoScenario(scenario.id);
      setStatusTone("success");
      setStatusMessage(
        `${scenario.label} accepted. ${response.message ?? "Events are being ingested in the background now."} Open ${SCREEN_LABELS[scenario.openScreen]} next.`,
      );
      onNavigate?.(scenario.openScreen);
    } catch (error) {
      setStatusTone("error");
      setStatusMessage(
        `${scenario.label} failed to start: ${error instanceof Error ? error.message : "scenario_start_failed"}`,
      );
    } finally {
      setBusyAction(null);
    }
  };

  const bootstrapScenario = async (scenario: DemoScenarioCard) => {
    setBusyAction(`bootstrap:${scenario.id}`);
    setStatusTone("info");
    setStatusMessage(null);
    try {
      const response = await bootstrapDemoData("cyber", scenario.id);
      setStatusTone("success");
      setStatusMessage(
        `${scenario.label} preparation accepted. ${response.message} Use this when you want prepared data plus a refreshed cyber model run.`,
      );
    } catch (error) {
      setStatusTone("error");
      setStatusMessage(
        `${scenario.label} bootstrap failed: ${error instanceof Error ? error.message : "scenario_bootstrap_failed"}`,
      );
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className="panel workflow-stage-panel scenario-launcher-panel">
      <div className="panel-header">
        <h3>Scenario launcher</h3>
        <span className="muted">Run scenarios from the workspace instead of the terminal</span>
      </div>

      <div className="workflow-summary-banner" style={{ marginBottom: 14 }}>
        <div>
          <strong>Launch now</strong>
          <span className="muted">Triggers the backend replay path and opens the strongest first screen.</span>
        </div>
        <div>
          <strong>Prepare data + refresh model</strong>
          <span className="muted">Seeds extra cyber training data and refreshes the cyber model in the background.</span>
        </div>
        <div>
          <strong>Best use</strong>
          <span className="muted">DDoS proves the operational loop. The federation scenarios prove why this matters nationally across banks, telco, and public response.</span>
        </div>
      </div>

      {statusMessage && (
        <div className={`scenario-status scenario-status-${statusTone}`}>
          {statusMessage}
        </div>
      )}

      <div className="scenario-launcher-grid">
        {scenarios.map((scenario) => {
          const Icon = scenarioIcon(scenario.id);
          const launching = busyAction === `run:${scenario.id}`;
          const bootstrapping = busyAction === `bootstrap:${scenario.id}`;
          const disabled = busyAction != null;

          return (
            <article key={scenario.id} className="scenario-card">
              <div className="scenario-card-head">
                <div>
                  <p className="eyebrow" style={{ marginBottom: 6 }}>Scenario</p>
                  <h4>{scenario.label}</h4>
                  <p className="muted" style={{ marginTop: 6 }}>{scenario.summary}</p>
                </div>
                <div className="scenario-card-icon">
                  <Icon size={18} />
                </div>
              </div>

              <div className="scenario-screen-row">
                <span className="scenario-screen-chip">Start in {SCREEN_LABELS[scenario.openScreen]}</span>
                <span className="scenario-screen-chip">Then {SCREEN_LABELS[scenario.followUpScreen]}</span>
              </div>

              <div className="scenario-detail-block">
                <strong>Expected output</strong>
                <p className="muted">{scenario.expectedOutput}</p>
              </div>

              <div className="scenario-detail-block">
                <strong>What it proves</strong>
                <p className="muted">{scenario.meaning}</p>
              </div>

              <div className="scenario-detail-block">
                <strong>Model note</strong>
                <p className="muted">{scenario.modelNote}</p>
              </div>

              <div className="scenario-action-row">
                <button type="button" className="ghost" onClick={() => void runScenario(scenario)} disabled={disabled}>
                  {launching ? <Loader size={13} className="spin" /> : <Play size={13} />}
                  &nbsp;Launch now
                </button>
                <button type="button" className="btn-train-cyber" onClick={() => void bootstrapScenario(scenario)} disabled={disabled}>
                  {bootstrapping ? <Loader size={13} className="spin" /> : <Database size={13} />}
                  &nbsp;Prepare data + refresh model
                </button>
                {onNavigate && (
                  <button type="button" className="ghost" onClick={() => onNavigate(scenario.followUpScreen)} disabled={disabled}>
                    Open {SCREEN_LABELS[scenario.followUpScreen]}
                  </button>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
