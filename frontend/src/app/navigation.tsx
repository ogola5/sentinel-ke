import type { CSSProperties, ComponentType } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart2,
  BookOpen,
  Brain,
  Building2,
  Cpu,
  FileText,
  Flag,
  Globe,
  Lock,
  Network,
  Radio,
  Search,
  Server,
  Shield,
  Users,
  Zap,
} from "lucide-react";

import type { SourceType } from "../types/domain";

type NavIcon = ComponentType<{ size: number; style?: CSSProperties; color?: string }>;

export type NavItem = {
  id: string;
  label: string;
  Icon: NavIcon;
  tag: string;
};

export type ScreenChrome = {
  title: string;
  subtitle: string;
  showSourceFilters?: boolean;
  showTimeWindow?: boolean;
  showEntitySearch?: boolean;
  entitySearchLabel?: string;
  entitySearchPlaceholder?: string;
};

export type ScreenGuide = {
  purpose: string;
  steps: [string, string, string];
  next?: string;
};

// ── Primary navigation (8 items — analyst daily workflow) ─────────────────────

export const NAV_SENSE = [
  { id: "live", label: "Live Feed", Icon: Radio, tag: "S1" },
] as const;

export const NAV_ANALYZE = [
  { id: "graph", label: "Threat Graph", Icon: Network, tag: "S2" },
  { id: "investigate", label: "Investigate", Icon: Search, tag: "S3" },
] as const;

export const NAV_ATTRIBUTE = [
  { id: "campaigns", label: "Campaigns", Icon: Flag, tag: "S4" },
] as const;

export const NAV_RESPOND = [
  { id: "cases", label: "Cases", Icon: FileText, tag: "S5" },
  { id: "defense", label: "Defense", Icon: Shield, tag: "S6" },
] as const;

export const NAV_GOVERN = [
  { id: "ops", label: "Dashboard", Icon: BarChart2, tag: "S7" },
  { id: "reports", label: "Reports", Icon: FileText, tag: "S8" },
] as const;

export const NAV_COMMAND = [
  { id: "command", label: "Command", Icon: Cpu, tag: "C1" },
] as const;

// ── System / admin screens (collapsed drawer — not in daily analyst flow) ─────

export const NAV_ADMIN = [
  { id: "timeline", label: "Service Indicators", Icon: Activity, tag: "A1" },
  { id: "infra", label: "Infra Correlation", Icon: Server, tag: "A2" },
  { id: "gnn", label: "GNN Intelligence", Icon: Brain, tag: "A3" },
  { id: "crypto", label: "Crypto Posture", Icon: Lock, tag: "A4" },
  { id: "corruption", label: "Corruption Intel", Icon: Building2, tag: "A5" },
  { id: "federation", label: "Federation", Icon: Globe, tag: "A6" },
  { id: "audit", label: "Audit Log", Icon: BookOpen, tag: "A7" },
  { id: "exec", label: "Crisis Brief", Icon: AlertTriangle, tag: "A8" },
  { id: "onboard", label: "Agency Onboarding", Icon: Zap, tag: "A9" },
  { id: "users", label: "User Management", Icon: Users, tag: "A10" },
] as const;

export type ScreenId =
  | (typeof NAV_SENSE)[number]["id"]
  | (typeof NAV_ANALYZE)[number]["id"]
  | (typeof NAV_ATTRIBUTE)[number]["id"]
  | (typeof NAV_RESPOND)[number]["id"]
  | (typeof NAV_GOVERN)[number]["id"]
  | (typeof NAV_COMMAND)[number]["id"]
  | (typeof NAV_ADMIN)[number]["id"];

