import { useId } from "react";
import { BellRing, Check, CircleAlert, Info, TriangleAlert } from "lucide-react";

import "@/Agenda.css";

import { DEFAULT_DAY_REMINDER_TIME, OFFSETS, OFFSET_KEYS } from "./agendaConstants";
import { isReminderPast, isTime } from "./dateUtils";

function currentValue(value) {
  const source = value && typeof value === "object" ? value : {};
  const offsets = Array.isArray(source.offsets) ? OFFSET_KEYS.filter((key) => source.offsets.includes(key)) : [];
  return { enabled: Boolean(source.enabled), offsets, ping_role: Boolean(source.ping_role) };
}

// Ligne d'état sous la section : configuration absente, coupée, ou salon utilisé.
function SettingsNotice({ settings }) {
  if (!settings) return null;
  if (settings.disabled_by_env) {
    return (
      <p className="ag-callout ag-callout--info">
        <Info size={15} aria-hidden="true" />
        <span>Les rappels Discord sont désactivés par la configuration du serveur : rien ne partira pour l'instant.</span>
      </p>
    );
  }
  if (settings.enabled === false) {
    return (
      <p className="ag-callout ag-callout--info">
        <Info size={15} aria-hidden="true" />
        <span>Les rappels Discord sont désactivés pour le moment : ils partiront quand un responsable les réactivera.</span>
      </p>
    );
  }
  if (!settings.configured) {
    return (
      <p className="ag-callout ag-callout--info">
        <Info size={15} aria-hidden="true" />
        <span>Les rappels Discord ne sont pas encore configurés : ils partiront dès qu'un responsable aura choisi le salon.</span>
      </p>
    );
  }
  if (settings.channel_status === "inaccessible") {
    return (
      <p className="ag-callout ag-callout--warning">
        <TriangleAlert size={15} aria-hidden="true" />
        <span>Le salon des rappels est inaccessible pour le moment : un responsable doit vérifier les réglages.</span>
      </p>
    );
  }
  return (
    <p className="ag-help">
      {settings.channel_name ? `Dans #${settings.channel_name} · heure de Paris` : "Heure de Paris"}
    </p>
  );
}

