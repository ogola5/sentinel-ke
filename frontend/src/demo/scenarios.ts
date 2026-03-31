import type { ScreenId } from "../app/navigation";

export type DemoScenarioId =
  | "ddos"
  | "malware"
  | "vpn"
  | "sim_swap"
  | "ddos_vpn"
  | "ddos_vpn_fraud"
  | "federated_vpn"
  | "federated_sim_swap"
  | "federated_malware";

export type DemoScenarioCard = {
  id: DemoScenarioId;
  label: string;
  summary: string;
  openScreen: ScreenId;
  followUpScreen: ScreenId;
  expectedOutput: string;
  meaning: string;
  modelNote: string;
};

export const DEMO_SCENARIOS: DemoScenarioCard[] = [
  {
    id: "ddos",
    label: "DDoS pressure",
    summary: "Replays a rising burst against a public-facing service so the platform shows detection, graph correlation, and bounded containment.",
    openScreen: "ops",
    followUpScreen: "defense",
    expectedOutput: "Dashboard pressure rises, DDoS alerts appear, the target service becomes high-risk, and Defense shows a safe next action such as WAF challenge or rate limiting.",
    meaning: "This proves the full operational loop: signal, graph, score, explain, and respond.",
    modelNote: "Use this when you want the clearest end-to-end cyber proof. It is the strongest live lane in the platform.",
  },
  {
    id: "malware",
    label: "Malware / IOC spread",
    summary: "Replays malware-style DFIR findings so the feed, graph, and investigation screens show IOC clustering and linked infrastructure.",
    openScreen: "live",
    followUpScreen: "investigate",
    expectedOutput: "Live Feed shows DFIR finding events, Threat Graph groups the IOC infrastructure, and Investigate explains why the IP or domain was elevated.",
    meaning: "This proves that live-style threat intelligence can enter the platform, be connected to infrastructure, and be prioritized for analyst review.",
    modelNote: "Use this to explain that the graph and GNN correlate malware intelligence; they do not by themselves confirm host compromise.",
  },
  {
    id: "vpn",
    label: "VPN infrastructure reuse",
    summary: "Replays repeated successful logins from a rotating VPN-like IP pool so the graph shows reuse instead of isolated logins.",
    openScreen: "graph",
    followUpScreen: "investigate",
    expectedOutput: "Threat Graph and Infra Correlation show a shared access pattern, and Investigate can explain why the linked IP or device deserves review.",
    meaning: "This proves the system can map suspicious shared infrastructure and distinguish correlation from isolated noise.",
    modelNote: "Use this to explain that VPN usage alone is not malicious; Sentinel-KE scores the reuse pattern and linked evidence, not the existence of a VPN.",
  },
  {
    id: "sim_swap",
    label: "SIM swap fraud chain",
    summary: "Replays SIM swap, suspicious login, transfer, and cash-out behavior so the fraud chain is visible without relying on telco partner data.",
    openScreen: "live",
    followUpScreen: "investigate",
    expectedOutput: "Live Feed shows the fraud chain, Threat Graph links the phone, device, login, and transfer path, and Defense suggests fraud-safe actions such as freeze account or suspend SIM change.",
    meaning: "This proves the graph can reconstruct a fraud chain and map it to bounded containment, even though the benchmark evidence is separate from live sovereign data.",
    modelNote: "Use this to show architecture and reasoning, not to claim live national telco validation.",
  },
  {
    id: "ddos_vpn",
    label: "DDoS + VPN pressure",
    summary: "Replays concurrent service pressure and suspicious access reuse so the platform shows overlapping cyber narratives in one view.",
    openScreen: "command",
    followUpScreen: "graph",
    expectedOutput: "Command and Dashboard show rising pressure, while Threat Graph separates service impact from suspicious infrastructure reuse.",
    meaning: "This proves Sentinel-KE can keep different cyber stories in one operational picture instead of handling each alert in isolation.",
    modelNote: "Use this when you need a more complex command-center story, not as the first scenario in a short run.",
  },
  {
    id: "ddos_vpn_fraud",
    label: "Combined pressure",
    summary: "Replays DDoS, VPN reuse, and fraud-chain pressure together for a full mission warm-up.",
    openScreen: "command",
    followUpScreen: "reports",
    expectedOutput: "Command shows broad pressure, multiple queues become active, and Reports can turn the current state into an evidence-backed brief.",
    meaning: "This proves the platform can hold multiple queues, not just one isolated attack story.",
    modelNote: "Use this to warm the environment. It is broader but less crisp than the single-scenario flows.",
  },
  {
    id: "federated_vpn",
    label: "Shared VPN exit across partners",
    summary: "Replays the same VPN-style access infrastructure across KCB, Equity, and M-Pesa so the federation layer can show a shared national warning pattern.",
    openScreen: "federation",
    followUpScreen: "graph",
    expectedOutput: "Federation shows one shared correlation across three partners, and Threat Graph shows the same access infrastructure touching more than one service path.",
    meaning: "This proves Sentinel-KE can surface cross-agency infrastructure reuse without requiring any one agency to surrender raw data to the hub.",
    modelNote: "Use this when you want to show sovereign, privacy-preserving correlation rather than a single-bank alert stream.",
  },
  {
    id: "federated_sim_swap",
    label: "Shared SIM-swap actor",
    summary: "Replays one actor moving from telco SIM swap to bank access and wallet cashout so the platform shows a shared fraud chain across agencies.",
    openScreen: "federation",
    followUpScreen: "investigate",
    expectedOutput: "Federation shows the same actor hash crossing Safaricom, Equity, and KCB, and Investigate explains why the linked phone or device was elevated.",
    meaning: "This proves the system can connect telco, banking, and wallet warnings into one explainable fraud narrative rather than leaving each institution with a partial view.",
    modelNote: "Use this to show cross-agency fraud reasoning. It is stronger than a single SIM-swap replay because the story spans multiple partner edges.",
  },
  {
    id: "federated_malware",
    label: "Shared malware IOC",
    summary: "Replays the same malware / C2 infrastructure across KCB, Equity, and KE-CIRT so the hub can show national correlation from privacy-preserving edge signals.",
    openScreen: "federation",
    followUpScreen: "live",
    expectedOutput: "Federation shows a shared malware correlation, and Live Feed shows DFIR finding events tied to the same IOC infrastructure across multiple services.",
    meaning: "This proves Sentinel-KE can turn partner-local IOC sightings into a single national warning surface without centralizing raw endpoint data.",
    modelNote: "Use this when judges ask how cyber intelligence can spill over from one institution to another in a sovereign way.",
  },
];

export function demoScenarioLabelFor(id: DemoScenarioId): string {
  return DEMO_SCENARIOS.find((scenario) => scenario.id === id)?.label ?? id;
}