export const SCREEN_CHROME: Record<ScreenId, ScreenChrome> = {
  live: {
    title: "Live Feed",
    subtitle: "Watch the current event flow.",
    showSourceFilters: true,
    showTimeWindow: true,
    showEntitySearch: true,
    entitySearchLabel: "Jump to entity",
    entitySearchPlaceholder: "Search a service or entity to investigate",
  },
  graph: {
    title: "Threat Graph",
    subtitle: "Trace connected entities and campaigns.",
    showSourceFilters: true,
    showTimeWindow: true,
    showEntitySearch: true,
    entitySearchLabel: "Investigate entity",
    entitySearchPlaceholder: "Search an entity to open investigation",
  },
  investigate: {
    title: "Investigation",
    subtitle: "Explain one entity clearly.",
    showEntitySearch: true,
    entitySearchLabel: "Entity key",
    entitySearchPlaceholder: "Search a service or entity key",
  },
  campaigns: {
    title: "Campaigns",
    subtitle: "Review coordinated activity.",
    showEntitySearch: true,
    entitySearchLabel: "Find linked entity",
    entitySearchPlaceholder: "Search entity to pivot into investigation",
  },
  cases: {
    title: "Cases",
    subtitle: "Export evidence-backed case packets.",
    showEntitySearch: true,
    entitySearchLabel: "Entity jump",
    entitySearchPlaceholder: "Search entity to investigate before export",
  },
  defense: {
    title: "Defense",
    subtitle: "Run verified response actions.",
  },
  ops: {
    title: "Operations",
    subtitle: "Triage the current operational picture.",
  },
  reports: {
    title: "Reports",
    subtitle: "Generate readable outputs fast.",
  },
  command: {
    title: "Command",
    subtitle: "Keep the national picture focused.",
  },
  timeline: {
    title: "Threat Forecast",
    subtitle: "Read the time-based threat picture.",
    showSourceFilters: true,
    showTimeWindow: true,
  },
  infra: {
    title: "Infrastructure Correlation",
    subtitle: "Inspect shared attack infrastructure.",
    showSourceFilters: true,
    showTimeWindow: true,
  },
  gnn: {
    title: "GNN Intelligence",
    subtitle: "Review model state and caveats.",
  },
  crypto: {
    title: "Crypto Posture",
    subtitle: "Audit platform cryptography.",
  },
  corruption: {
    title: "Corruption Intelligence",
    subtitle: "Review integrity and leakage signals.",
  },
  federation: {
    title: "Federation",
    subtitle: "Track partner posture and correlations.",
  },
  audit: {
    title: "Audit",
    subtitle: "Inspect traceability and control events.",
  },
  exec: {
    title: "Crisis Brief",
    subtitle: "Prepare a short executive brief.",
  },
  onboard: {
    title: "Agency Onboarding",
    subtitle: "Prepare agencies for controlled federation.",
  },
  users: {
    title: "User Management",
    subtitle: "Control access and user readiness.",
  },
};

