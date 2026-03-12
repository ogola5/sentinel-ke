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
    subtitle: "Monitor national event flow and open a single event at a time.",
    showSourceFilters: true,
    showTimeWindow: true,
    showEntitySearch: true,
    entitySearchLabel: "Jump to entity",
    entitySearchPlaceholder: "Search a service or entity to investigate",
  },
  graph: {
    title: "Threat Graph",
    subtitle: "Trace relationships between services, attack infrastructure, and campaigns.",
    showSourceFilters: true,
    showTimeWindow: true,
    showEntitySearch: true,
    entitySearchLabel: "Investigate entity",
    entitySearchPlaceholder: "Search an entity to open investigation",
  },
  investigate: {
    title: "Investigation",
    subtitle: "Explain one entity clearly: score, evidence, graph paths, and reports.",
    showEntitySearch: true,
    entitySearchLabel: "Entity key",
    entitySearchPlaceholder: "Search a service or entity key",
  },
  campaigns: {
    title: "Campaigns",
    subtitle: "Review coordinated activity and escalate only the highest-risk clusters.",
    showEntitySearch: true,
    entitySearchLabel: "Find linked entity",
    entitySearchPlaceholder: "Search entity to pivot into investigation",
  },
  cases: {
    title: "Cases",
    subtitle: "Export clean case packets with evidence and recommended actions.",
    showEntitySearch: true,
    entitySearchLabel: "Entity jump",
    entitySearchPlaceholder: "Search entity to investigate before export",
  },
  defense: {
    title: "Defense",
    subtitle: "Execute verified response actions and review webhook deliveries.",
  },
  ops: {
    title: "Operations",
    subtitle: "Triage operational queues without mixing them with command or admin tasks.",
  },
  reports: {
    title: "Reports",
    subtitle: "Generate readable reports by cadence, audience, and subject.",
  },
  command: {
    title: "Command",
    subtitle: "Keep the national picture focused: threat level, network posture, and readiness.",
  },
  timeline: {
    title: "Threat Forecast",
    subtitle: "Read the time-based threat picture, forecast, and top threat movement.",
    showSourceFilters: true,
    showTimeWindow: true,
  },
  infra: {
    title: "Infrastructure Correlation",
    subtitle: "Inspect shared attack infrastructure and correlated clusters.",
    showSourceFilters: true,
    showTimeWindow: true,
  },
  gnn: {
    title: "GNN Intelligence",
    subtitle: "Review model health, queue quality, and training runs without hiding caveats.",
  },
  crypto: {
    title: "Crypto Posture",
    subtitle: "Audit platform cryptography, self-tests, and key-management posture.",
  },
  corruption: {
    title: "Corruption Intelligence",
    subtitle: "Review procurement, leakage, and integrity signals in one governed view.",
  },
  federation: {
    title: "Federation",
    subtitle: "Track partner posture, correlations, and privacy-preserving exchange health.",
  },
  audit: {
    title: "Audit",
    subtitle: "Inspect traceability, accountability, and control events.",
  },
  exec: {
    title: "Crisis Brief",
    subtitle: "Prepare a short executive view for central emergency leadership.",
  },
  onboard: {
    title: "Agency Onboarding",
    subtitle: "Register new agencies and prepare them for controlled federation.",
  },
  users: {
    title: "User Management",
    subtitle: "Control access, roles, and user readiness without cluttering the analyst flow.",
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
