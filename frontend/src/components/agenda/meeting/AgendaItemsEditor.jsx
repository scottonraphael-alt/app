import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Check, Plus, X } from "lucide-react";

import "./meeting.css";

import { TEXT_LIMITS } from "../agendaConstants";
import { newAgendaItem, setItemText } from "./meetingModel";

// Ordre du jour : points cochables (« abordé »), titres modifiables, réordonnables. Lecture seule si `readOnly`.
export default function AgendaItemsEditor({ items, onChange, readOnly = false }) {
  const [draft, setDraft] = useState("");
  const [focusId, setFocusId] = useState(null);
  const rowRefs = useRef(new Map());
  const full = items.length >= TEXT_LIMITS.listItems;

  useEffect(() => {
    if (!focusId) return;
    const node = rowRefs.current.get(focusId);
    if (node) node.focus();
    setFocusId(null);
  }, [focusId, items]);

  const update = (id, patch) => onChange(items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  const rename = (id, value) =>
    onChange(items.map((item) => (item.id === id ? setItemText(item, "title", value) : item)));

  const move = (index, delta) => {
    const target = index + delta;
    if (target < 0 || target >= items.length) return;
    const next = [...items];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  const remove = (id) => onChange(items.filter((item) => item.id !== id));

  // Un titre laissé vide revient au dernier texte valide, ou disparaît s'il n'a jamais eu de texte.
  const settle = (item) => {
    if (item.title.trim()) return;
    if (item.lastText) update(item.id, { title: item.lastText });
    else remove(item.id);
  };

  const addDraft = () => {
    const title = draft.trim();
    if (!title || full) return;
    const item = newAgendaItem(title);
    onChange([...items, setItemText(item, "title", title)]);
    setDraft("");
  };

  const doneCount = items.filter((item) => item.done).length;

  return (
    <div className="ag-meeting-agenda">
      {items.length ? (
        <>
          <p className="ag-meeting-progress" aria-live="polite">
            {doneCount} point{doneCount > 1 ? "s" : ""} abordé{doneCount > 1 ? "s" : ""} sur {items.length}
          </p>
          <ol className="ag-meeting-points">
            {items.map((item, index) => (
              <li key={item.id} className={`ag-meeting-point${item.done ? " is-done" : ""}`}>
                <label className="ag-checkbox ag-meeting-point-check">
                  <input
                    type="checkbox"
                    className="ag-check-input"
                    checked={item.done}
                    disabled={readOnly}
                    onChange={(event) => update(item.id, { done: event.target.checked })}
                    aria-label={`Point ${index + 1} abordé : ${item.title || "sans titre"}`}
                  />
                  <span className="ag-check-mark" aria-hidden="true">
                    <Check size={12} strokeWidth={3} />
                  </span>
                </label>
                {readOnly ? (
                  <span className="ag-meeting-point-text">{item.title}</span>
                ) : (
                  <input
                    ref={(node) => {
                      if (node) rowRefs.current.set(item.id, node);
                      else rowRefs.current.delete(item.id);
                    }}
                    type="text"
                    className="ag-input ag-meeting-point-input"
                    value={item.title}
                    maxLength={TEXT_LIMITS.agendaItem}
                    aria-label={`Titre du point ${index + 1}`}
                    onChange={(event) => rename(item.id, event.target.value)}
                    onBlur={() => settle(item)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        document.getElementById("ag-meeting-agenda-add")?.focus();
                      }
                    }}
                  />
                )}
                {readOnly ? null : (
                  <span className="ag-meeting-row-tools">
                    <button
                      type="button"
                      className="ag-icon-button ag-icon-button--small"
                      aria-label={`Monter le point ${index + 1}`}
                      disabled={index === 0}
                      onClick={() => move(index, -1)}
                    >
                      <ArrowUp size={15} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="ag-icon-button ag-icon-button--small"
                      aria-label={`Descendre le point ${index + 1}`}
                      disabled={index === items.length - 1}
                      onClick={() => move(index, 1)}
                    >
                      <ArrowDown size={15} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="ag-icon-button ag-icon-button--small ag-icon-button--danger"
                      aria-label={`Retirer le point ${index + 1}`}
                      onClick={() => remove(item.id)}
                    >
                      <X size={15} aria-hidden="true" />
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ol>
        </>
      ) : readOnly ? (
        <p className="ag-meeting-empty">Aucun point à l'ordre du jour.</p>
      ) : null}
      {readOnly ? null : (
        <div className="ag-meeting-add">
          <input
            id="ag-meeting-agenda-add"
            type="text"
            className="ag-input"
            value={draft}
            maxLength={TEXT_LIMITS.agendaItem}
            placeholder={full ? "50 points au maximum" : "Ajouter un point à l'ordre du jour"}
            aria-label="Ajouter un point"
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
            Ajouter
          </button>
        </div>
      )}
    </div>
  );
}

export { AgendaItemsEditor };
