import { Check, CircleAlert } from "lucide-react";

import "@/Agenda.css";

import { joinClasses } from "./calendarHelpers";

// Case à cocher native stylée (charte Agenda.css).
export function FormCheckbox({ checked, onChange, label, help = null, disabled = false, id, describedBy }) {
  return (
    <label className={joinClasses("ag-checkbox", disabled ? "is-disabled" : "")}>
      <input
        id={id}
        type="checkbox"
        className="ag-check-input"
        checked={checked}
        disabled={disabled}
        aria-describedby={describedBy}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="ag-check-mark" aria-hidden="true">
        <Check size={12} strokeWidth={3} />
      </span>
      <span className="ag-check-text">
        {label}
        {help ? <small>{help}</small> : null}
      </span>
    </label>
  );
}

// Interrupteur natif (role="switch") stylé.
export function FormSwitch({ checked, onChange, label, disabled = false, id, describedBy }) {
  return (
    <label className={joinClasses("ag-switch", disabled ? "is-disabled" : "")}>
      <input
        id={id}
        type="checkbox"
        role="switch"
        className="ag-check-input"
        checked={checked}
        disabled={disabled}
        aria-describedby={describedBy}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="ag-switch-track" aria-hidden="true" />
      <span className="ag-switch-label">{label}</span>
    </label>
  );
}

// Message d'erreur sous un champ (annoncé par les lecteurs d'écran).
export function FieldError({ id, message }) {
  if (!message) return null;
  return (
    <p className="ag-field-error" id={id} role="alert">
      <CircleAlert size={14} aria-hidden="true" />
      {message}
    </p>
  );
}

// Bandeau d'erreur général d'un formulaire.
export function FormBanner({ message }) {
  if (!message) return null;
  return (
    <div className="ag-error" role="alert">
      <span className="ag-error-text">
        <CircleAlert size={15} aria-hidden="true" />
        {message}
      </span>
    </div>
  );
}

// Compteur « 120 / 500 » sous un champ texte.
export function Counter({ value, max }) {
  const length = (value || "").length;
  return (
    <span className={joinClasses("ag-counter", length > max ? "is-over" : "")} aria-hidden="true">
      {length} / {max}
    </span>
  );
}
