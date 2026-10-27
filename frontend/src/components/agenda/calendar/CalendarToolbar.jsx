import { useRef } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import "@/Agenda.css";

import { AGENDA_VIEWS, VIEW_LABELS } from "../agendaConstants";
import "./agenda-calendar.css";

// Barre d'outils du calendrier : période précédente / suivante, « Aujourd'hui », titre et choix de la vue.
export default function CalendarToolbar({ title, view, onViewChange, onPrevious, onNext, onToday }) {
  const groupRef = useRef(null);

  // Flèches : on passe à la vue voisine et le focus la suit (groupe de boutons radio).
  const handleKeyDown = (event) => {
    const index = AGENDA_VIEWS.indexOf(view);
    let next = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = AGENDA_VIEWS[(index + 1) % AGENDA_VIEWS.length];
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      next = AGENDA_VIEWS[(index - 1 + AGENDA_VIEWS.length) % AGENDA_VIEWS.length];
    }
    if (event.key === "Home") next = AGENDA_VIEWS[0];
    if (event.key === "End") next = AGENDA_VIEWS[AGENDA_VIEWS.length - 1];
    if (!next) return;
    event.preventDefault();
    onViewChange(next);
    const buttons = groupRef.current ? groupRef.current.querySelectorAll('[role="radio"]') : [];
    const target = buttons[AGENDA_VIEWS.indexOf(next)];
    if (target) target.focus();
  };

  return (
    <div className="ag-toolbar ag-cal-toolbar">
      <div className="ag-cal-nav">
        <button
          type="button"
          className="ag-icon-button ag-icon-button--small"
          aria-label="Période précédente"
          onClick={onPrevious}
        >
          <ChevronLeft size={18} aria-hidden="true" />
        </button>
        <button type="button" className="ag-button ag-button--secondary ag-button--small" onClick={onToday}>
          Aujourd'hui
        </button>
        <button
          type="button"
          className="ag-icon-button ag-icon-button--small"
          aria-label="Période suivante"
          onClick={onNext}
        >
          <ChevronRight size={18} aria-hidden="true" />
        </button>
      </div>
      <h2 className="ag-cal-title" aria-live="polite">
        {title}
      </h2>
      <div
        ref={groupRef}
        className="ag-segmented ag-cal-views"
        role="radiogroup"
        aria-label="Affichage du calendrier"
        onKeyDown={handleKeyDown}
      >
        {AGENDA_VIEWS.map((key) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={view === key}
            tabIndex={view === key ? 0 : -1}
            onClick={() => onViewChange(key)}
          >
            {VIEW_LABELS[key]}
          </button>
        ))}
      </div>
    </div>
  );
}

export { CalendarToolbar };
