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

export const NAV_SENSE = [
  { id: "live", label: "National Live Feed", Icon: Radio, tag: "S1" },
  { id: "timeline", label: "Service Indicators", Icon: Activity, tag: "S2" },
] as const;

export const NAV_ANALYZE = [
  { id: "graph", label: "Threat Graph", Icon: Network, tag: "S3" },
  { id: "investigate", label: "Entity Investigation", Icon: AlertTriangle, tag: "S14" },
  { id: "gnn", label: "GNN Intelligence", Icon: Brain, tag: "S8" },
  { id: "crypto", label: "Crypto Posture", Icon: Lock, tag: "S9" },
] as const;

export const NAV_ATTRIBUTE = [
  { id: "campaigns", label: "Campaign Console", Icon: Flag, tag: "S4" },
  { id: "infra", label: "Infra Correlation", Icon: Server, tag: "S5" },
] as const;

export const NAV_RESPOND = [
  { id: "cases", label: "Case Packets + STIX", Icon: FileText, tag: "S6" },
  { id: "defense", label: "Defense Center", Icon: Shield, tag: "S10" },
] as const;

export const NAV_GOVERN = [
  { id: "ops", label: "Operations Center", Icon: BarChart2, tag: "S7" },
  { id: "corruption", label: "Corruption Intel", Icon: Building2, tag: "S11" },
  { id: "federation", label: "Federation Network", Icon: Globe, tag: "S12" },
  { id: "audit", label: "Audit Log", Icon: BookOpen, tag: "S13" },
] as const;

export const NAV_COMMAND = [
  { id: "exec", label: "Crisis Brief", Icon: AlertTriangle, tag: "C0" },
  { id: "command", label: "National Command", Icon: Cpu, tag: "C1" },
  { id: "onboard", label: "Agency Onboarding", Icon: Zap, tag: "C2" },
  { id: "users", label: "User Management", Icon: Users, tag: "C3" },
] as const;

export type ScreenId =
  | (typeof NAV_SENSE)[number]["id"]
  | (typeof NAV_ANALYZE)[number]["id"]
  | (typeof NAV_ATTRIBUTE)[number]["id"]
  | (typeof NAV_RESPOND)[number]["id"]
  | (typeof NAV_GOVERN)[number]["id"]
  | (typeof NAV_COMMAND)[number]["id"]
  | "onboard";

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
