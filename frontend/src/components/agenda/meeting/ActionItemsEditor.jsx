import { useState } from "react";
import { Check, Plus, X } from "lucide-react";

import "./meeting.css";

import PeoplePicker from "../PeoplePicker";
import { PersonLabel } from "../HelperAvatar";
import { Pill } from "../TypeBadge";
import { TEXT_LIMITS } from "../agendaConstants";
import { formatDayShort, formatInstant, isIsoDate } from "../dateUtils";
import { newAction, setItemText } from "./meetingModel";

// Actions à suivre : case faite, texte, responsable, échéance. Quand la réunion est verrouillée (`readOnly`),
// tout est en lecture seule sauf la case « faite » (`onToggleDone`).
export default function ActionItemsEditor({ items, onChange, onToggleDone, readOnly = false, today = "", busyIds }) {
  const [draft, setDraft] = useState("");
  const full = items.length >= TEXT_LIMITS.listItems;

  const patchItem = (id, patch) => onChange(items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  const rename = (id, value) =>
    onChange(items.map((item) => (item.id === id ? setItemText(item, "text", value) : item)));
  const remove = (id) => onChange(items.filter((item) => item.id !== id));
  const settle = (item) => {
    if (item.text.trim()) return;
    if (item.lastText) patchItem(item.id, { text: item.lastText });
    else remove(item.id);
  };

  const addDraft = () => {
    const text = draft.trim();
    if (!text || full) return;
    onChange([...items, setItemText(newAction(text), "text", text)]);
    setDraft("");
  };

  const open = items.filter((item) => !item.done).length;

  return (
    <div className="ag-meeting-actions">
      {items.length ? (
        <>
          <p className="ag-meeting-progress" aria-live="polite">
            {open === 0 ? "Toutes les actions sont faites." : `${open} action${open > 1 ? "s" : ""} à suivre sur ${items.length}`}
          </p>
          <ul className="ag-meeting-action-list">
            {items.map((item, index) => {
              const late = !item.done && isIsoDate(item.due_date) && isIsoDate(today) && item.due_date < today;
              const busy = Boolean(busyIds?.has(item.id));
              return (
                <li key={item.id} className={`ag-meeting-action${item.done ? " is-done" : ""}`}>
                  <label className="ag-checkbox ag-meeting-action-check">
                    <input
                      type="checkbox"
                      className="ag-check-input"
                      checked={item.done}
                      disabled={busy}
                      onChange={(event) => onToggleDone(item, event.target.checked)}
                      aria-label={`Action faite : ${item.text || "sans texte"}`}
                    />
                    <span className="ag-check-mark" aria-hidden="true">
                      <Check size={12} strokeWidth={3} />
                    </span>
                  </label>
                  <div className="ag-meeting-action-main">
                    {readOnly ? (
                      <span className="ag-meeting-point-text">{item.text}</span>
                    ) : (
                      <input
                        type="text"
                        className="ag-input"
                        value={item.text}
                        maxLength={TEXT_LIMITS.action}
                        aria-label={`Texte de l'action ${index + 1}`}
                        onChange={(event) => rename(item.id, event.target.value)}
                        onBlur={() => settle(item)}
                      />
                    )}
                    {item.done && item.done_at ? (
                      <small className="ag-meeting-action-done">
                        Fait le {formatInstant(item.done_at, { withTime: false })}
                        {item.done_by ? ` par ${item.done_by.display_name || item.done_by.username}` : ""}
                      </small>
                    ) : null}
                  </div>
                  <div className="ag-meeting-action-who">
                    {readOnly ? (
                      item.assignee ? (
                        <PersonLabel person={item.assignee} size={22} />
                      ) : (
                        <span className="ag-meeting-muted">Non attribuée</span>
                      )
                    ) : (
                      <PeoplePicker
                        mode="single"
                        size="sm"
                        selected={item.assignee}
                        onChange={(next) => patchItem(item.id, { assignee: next || null })}
                        align="end"
                      />
                    )}
                  </div>
                  <div className="ag-meeting-action-due">
                    {readOnly ? (
                      item.due_date ? (
                        <Pill tone={late ? "danger" : "neutral"} size="sm">
                          {late ? "En retard · " : "Pour le "}
                          {formatDayShort(item.due_date)}
                        </Pill>
                      ) : (
                        <span className="ag-meeting-muted">Sans échéance</span>
                      )
                    ) : (
                      <>
                        <input
                          type="date"
                          className="ag-input ag-meeting-date"
                          value={item.due_date || ""}
                          aria-label={`Échéance de l'action ${index + 1}`}
                          aria-invalid={late || undefined}
                          onChange={(event) => patchItem(item.id, { due_date: event.target.value })}
                        />
                        {late ? <small className="ag-meeting-late">En retard</small> : null}
                      </>
                    )}
                  </div>
                  {readOnly ? null : (
                    <button
                      type="button"
                      className="ag-icon-button ag-icon-button--small ag-icon-button--danger"
                      aria-label={`Retirer l'action ${index + 1}`}
                      onClick={() => remove(item.id)}
                    >
                      <X size={15} aria-hidden="true" />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <p className="ag-meeting-empty">Aucune action à suivre pour l'instant.</p>
      )}
      {readOnly ? null : (
        <div className="ag-meeting-add">
          <input
            type="text"
            className="ag-input"
            value={draft}
            maxLength={TEXT_LIMITS.action}
            placeholder={full ? "50 actions au maximum" : "Ajouter une action"}
            aria-label="Ajouter une action"
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
            Ajouter une action
          </button>
        </div>
      )}
    </div>
  );
}

export { ActionItemsEditor };
