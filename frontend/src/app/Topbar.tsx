import type { EntityProfile, SourceType } from "../types/domain";
import { SOURCE_OPTIONS, TIME_WINDOWS, sourceLabel, type ScreenId } from "./navigation";

// Screens where data-source filters and time window are meaningful
const DATA_SCREENS = new Set<ScreenId>(["live", "timeline", "graph", "campaigns", "infra"]);

export default function Topbar({
  activeScreen,
  sourceFilters,
  timeWindow,
  entityQuery,
  entities,
  inspectorOpen,
  onToggleSource,
  onSelectTimeWindow,
  onEntityQueryChange,
  onSelectEntity,
  onOpenInspector,
}: {
  activeScreen: ScreenId;
  sourceFilters: Record<SourceType, boolean>;
  timeWindow: string;
  entityQuery: string;
  entities: EntityProfile[];
  inspectorOpen: boolean;
  onToggleSource: (source: SourceType) => void;
  onSelectTimeWindow: (id: string) => void;
  onEntityQueryChange: (query: string) => void;
  onSelectEntity: (entity: EntityProfile) => void;
  onOpenInspector: () => void;
}) {
  const showDataControls = DATA_SCREENS.has(activeScreen);

  return (
    <header className="topbar">
      {showDataControls && (
        <div className="topbar-group">
          <p className="topbar-label">Source</p>
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
      )}

      {showDataControls && (
        <div className="topbar-group">
          <p className="topbar-label">Window</p>
          <div className="chip-row">
            {TIME_WINDOWS.map((w) => (
              <button
                key={w.id}
                className={timeWindow === w.id ? "chip active" : "chip ghost"}
                type="button"
                onClick={() => onSelectTimeWindow(w.id)}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>
      )}

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
            if (entity) {
              onSelectEntity(entity);
            }
          }}
        />
        <datalist id="entity-options">
          {entities.map((entity) => (
            <option key={entity.label} value={entity.label} />
          ))}
        </datalist>
      </div>

      <div className="topbar-end">
        {!inspectorOpen && (
          <button className="chip ghost" type="button" onClick={onOpenInspector} title="Open entity inspector">
            Inspector
          </button>
        )}
      </div>
    </header>
  );
}
