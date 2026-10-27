import { ListChecks, Minimize2 } from "lucide-react";

import "./meeting.css";

import AgendaHomeLink from "../AgendaHomeLink";
import SaveStatus from "./SaveStatus";

// Barre fine et collante du mode concentration : titre, état d'enregistrement, nombre de mots, ordre du jour,
// « Terminer » et « Accueil → » tout à droite.
export default function FocusBar({
  title,
  words,
  saveProps,
  agendaOpen,
  hasAgenda,
  onToggleAgenda,
  onExit,
}) {
  return (
    <div className="ag-focus-bar" role="region" aria-label="Barre du mode concentration">
      <p className="ag-focus-title" title={title}>
        {title || "Réunion"}
      </p>
      <SaveStatus {...saveProps} />
      <span className="ag-focus-words">
        {words} mot{words > 1 ? "s" : ""}
      </span>
      {hasAgenda ? (
        <button
          type="button"
          className="ag-button ag-button--secondary ag-button--small"
          aria-pressed={agendaOpen}
          aria-controls="ordre-du-jour"
          onClick={onToggleAgenda}
        >
          <ListChecks size={14} aria-hidden="true" />
          Ordre du jour
        </button>
      ) : null}
      <button type="button" className="ag-button ag-button--small" onClick={onExit}>
        <Minimize2 size={14} aria-hidden="true" />
        Terminer
      </button>
      <AgendaHomeLink compact />
    </div>
  );
}

export { FocusBar };
