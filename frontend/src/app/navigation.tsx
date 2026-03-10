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

export const NAV_BRIEF = [
  { id: "exec", label: "Crisis Brief", Icon: AlertTriangle, tag: "B1" },
  { id: "command", label: "National Command", Icon: Cpu, tag: "B2" },
] as const;

export const NAV_MONITOR = [
  { id: "live", label: "Live Feed", Icon: Radio, tag: "M1" },
  { id: "timeline", label: "Service Indicators", Icon: Activity, tag: "M2" },
] as const;

export const NAV_INVESTIGATE = [
  { id: "campaigns", label: "Campaigns", Icon: Flag, tag: "I1" },
  { id: "graph", label: "Threat Graph", Icon: Network, tag: "I2" },
  { id: "infra", label: "Infrastructure", Icon: Server, tag: "I3" },
  { id: "gnn", label: "AI Review", Icon: Brain, tag: "I4" },
] as const;

export const NAV_RESPOND = [
  { id: "cases", label: "Case Packets", Icon: FileText, tag: "R1" },
  { id: "defense", label: "Defense Center", Icon: Shield, tag: "R2" },
] as const;

export const NAV_GOVERN = [
  { id: "ops", label: "Operations", Icon: BarChart2, tag: "G1" },
  { id: "corruption", label: "Integrity", Icon: Building2, tag: "G2" },
  { id: "federation", label: "Federation", Icon: Globe, tag: "G3" },
  { id: "audit", label: "Audit Log", Icon: BookOpen, tag: "G4" },
] as const;

export const NAV_ADMIN = [
  { id: "users", label: "Users", Icon: Users, tag: "A1" },
  { id: "onboard", label: "Onboarding", Icon: Zap, tag: "A2" },
  { id: "crypto", label: "Crypto Posture", Icon: Lock, tag: "A3" },
] as const;

export type ScreenId =
  | (typeof NAV_BRIEF)[number]["id"]
  | (typeof NAV_MONITOR)[number]["id"]
  | (typeof NAV_INVESTIGATE)[number]["id"]
  | (typeof NAV_RESPOND)[number]["id"]
  | (typeof NAV_GOVERN)[number]["id"]
  | (typeof NAV_ADMIN)[number]["id"];

export type WorkspaceId = "brief" | "monitor" | "investigate" | "respond" | "govern" | "admin";

export type WorkspaceItem = {
  id: WorkspaceId;
  label: string;
  description: string;
  Icon: NavIcon;
  color: string;
};

export type NavigationContext = {
  central: boolean;
  execute: boolean;
  manageUsers: boolean;
  auditorOnly: boolean;
};

export const WORKSPACES: Record<WorkspaceId, WorkspaceItem> = {
  brief: {
    id: "brief",
    label: "Brief",
    description: "Leadership posture and immediate national priorities.",
    Icon: AlertTriangle,
    color: "var(--warning)",
  },
  monitor: {
    id: "monitor",
    label: "Monitor",
    description: "Watch incoming activity and service movement in real time.",
    Icon: Radio,
    color: "var(--info)",
  },
  investigate: {
    id: "investigate",
    label: "Investigate",
    description: "Follow entities, campaigns, infrastructure, and model review.",
    Icon: Network,
    color: "var(--accent)",
  },
  respond: {
    id: "respond",
    label: "Respond",
    description: "Build case packets and execute protective actions.",
    Icon: Shield,
    color: "var(--risk-critical)",
  },
  govern: {
    id: "govern",
    label: "Govern",
    description: "Track integrity, federation, and audit controls.",
    Icon: Building2,
    color: "var(--risk-low)",
  },
  admin: {
    id: "admin",
    label: "Admin",
    description: "Manage users, onboarding, and platform posture.",
    Icon: Users,
    color: "var(--command)",
  },
};

const WORKSPACE_SCREENS: Record<WorkspaceId, readonly NavItem[]> = {
  brief: NAV_BRIEF,
  monitor: NAV_MONITOR,
  investigate: NAV_INVESTIGATE,
  respond: NAV_RESPOND,
  govern: NAV_GOVERN,
  admin: NAV_ADMIN,
};

const SCREEN_WORKSPACE: Record<ScreenId, WorkspaceId> = {
  exec: "brief",
  command: "brief",
  live: "monitor",
  timeline: "monitor",
  campaigns: "investigate",
  graph: "investigate",
  infra: "investigate",
  gnn: "investigate",
  cases: "respond",
  defense: "respond",
  ops: "govern",
  corruption: "govern",
  federation: "govern",
  audit: "govern",
  users: "admin",
  onboard: "admin",
  crypto: "admin",
};

function canAccessScreen(screenId: ScreenId, context: NavigationContext): boolean {
  if (context.auditorOnly) {
    if (screenId === "audit" || screenId === "ops" || screenId === "corruption" || screenId === "federation") {
      return true;
    }
    if (screenId === "exec" || screenId === "command") {
      return context.central;
    }
    return false;
  }

  if (screenId === "exec" || screenId === "command") return context.central;
  if (screenId === "defense") return context.execute;
  if (screenId === "users" || screenId === "onboard") return context.manageUsers;
  if (screenId === "crypto") return context.central || context.manageUsers;
  return true;
}

export function getVisibleWorkspaces(context: NavigationContext): WorkspaceItem[] {
  return (Object.keys(WORKSPACES) as WorkspaceId[])
    .filter((workspaceId) => getVisibleScreensForWorkspace(workspaceId, context).length > 0)
    .map((workspaceId) => WORKSPACES[workspaceId]);
}

export function getVisibleScreensForWorkspace(workspaceId: WorkspaceId, context: NavigationContext): NavItem[] {
  return WORKSPACE_SCREENS[workspaceId].filter((item) => canAccessScreen(item.id as ScreenId, context)) as NavItem[];
}

export function getWorkspaceForScreen(screenId: ScreenId): WorkspaceId {
  return SCREEN_WORKSPACE[screenId];
}

export function getDefaultScreenForWorkspace(workspaceId: WorkspaceId, context: NavigationContext): ScreenId {
  const visible = getVisibleScreensForWorkspace(workspaceId, context);
  if (visible.length === 0) {
    if (context.auditorOnly) return "ops";
    return context.central ? "exec" : "live";
  }
  return visible[0].id as ScreenId;
}

export const TIME_WINDOWS = [
  { id: "10m", label: "10m" },
  { id: "1h", label: "1h" },
  { id: "24h", label: "24h" },
  { id: "30d", label: "30d" },
] as const;

export const SOURCE_OPTIONS: SourceType[] = ["telco", "bank", "gov", "osint", "infra"];

export const sourceLabel = (source: SourceType) => source.toUpperCase();
