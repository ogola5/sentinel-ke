import type { EntityProfile, SourceType } from "../types/domain";
import {
  SCREEN_CHROME,
  SCREEN_GUIDES,
  SOURCE_OPTIONS,
  TIME_WINDOWS,
  sourceLabel,
  type ScreenId,
} from "./navigation";

export default function Topbar({
  activeScreen,
  sourceFilters,
  timeWindow,
  entityQuery,
  entities,
  inspectorOpen,
  assistantOpen,
  onToggleSource,
  onSelectTimeWindow,
  onEntityQueryChange,
  onApplyEntityExample,
  onInvestigateEntity,
  onOpenNextScreen,
  onOpenInspector,
  onToggleAssistant,
}: {
  activeScreen: ScreenId;
  sourceFilters: Record<SourceType, boolean>;
  timeWindow: string;
  entityQuery: string;
  entities: EntityProfile[];
  inspectorOpen: boolean;
  assistantOpen: boolean;
  onToggleSource: (source: SourceType) => void;
  onSelectTimeWindow: (id: string) => void;
  onEntityQueryChange: (query: string) => void;
  onApplyEntityExample: (value: string) => void;
  onInvestigateEntity: (entity: EntityProfile) => void;
  onOpenNextScreen: (screen: ScreenId) => void;
  onOpenInspector: () => void;
  onToggleAssistant: () => void;
}) {
  const chrome = SCREEN_CHROME[activeScreen];
  const guide = SCREEN_GUIDES[activeScreen];
  const showSourceFilters = Boolean(chrome.showSourceFilters);
  const showTimeWindow = Boolean(chrome.showTimeWindow);
  const showEntitySearch = Boolean(chrome.showEntitySearch);
  const sampleInputs = showEntitySearch ? guide.sampleInputs ?? [] : [];
  const normalizedQuery = entityQuery.trim().toLowerCase();
  const matchedEntity = normalizedQuery
    ? entities.find((item) => item.label.toLowerCase() === normalizedQuery)
      ?? entities.find((item) => item.id.toLowerCase() === normalizedQuery)
      ?? entities.find((item) => item.label.toLowerCase().includes(normalizedQuery))
      ?? entities.find((item) => item.id.toLowerCase().includes(normalizedQuery))
    : null;

  return (
    <header className="topbar">
      <div className="topbar-screen">
        <p className="topbar-label">Current view</p>
        <div className="topbar-screen-title">{chrome.title}</div>
        <p className="topbar-screen-subtitle">{chrome.subtitle}</p>
      </div>

      <div className="topbar-controls">
        {showSourceFilters && (
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

        {showTimeWindow && (
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

        {showEntitySearch && (
          <div className="topbar-group topbar-search">
            <p className="topbar-label">{chrome.entitySearchLabel ?? "Entity"}</p>
            <div className="topbar-search-row">
              <input
                className="search"
                list="entity-options"
                placeholder={chrome.entitySearchPlaceholder ?? "Search entities…"}
                value={entityQuery}
                onChange={(event) => {
                  onEntityQueryChange(event.target.value);
                }}
              />
              <button
                className="chip active"
                type="button"
                onClick={() => {
                  if (matchedEntity) {
                    onInvestigateEntity(matchedEntity);
                  }
                }}
                disabled={!matchedEntity}
                title={matchedEntity ? `Open ${matchedEntity.label}` : "Choose or type a known entity first"}
              >
                Investigate
              </button>
            </div>
            {sampleInputs.length > 0 && (
              <div className="chip-row topbar-example-row">
                <span className="topbar-example-label">Try</span>
                {sampleInputs.map((item) => (
                  <button
                    key={`${activeScreen}:${item.value}`}
                    className="chip ghost"
                    type="button"
                    onClick={() => onApplyEntityExample(item.value)}
                    title={item.value}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
            <datalist id="entity-options">
              {entities.map((entity) => (
                <option key={entity.id} value={entity.id} label={entity.label} />
              ))}
            </datalist>
          </div>
        )}

        <div className="topbar-end">
          {guide.nextScreen && (
            <button
              className="chip ghost"
              type="button"
              onClick={() => onOpenNextScreen(guide.nextScreen!)}
              title={`Open ${SCREEN_CHROME[guide.nextScreen].title}`}
            >
              Next: {SCREEN_CHROME[guide.nextScreen].title}
            </button>
          )}
          <button className={assistantOpen ? "chip active" : "chip ghost"} type="button" onClick={onToggleAssistant} title="Open platform assistant">
            Assistant
          </button>
          {!inspectorOpen && (
            <button className="chip ghost" type="button" onClick={onOpenInspector} title="Open entity inspector">
              Inspector
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
