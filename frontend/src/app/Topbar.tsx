import type { EntityProfile, SourceType } from "../types/domain";
import { SOURCE_OPTIONS, sourceLabel } from "./navigation";

export default function Topbar({
  sourceFilters,
  entityQuery,
  entities,
  onToggleSource,
  onEntityQueryChange,
  onSelectEntity,
}: {
  sourceFilters: Record<SourceType, boolean>;
  entityQuery: string;
  entities: EntityProfile[];
  onToggleSource: (source: SourceType) => void;
  onEntityQueryChange: (query: string) => void;
  onSelectEntity: (entity: EntityProfile) => void;
}) {
  return (
    <header className="topbar">
      <div className="topbar-group">
        <p className="label" style={{ fontSize: "0.65rem" }}>
          Source filter
        </p>
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
        <p className="label" style={{ fontSize: "0.65rem" }}>
          Entity search
        </p>
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
      <div className="topbar-group align-right" />
    </header>
  );
}
