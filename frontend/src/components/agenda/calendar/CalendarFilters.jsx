import "@/Agenda.css";

import { TYPE_ORDER, typeMeta } from "../agendaConstants";
import { isFilterActive } from "../calendarModel";
import { TypeDot, typeClass } from "../TypeBadge";
import { joinClasses } from "./calendarHelpers";
import "./agenda-calendar.css";

// Filtres du calendrier : une pastille par type (avec le nombre d'éléments de la période),
// « Seulement moi » et « Réinitialiser » quand un filtre est actif.
export default function CalendarFilters({ filters, counts, onToggleType, onToggleMine, onReset }) {
  const active = isFilterActive(filters);
  return (
    <div className="ag-cal-filterbar">
      <div className="ag-filters" role="group" aria-label="Types d'éléments affichés">
        {TYPE_ORDER.map((type) => {
          const selected = filters.types.includes(type);
          const count = counts?.[type] || 0;
          return (
            <button
              key={type}
              type="button"
              className={joinClasses("ag-chip", typeClass(type), selected ? "is-selected" : "")}
              aria-pressed={selected}
              onClick={() => onToggleType(type)}
            >
              <TypeDot type={type} />
              {typeMeta(type).pluralLabel}
              <span className="ag-chip-count" aria-label={`${count} sur la période`}>
                {count}
              </span>
            </button>
          );
        })}
      </div>
      <div className="ag-cal-filter-side">
        <label className="ag-switch">
          <input
            type="checkbox"
            role="switch"
            className="ag-check-input"
            checked={filters.onlyMine}
            onChange={(event) => onToggleMine(event.target.checked)}
          />
          <span className="ag-switch-track" aria-hidden="true" />
          <span className="ag-switch-label">Seulement moi</span>
        </label>
        {active ? (
          <button type="button" className="ag-link-button" onClick={onReset}>
            Réinitialiser
          </button>
        ) : null}
      </div>
    </div>
  );
}

export { CalendarFilters };