// Section « Rappels Discord » des formulaires d'entrée et de réunion.
// `value` = { enabled, offsets, ping_role } ; onChange reçoit le même format (sans `schedule`).
export default function ReminderFields({
  value,
  onChange,
  allDay = false,
  startDate = "",
  startTime = "",
  canPing = false,
  settings = null,
  disabled = false,
  error = null,
  title = "Rappels Discord",
}) {
  const baseId = `ag-reminders-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const current = currentValue(value);
  const dayTime = isTime(settings?.day_reminder_time) ? settings.day_reminder_time : DEFAULT_DAY_REMINDER_TIME;
  const timed = !allDay && isTime(startTime);
  const errorId = error ? `${baseId}-error` : undefined;

  const emit = (patch) => {
    if (!onChange) return;
    const next = { ...current, ...patch };
    onChange({
      enabled: Boolean(next.enabled),
      offsets: OFFSET_KEYS.filter((key) => next.offsets.includes(key)),
      ping_role: Boolean(next.ping_role),
    });
  };

  const toggleEnabled = (checked) => {
    if (checked && current.offsets.length === 0) {
      emit({ enabled: true, offsets: [...OFFSET_KEYS] });
      return;
    }
    emit({ enabled: checked });
  };

  const toggleOffset = (key, checked) => {
    const offsets = checked ? [...current.offsets, key] : current.offsets.filter((item) => item !== key);
    emit({ offsets });
  };

  const pingLocked = !canPing;
  const roleMissing = canPing && settings && settings.ping_role_configured === false;

  return (
    <fieldset className="ag-fieldset ag-reminders" disabled={disabled} aria-describedby={errorId}>
      <legend className="ag-legend">
        <BellRing size={16} aria-hidden="true" />
        {title}
      </legend>

      <label className={`ag-switch${disabled ? " is-disabled" : ""}`} htmlFor={`${baseId}-enabled`}>
        <input
          id={`${baseId}-enabled`}
          type="checkbox"
          role="switch"
          className="ag-check-input"
          checked={current.enabled}
          onChange={(event) => toggleEnabled(event.target.checked)}
        />
        <span className="ag-switch-track" aria-hidden="true" />
        <span className="ag-switch-label">Envoyer des rappels sur Discord</span>
      </label>

      {current.enabled ? (
        <>
          <fieldset className="ag-reminder-offsets">
            <legend className="ag-sr-only">Quand envoyer les rappels</legend>
            {OFFSETS.map((offset) => {
              const unavailable = offset.needsTime && !timed;
              const checked = !unavailable && current.offsets.includes(offset.key);
              const past =
                !unavailable && isReminderPast(offset.key, startDate, timed ? startTime : null, { dayTime });
              const inputId = `${baseId}-${offset.key}`;
              const helpId = unavailable ? `${baseId}-${offset.key}-help` : undefined;
              const classes = [
                "ag-check-pill",
                checked ? "is-checked" : "",
                past ? "is-past" : "",
                unavailable ? "is-disabled" : "",
              ]
                .filter(Boolean)
                .join(" ");
              return (
                <label
                  key={offset.key}
                  className={classes}
                  htmlFor={inputId}
                  title={unavailable ? "Disponible seulement pour un élément avec une heure" : undefined}
                >
                  <input
                    id={inputId}
                    type="checkbox"
                    className="ag-check-input"
                    checked={checked}
                    disabled={unavailable}
                    aria-describedby={helpId}
                    onChange={(event) => toggleOffset(offset.key, event.target.checked)}
                  />
                  <span className="ag-check-mark" aria-hidden="true">
                    <Check size={12} strokeWidth={3} />
                  </span>
                  <span>
                    <strong>{offset.shortLabel}</strong> <small>{offset.label}</small>
                  </span>
                  {past ? <em className="ag-check-pill-note">déjà passé</em> : null}
                </label>
              );
            })}
          </fieldset>
          {!timed ? (
            <p className="ag-help" id={`${baseId}-H-1-help`}>
              H-1 : disponible seulement pour un élément avec une heure.
            </p>
          ) : null}
          {current.offsets.filter((key) => key !== "H-1" || timed).length === 0 ? (
            <p className="ag-help">Aucun palier choisi : aucun rappel ne partira.</p>
          ) : null}

          <div className="ag-reminder-options">
            <label className={`ag-checkbox${pingLocked || disabled ? " is-disabled" : ""}`} htmlFor={`${baseId}-ping`}>
              <input
                id={`${baseId}-ping`}
                type="checkbox"
                className="ag-check-input"
                checked={current.ping_role}
                disabled={pingLocked}
                aria-describedby={pingLocked || roleMissing ? `${baseId}-ping-help` : undefined}
                onChange={(event) => emit({ ping_role: event.target.checked })}
              />
              <span className="ag-check-mark" aria-hidden="true">
                <Check size={12} strokeWidth={3} />
              </span>
              <span className="ag-check-text">
                Mentionner le rôle
                {pingLocked ? (
                  <small id={`${baseId}-ping-help`}>Réservé aux responsables</small>
                ) : roleMissing ? (
                  <small id={`${baseId}-ping-help`}>Aucun rôle à mentionner n'est encore configuré.</small>
                ) : null}
              </span>
            </label>
          </div>
        </>
      ) : null}

      {settings || error ? (
        <div className="ag-reminder-options">
          <SettingsNotice settings={settings} />
          {error ? (
            <p className="ag-field-error" id={errorId} role="alert">
              <CircleAlert size={14} aria-hidden="true" />
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </fieldset>
  );
}

export { ReminderFields };
