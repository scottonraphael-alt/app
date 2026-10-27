import { useState } from "react";
import { Plus, X } from "lucide-react";

import "./meeting.css";

import { TEXT_LIMITS } from "../agendaConstants";
import { newDecision, setItemText } from "./meetingModel";

// Décisions : liste numérotée de textes modifiables.
export default function DecisionsEditor({ items, onChange, readOnly = false }) {
  const [draft, setDraft] = useState("");
  const full = items.length >= TEXT_LIMITS.listItems;

  const rename = (id, value) =>
    onChange(items.map((item) => (item.id === id ? setItemText(item, "text", value) : item)));
  const remove = (id) => onChange(items.filter((item) => item.id !== id));
  const settle = (item) => {
    if (item.text.trim()) return;
    if (item.lastText) onChange(items.map((entry) => (entry.id === item.id ? { ...entry, text: item.lastText } : entry)));
    else remove(item.id);
  };

  const addDraft = () => {
    const text = draft.trim();
    if (!text || full) return;
    onChange([...items, setItemText(newDecision(text), "text", text)]);
    setDraft("");
  };

  return (
    <div className="ag-meeting-decisions">
      {items.length ? (
        <ol className="ag-meeting-decision-list">
          {items.map((item, index) => (
            <li key={item.id} className="ag-meeting-decision">
              <span className="ag-meeting-decision-number" aria-hidden="true">
                {index + 1}
              </span>
              {readOnly ? (
                <span className="ag-meeting-point-text">{item.text}</span>
              ) : (
                <>
                  <input
                    type="text"
                    className="ag-input"
                    value={item.text}
                    maxLength={TEXT_LIMITS.decision}
                    aria-label={`Décision ${index + 1}`}
                    onChange={(event) => rename(item.id, event.target.value)}
                    onBlur={() => settle(item)}
                  />
                  <button
                    type="button"
                    className="ag-icon-button ag-icon-button--small ag-icon-button--danger"
                    aria-label={`Retirer la décision ${index + 1}`}
                    onClick={() => remove(item.id)}
                  >
                    <X size={15} aria-hidden="true" />
                  </button>
                </>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <p className="ag-meeting-empty">{readOnly ? "Aucune décision enregistrée." : "Aucune décision pour l'instant."}</p>
      )}
      {readOnly ? null : (
        <div className="ag-meeting-add">
          <input
            type="text"
            className="ag-input"
            value={draft}
            maxLength={TEXT_LIMITS.decision}
            placeholder={full ? "50 décisions au maximum" : "Ajouter une décision"}
            aria-label="Ajouter une décision"
            disabled={full}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addDraft();
              }
            }}
          />
          <button
            type="button"
            className="ag-button ag-button--secondary ag-button--small"
            onClick={addDraft}
            disabled={full || !draft.trim()}
          >
            <Plus size={14} aria-hidden="true" />
            Ajouter une décision
          </button>
        </div>
      )}
    </div>
  );
}

export { DecisionsEditor };
