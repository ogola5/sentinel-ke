import type { EntityProfile, SourceType } from "../types/domain";
import {
  SOURCE_OPTIONS,
  TIME_WINDOWS,
  sourceLabel,
  type NavItem,
  type ScreenId,
  type WorkspaceItem,
} from "./navigation";

const DATA_SCREENS = new Set<ScreenId>(["live", "timeline", "graph", "campaigns", "infra"]);
const ENTITY_SCREENS = new Set<ScreenId>(["live", "timeline", "graph", "campaigns", "infra", "gnn", "cases"]);

export default function Topbar({
  activeScreen,
  activeWorkspace,
  workspaceScreens,
  sourceFilters,
  timeWindow,
  entityQuery,
  entities,
  inspectorOpen,
  onSelectScreen,
  onToggleSource,
  onSelectTimeWindow,
  onEntityQueryChange,
  onSelectEntity,
  onOpenInspector,
}: {
  activeScreen: ScreenId;
  activeWorkspace: WorkspaceItem;
  workspaceScreens: NavItem[];
  sourceFilters: Record<SourceType, boolean>;
  timeWindow: string;
  entityQuery: string;
  entities: EntityProfile[];
  inspectorOpen: boolean;
  onSelectScreen: (id: ScreenId) => void;
  onToggleSource: (source: SourceType) => void;
  onSelectTimeWindow: (id: string) => void;
  onEntityQueryChange: (query: string) => void;
  onSelectEntity: (entity: EntityProfile) => void;
  onOpenInspector: () => void;
}) {
  const showDataControls = DATA_SCREENS.has(activeScreen);
  const showEntitySearch = ENTITY_SCREENS.has(activeScreen);
  const ActiveIcon = activeWorkspace.Icon;

  return (
    <header className="topbar topbar-lean">
      <div className="topbar-main">
        <div className="topbar-context">
          <p className="topbar-label">Workspace</p>
          <div className="topbar-workspace-line">
            <span className="topbar-workspace-icon" style={{ color: activeWorkspace.color }}>
              <ActiveIcon size={16} />
            </span>
            <div>
              <div className="topbar-current-title">{activeWorkspace.label}</div>
              <div className="topbar-current-sub">{activeWorkspace.description}</div>
            </div>
          </div>
        </div>

        <div className="topbar-end">
          {!inspectorOpen && (
            <button className="chip ghost" type="button" onClick={onOpenInspector} title="Open entity inspector">
              Inspector
            </button>
          )}
        </div>
      </div>

      {workspaceScreens.length > 0 && (
        <div className="workspace-tabs" role="tablist" aria-label={`${activeWorkspace.label} sections`}>
          {workspaceScreens.map((screen) => {
            const { Icon } = screen;
            const isActive = screen.id === activeScreen;
            return (
              <button
                key={screen.id}
                type="button"
                className={`workspace-tab${isActive ? " active" : ""}`}
                onClick={() => onSelectScreen(screen.id as ScreenId)}
                role="tab"
                aria-selected={isActive}
              >
                <Icon size={14} />
                <span>{screen.label}</span>
              </button>
            );
          })}
        </div>
      )}

      {(showDataControls || showEntitySearch) && (
        <div className="topbar-controls">
          {showDataControls && (
            <>
              <div className="topbar-group">
                <p className="topbar-label">Sources</p>
                <div className="chip-row">
                  {SOURCE_OPTIONS.map((source) => (
                    <button
                      key={source}
                      className={sourceFilters[source] ? "chip active" : "chip ghost"}
                      type="button"
                      onClick={() => onToggleSource(source)}
                    >
                      {sourceLabel(source)}
                    </button>
                  ))}
                </div>
              </div>

              <div className="topbar-group">
                <p className="topbar-label">Window</p>
                <div className="chip-row">
                  {TIME_WINDOWS.map((windowOption) => (
                    <button
                      key={windowOption.id}
                      className={timeWindow === windowOption.id ? "chip active" : "chip ghost"}
                      type="button"
                      onClick={() => onSelectTimeWindow(windowOption.id)}
                    >
                      {windowOption.label}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}

          {showEntitySearch && (
            <div className="topbar-group topbar-search">
              <p className="topbar-label">Entity</p>
              <input
                className="search"
                list="entity-options"
                placeholder="Search entities…"
                value={entityQuery}
                onChange={(event) => {
                  onEntityQueryChange(event.target.value);
                  const entity = entities.find((item) => item.label === event.target.value);
                  if (entity) onSelectEntity(entity);
                }}
              />
              <datalist id="entity-options">
                {entities.map((entity) => (
                  <option key={entity.label} value={entity.label} />
                ))}
              </datalist>
            </div>
          )}
        </div>
      )}
    </header>
  );
}