export const SCREEN_GUIDES: Record<ScreenId, ScreenGuide> = {
  live: {
    purpose: "Use this page to understand what is arriving right now before you open a deeper workflow.",
    steps: ["Scan the newest events.", "Open one event only.", "Pivot to graph or investigation if it matters."],
    next: "Investigate",
  },
  graph: {
    purpose: "Use this page to see how services, infrastructure, and campaigns connect.",
    steps: ["Pick one node or edge.", "Check linked evidence.", "Move to Investigate for a single-entity explanation."],
    next: "Investigate",
  },
  investigate: {
    purpose: "Use this page to explain one entity clearly, record analyst judgment, and trigger a contained response.",
    steps: ["Search one real entity key.", "Read trust and evidence before acting.", "Record feedback, containment, or export a report."],
    next: "Reports",
  },
  campaigns: {
    purpose: "Use this page to review coordinated activity, not isolated alerts.",
    steps: ["Open the highest-risk campaign.", "Inspect linked entities.", "Generate a case if escalation is justified."],
    next: "Cases",
  },
  cases: {
    purpose: "Use this page to package evidence into a clean, reviewable case artifact.",
    steps: ["Generate a case from a campaign.", "Check evidence coverage.", "Export JSON or STIX when ready."],
    next: "Reports",
  },
  defense: {
    purpose: "Use this page to execute response actions and confirm webhook delivery.",
    steps: ["Select an incident run.", "Choose the safest action.", "Confirm delivery receipts before closing."],
    next: "Audit",
  },
  ops: {
    purpose: "Use this page to keep operational queues lean and prioritized.",
    steps: ["Start with the highest-risk queue.", "Open only one queue at a time.", "Escalate to campaigns or reports when needed."],
    next: "Investigate",
  },
  reports: {
    purpose: "Use this page to create readable outputs for operators, leadership, and legal review.",
    steps: ["Choose one report type.", "Use a real entity or prediction.", "Preview before downloading."],
    next: "Investigate",
  },
  command: {
    purpose: "Use this page to keep leadership focused on threat level, network posture, and readiness.",
    steps: ["Read the national brief.", "Check agency network or readiness.", "Open the next operational workspace only when needed."],
    next: "Operations",
  },
  timeline: {
    purpose: "Use this page to understand service movement over time.",
    steps: ["Choose one service.", "Review the timeline.", "Pivot to campaigns or infrastructure if it escalates."],
    next: "Campaigns",
  },
  infra: {
    purpose: "Use this page to inspect shared infrastructure behind linked attacks.",
    steps: ["Choose one cluster.", "Review shared endpoints and evidence.", "Escalate to graph or campaigns if confirmed."],
    next: "Graph",
  },
  gnn: {
    purpose: "Use this page to review model quality, queue quality, and training caveats.",
    steps: ["Check the queue first.", "Review metrics with caveats.", "Train or seed only when needed."],
    next: "Investigate",
  },
  crypto: {
    purpose: "Use this page to inspect cryptographic posture and self-test state.",
    steps: ["Check compliance status.", "Review key and token posture.", "Capture evidence if posture has degraded."],
    next: "Reports",
  },
  corruption: {
    purpose: "Use this page to review procurement and leakage risks in one place.",
    steps: ["Check the highest-risk anomaly.", "Open the supporting integrity signal.", "Export a report for review."],
    next: "Reports",
  },
  federation: {
    purpose: "Use this page to see partner status and cross-agency correlations.",
    steps: ["Check which partners are active.", "Review the highest-risk correlation.", "Escalate only material matches."],
    next: "Command",
  },
  audit: {
    purpose: "Use this page to verify accountability, control events, and traceability.",
    steps: ["Start with the newest entries.", "Verify the action trail.", "Use reports if leadership needs a summary."],
    next: "Reports",
  },
  exec: {
    purpose: "Use this page to prepare a short crisis brief for leadership.",
    steps: ["Confirm the threat level.", "Summarize only the top risks.", "Move leaders to Command or Reports if deeper detail is needed."],
    next: "Command",
  },
  onboard: {
    purpose: "Use this page to prepare an agency for controlled federation access.",
    steps: ["Create the agency profile.", "Provision the user and access level.", "Confirm readiness before federation use."],
    next: "Users",
  },
  users: {
    purpose: "Use this page to manage access, not operational investigations.",
    steps: ["Search the user.", "Update the account or password.", "Return to Command or Defense for operations."],
    next: "Command",
  },
};

export const TIME_WINDOWS = [
  { id: "10m", label: "10m" },
  { id: "1h", label: "1h" },
  { id: "24h", label: "24h" },
  { id: "30d", label: "30d" },
] as const;

export const SOURCE_OPTIONS: SourceType[] = ["telco", "bank", "gov", "osint", "infra"];

export const sourceLabel = (source: SourceType) => source.toUpperCase();

export function NavGroup({
  label,
  color,
  items,
  active,
  collapsed = false,
  onSelect,
}: {
  label: string;
  color: string;
  items: readonly NavItem[];
  active: string;
  collapsed?: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="nav-group">
      {!collapsed && (
        <div className="nav-group-label" style={{ color }}>
          {label}
        </div>
      )}
      {items.map((item) => {
        const { Icon } = item;
        const isActive = active === item.id;
        return (
          <button
            key={item.id}
            className={`nav-item${isActive ? " active" : ""}${collapsed ? " nav-item-icon-only" : ""}`}
            type="button"
            onClick={() => onSelect(item.id)}
            title={`${item.tag} · ${item.label}`}
          >
            <Icon size={14} style={{ opacity: isActive ? 1 : 0.55 }} color={isActive ? color : undefined} />
            {!collapsed && (
              <div className="nav-copy">
                <span className="nav-tag">{item.tag}</span>
                <span className="nav-label">{item.label}</span>
              </div>
            )}
          </button>
        );
      })}
    </div>
  );
}
