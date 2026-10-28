import { useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import "@/Agenda.css";

import AgendaDialog from "../AgendaDialog";
import PeoplePicker from "../PeoplePicker";
import ReminderFields from "../ReminderFields";
import {
  agendaQueries,
  buildPatch,
  createEntry,
  invalidateAgenda,
  isEmptyPatch,
  updateEntry,
} from "../agendaApi";
import {
  DATE_LIMITS,
  DEFAULT_REMINDERS,
  ENTRY_TYPE_KEYS,
  SINGLE_DAY_TYPES,
  TEXT_LIMITS,
  remindersPayload,
  typeMeta,
} from "../agendaConstants";
import { splitAgendaError } from "../agendaErrors";
import { addDaysIso, daysBetween, isIsoDate, isTime, timeToMinutes } from "../dateUtils";
import { TypeIcon, typeClass } from "../TypeBadge";
import { Counter, FieldError, FormBanner, FormCheckbox } from "./FormControls";
import { joinClasses } from "./calendarHelpers";
import "./agenda-calendar.css";

const FORM_FIELDS = [
  "type",
  "custom_label",
  "title",
  "description",
  "all_day",
  "start_date",
  "end_date",
  "start_time",
  "end_time",
  "location",
  "participant_ids",
  "reminders",
  "recurrence",
];
const PATCH_KEYS = [
  "type",
  "custom_label",
  "title",
  "description",
  "all_day",
  "start_date",
  "end_date",
  "start_time",
  "end_time",
  "location",
  "participant_ids",
  "reminders",
  "recurrence",
];

const RECURRENCE_OPTIONS = [
  { value: "", label: "Ne se répète pas" },
  { value: "weekly", label: "Chaque semaine" },
  { value: "biweekly", label: "Toutes les 2 semaines" },
  { value: "monthly", label: "Chaque mois" },
];
const RECURRENCE_MIN_INTERVAL = { weekly: 7, biweekly: 14, monthly: 28 };
const RECURRENCE_MAX_DAYS = 731;

const NEW_HEADINGS = {
  evenement: "Nouvel événement",
  echeance: "Nouvelle échéance",
  rappel: "Nouveau rappel",
  permanence: "Nouvelle permanence",
  autre: "Nouvel élément",
};

function identity(person) {
  return {
    id: String(person.id),
    username: person.username || "",
    display_name: person.display_name ?? null,
    avatar_url: person.avatar_url ?? null,
  };
}

// Formulaire de départ : une entrée à modifier ou à dupliquer (`source`), ou des valeurs proposées (`defaults`).
function initialForm(source, defaults, type, today) {
  if (source) {
    // Une occurrence d'une série s'ouvre sur le début de la série (la modification vaut pour toute la série).
    let startDate = isIsoDate(source.start_date) ? source.start_date : today;
    let endDate = isIsoDate(source.end_date) ? source.end_date : "";
    if (isIsoDate(source.series_start_date) && source.series_start_date !== startDate) {
      const length = endDate ? daysBetween(startDate, endDate) : 0;
      startDate = source.series_start_date;
      endDate = length ? addDaysIso(startDate, length) : "";
    }
    return {
      recurrence_freq: source.recurrence?.freq || "",
      recurrence_until: source.recurrence?.until || "",
      type: source.type || type,
      custom_label: source.custom_label || "",
      title: source.title || "",
      description: source.description || "",
      all_day: source.all_day !== false,
      start_date: startDate,
      end_date: endDate,
      start_time: isTime(source.start_time) ? source.start_time : "",
      end_time: isTime(source.end_time) ? source.end_time : "",
      location: source.location || "",
      participants: Array.isArray(source.participants) ? source.participants.filter((p) => p && p.id).map(identity) : [],
      reminders: remindersPayload(source.reminders || DEFAULT_REMINDERS),
    };
  }
  const start = isIsoDate(defaults?.start) ? defaults.start : today;
  const end = isIsoDate(defaults?.end) && defaults.end > start ? defaults.end : "";
  const allDay = defaults?.allDay !== false;
  return {
    recurrence_freq: "",
    recurrence_until: "",
    type,
    custom_label: "",
    title: defaults?.title || "",
    description: "",
    all_day: allDay,
    start_date: start,
    end_date: end,
    start_time: allDay ? "" : defaults?.startTime || "",
    end_time: allDay ? "" : defaults?.endTime || "",
    location: "",
    participants: [],
    reminders: remindersPayload(DEFAULT_REMINDERS),
  };
}

// Valeurs telles que le serveur les stocke : la même fonction sert au document de départ et au formulaire.
function comparable(form) {
  const single = SINGLE_DAY_TYPES.includes(form.type);
  const allDay = Boolean(form.all_day);
  const endDate = !single && isIsoDate(form.end_date) && form.end_date !== form.start_date ? form.end_date : null;
  return {
    type: form.type,
    custom_label: form.type === "autre" ? form.custom_label.trim() : null,
    title: form.title.trim(),
    description: form.description.trim(),
    all_day: allDay,
    start_date: form.start_date,
    end_date: endDate,
    start_time: allDay || !isTime(form.start_time) ? null : form.start_time,
    end_time: allDay || !isTime(form.end_time) ? null : form.end_time,
    location: form.location.trim(),
    participant_ids: form.participants.map((person) => String(person.id)),
    reminders: remindersPayload(form.reminders),
    recurrence: form.recurrence_freq ? { freq: form.recurrence_freq, until: form.recurrence_until } : null,
  };
}

// `keptDate` : date déjà enregistrée, que le serveur ne revérifie pas si elle ne change pas.
function validate(form, today, keptDate) {
  const errors = {};
  const single = SINGLE_DAY_TYPES.includes(form.type);
  if (!form.title.trim()) errors.title = "Indiquez un titre.";
  else if (form.title.length > TEXT_LIMITS.title) errors.title = `Le titre est limité à ${TEXT_LIMITS.title} caractères.`;
  if (form.type === "autre") {
    const label = form.custom_label.trim();
    if (!label) errors.custom_label = "Indiquez un libellé pour ce type.";
    else if (label.length > TEXT_LIMITS.customLabel) {
      errors.custom_label = `Le libellé est limité à ${TEXT_LIMITS.customLabel} caractères.`;
    }
  }
  if (form.description.length > TEXT_LIMITS.description) {
    errors.description = `La description est limitée à ${TEXT_LIMITS.description} caractères.`;
  }
  if (form.location.length > TEXT_LIMITS.location) {
    errors.location = `Le lieu est limité à ${TEXT_LIMITS.location} caractères.`;
  }
  if (!isIsoDate(form.start_date)) {
    errors.start_date = "Indiquez une date de début valide.";
  } else if (
    form.start_date !== keptDate &&
    isIsoDate(today) &&
    (form.start_date < addDaysIso(today, -DATE_LIMITS.pastDays) || form.start_date > addDaysIso(today, DATE_LIMITS.futureDays))
  ) {
    errors.start_date = "Date hors limites.";
  }
  const hasEndDate = !single && isIsoDate(form.end_date) && form.end_date !== form.start_date;
  if (!single && form.end_date && !isIsoDate(form.end_date)) {
    errors.end_date = "Indiquez une date de fin valide.";
  } else if (hasEndDate && isIsoDate(form.start_date)) {
    if (form.end_date < form.start_date) errors.end_date = "La date de fin doit suivre la date de début.";
    else if (daysBetween(form.start_date, form.end_date) > DATE_LIMITS.entryMaxDays) {
      errors.end_date = "Une entrée ne peut pas dépasser 3 mois.";
    }
  }
  if (form.recurrence_freq) {
    if (!isIsoDate(form.recurrence_until)) errors.recurrence_until = "Indiquez la fin de la répétition.";
    else if (isIsoDate(form.start_date)) {
      if (form.recurrence_until < form.start_date) {
        errors.recurrence_until = "La fin de la répétition doit suivre le début.";
      } else if (daysBetween(form.start_date, form.recurrence_until) > RECURRENCE_MAX_DAYS) {
        errors.recurrence_until = "La répétition ne peut pas dépasser 2 ans.";
      } else if (hasEndDate && daysBetween(form.start_date, form.end_date) + 1 > RECURRENCE_MIN_INTERVAL[form.recurrence_freq]) {
        errors.recurrence_until = "La durée de l'entrée dépasse l'intervalle de répétition.";
      }
    }
  }
  if (!form.all_day) {
    if (!isTime(form.start_time)) errors.start_time = "Indiquez une heure de début.";
    if (form.end_time && !isTime(form.end_time)) errors.end_time = "Heure invalide.";
    else if (form.end_time && isTime(form.start_time) && !hasEndDate) {
      if ((timeToMinutes(form.end_time) ?? 0) <= (timeToMinutes(form.start_time) ?? 0)) {
        errors.end_time = "L'heure de fin doit suivre l'heure de début.";
      }
    }
  }
  return errors;
}

function EntryDialogContent({
  entry,
  template,
  defaults,
  type: initialType,
  today,
  isResponsable,
  onOpenChange,
  onSaved,
}) {
  const queryClient = useQueryClient();
  const baseId = `ag-entry-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const editing = Boolean(entry);
  const settingsQuery = useQuery(agendaQueries.settings());
  const [initial] = useState(() => initialForm(entry || template, defaults, initialType || "evenement", today));
  const [form, setForm] = useState(initial);
  const [errors, setErrors] = useState({});
  const [banner, setBanner] = useState("");
  const [saving, setSaving] = useState(false);

  const single = SINGLE_DAY_TYPES.includes(form.type);

  const set = (key, value) => {
    setForm((old) => ({ ...old, [key]: value }));
    setErrors((old) => (old[key] ? { ...old, [key]: undefined } : old));
  };

  const close = () => onOpenChange(false);

  const applyError = (failure) => {
    const { field, message } = splitAgendaError(failure);
    if (field && FORM_FIELDS.includes(field)) {
      setErrors((old) => ({ ...old, [field]: message }));
      setBanner("");
    } else {
      setBanner(message);
    }
  };

  const submit = async () => {
    if (saving) return;
    const found = validate(form, today, editing ? entry.series_start_date || entry.start_date : "");
    setErrors(found);
    setBanner("");
    if (Object.keys(found).length) return;
    const values = comparable(form);
    setSaving(true);
    try {
      let saved;
      if (editing) {
        const patch = buildPatch(comparable(initial), values, PATCH_KEYS);
        if (patch.all_day === true) {
          patch.start_time = null;
          patch.end_time = null;
        }
        if (isEmptyPatch(patch)) {
          close();
          return;
        }
        saved = await updateEntry(entry.id, patch);
        toast.success("Élément mis à jour.");
      } else {
        saved = await createEntry(values);
        toast.success(template ? "Élément dupliqué." : "Élément ajouté au calendrier.");
      }
      await invalidateAgenda(queryClient);
      onSaved?.(saved, { created: !editing });
      close();
    } catch (failure) {
      setSaving(false);
      applyError(failure);
    }
  };

  const describe = (field) => (errors[field] ? `${baseId}-${field}-error` : undefined);
  const minDate = addDaysIso(today, -DATE_LIMITS.pastDays) || undefined;
  const maxDate = addDaysIso(today, DATE_LIMITS.futureDays) || undefined;
  const heading = editing ? "Modifier l'élément" : template ? "Dupliquer l'élément" : NEW_HEADINGS[form.type] || "Nouvel élément";

  return (
    <AgendaDialog
      open
      onOpenChange={onOpenChange}
      title={heading}
      eyebrow="Calendrier"
      description="Choisissez le type, la date et, si besoin, les personnes concernées et les rappels Discord."
      size="lg"
      onSubmit={submit}
      dismissible={!saving}
      busy={saving}
      footer={
        <div className="ag-dialog-footer-end">
          <button type="button" className="ag-button ag-button--secondary" onClick={close} disabled={saving}>
            Annuler
          </button>
          <button type="submit" className="ag-button" disabled={saving}>
            {saving ? "Enregistrement…" : editing ? "Enregistrer" : "Ajouter au calendrier"}
          </button>
        </div>
      }
    >
      <div className="ag-form ag-cal-form">
        <FormBanner message={banner} />

        <fieldset className="ag-cal-type-fieldset">
          <legend className="ag-label">Type</legend>
          <div className="ag-cal-type-grid" role="radiogroup" aria-label="Type d'élément">
            {ENTRY_TYPE_KEYS.map((key) => {
              const option = typeMeta(key);
              return (
                <label key={key} className={joinClasses("ag-cal-type-card", typeClass(key))}>
                  <input
                    type="radio"
                    name={`${baseId}-type`}
                    className="ag-check-input"
                    value={key}
                    checked={form.type === key}
                    onChange={() => set("type", key)}
                  />
                  <span className="ag-cal-type-body">
                    <span className="ag-cal-type-icon">
                      <TypeIcon type={key} size={18} />
                    </span>
                    <strong>{option.label}</strong>
                    <small>{option.help}</small>
                  </span>
                </label>
              );
            })}
          </div>
          <FieldError id={`${baseId}-type-error`} message={errors.type} />
        </fieldset>

        {form.type === "autre" ? (
          <div className="ag-field">
            <label className="ag-label" htmlFor={`${baseId}-label`}>
              Libellé
            </label>
            <input
              id={`${baseId}-label`}
              type="text"
              className="ag-input"
              value={form.custom_label}
              maxLength={TEXT_LIMITS.customLabel + 10}
              placeholder="Formation, congé, sortie…"
              autoComplete="off"
              aria-invalid={errors.custom_label ? "true" : undefined}
              aria-describedby={describe("custom_label")}
              onChange={(event) => set("custom_label", event.target.value)}
            />
            <FieldError id={`${baseId}-custom_label-error`} message={errors.custom_label} />
          </div>
        ) : null}

        <div className="ag-field">
          <label className="ag-label" htmlFor={`${baseId}-title`}>
            Titre
          </label>
          <input
            id={`${baseId}-title`}
            type="text"
            className="ag-input ag-input--title"
            value={form.title}
            maxLength={TEXT_LIMITS.title + 20}
            placeholder="Soirée jeux communautaire"
            autoComplete="off"
            aria-invalid={errors.title ? "true" : undefined}
            aria-describedby={describe("title")}
            onChange={(event) => set("title", event.target.value)}
          />
          {form.title.length > TEXT_LIMITS.title - 30 ? <Counter value={form.title} max={TEXT_LIMITS.title} /> : null}
          <FieldError id={`${baseId}-title-error`} message={errors.title} />
        </div>

        <FormCheckbox
          checked={form.all_day}
          onChange={(checked) => set("all_day", checked)}
          label="Toute la journée"
        />

        <div className="ag-form-row">
          <div className="ag-field">
            <label className="ag-label" htmlFor={`${baseId}-start`}>
              Début
            </label>
            <input
              id={`${baseId}-start`}
              type="date"
              className="ag-input"
              value={form.start_date}
              min={minDate}
              max={maxDate}
              aria-invalid={errors.start_date ? "true" : undefined}
              aria-describedby={describe("start_date")}
              onChange={(event) => set("start_date", event.target.value)}
            />
            <FieldError id={`${baseId}-start_date-error`} message={errors.start_date} />
          </div>
          {!form.all_day ? (
            <div className="ag-field">
              <label className="ag-label" htmlFor={`${baseId}-start-time`}>
                Heure de début
              </label>
              <input
                id={`${baseId}-start-time`}
                type="time"
                className="ag-input"
                value={form.start_time}
                aria-invalid={errors.start_time ? "true" : undefined}
                aria-describedby={describe("start_time")}
                onChange={(event) => set("start_time", event.target.value)}
              />
              <FieldError id={`${baseId}-start_time-error`} message={errors.start_time} />
            </div>
          ) : null}
        </div>

        {single && form.all_day ? (
          <p className="ag-help">Une échéance ou un rappel porte sur un seul jour.</p>
        ) : (
          <div className="ag-form-row">
            {single ? null : (
              <div className="ag-field">
                <label className="ag-label" htmlFor={`${baseId}-end`}>
                  Fin <span className="ag-label-optional">(facultatif)</span>
                </label>
                <input
                  id={`${baseId}-end`}
                  type="date"
                  className="ag-input"
                  value={form.end_date}
                  min={isIsoDate(form.start_date) ? form.start_date : undefined}
                  aria-invalid={errors.end_date ? "true" : undefined}
                  aria-describedby={describe("end_date")}
                  onChange={(event) => set("end_date", event.target.value)}
                />
                <FieldError id={`${baseId}-end_date-error`} message={errors.end_date} />
              </div>
            )}
            {!form.all_day ? (
              <div className="ag-field">
                <label className="ag-label" htmlFor={`${baseId}-end-time`}>
                  Heure de fin <span className="ag-label-optional">(facultatif)</span>
                </label>
                <input
                  id={`${baseId}-end-time`}
                  type="time"
                  className="ag-input"
                  value={form.end_time}
                  aria-invalid={errors.end_time ? "true" : undefined}
                  aria-describedby={describe("end_time")}
                  onChange={(event) => set("end_time", event.target.value)}
                />
                <FieldError id={`${baseId}-end_time-error`} message={errors.end_time} />
              </div>
            ) : null}
          </div>
        )}

        <div className="ag-form-row">
          <div className="ag-field">
            <label className="ag-label" htmlFor={`${baseId}-recurrence`}>
              Répétition
            </label>
            <select
              id={`${baseId}-recurrence`}
              className="ag-input"
              value={form.recurrence_freq}
              onChange={(event) => {
                const freq = event.target.value;
                setForm((old) => ({
                  ...old,
                  recurrence_freq: freq,
                  recurrence_until:
                    freq && !old.recurrence_until && isIsoDate(old.start_date)
                      ? addDaysIso(old.start_date, freq === "monthly" ? 90 : 56)
                      : old.recurrence_until,
                }));
                setErrors((old) => ({ ...old, recurrence_until: undefined }));
              }}
            >
              {RECURRENCE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          {form.recurrence_freq ? (
            <div className="ag-field">
              <label className="ag-label" htmlFor={`${baseId}-until`}>
                Jusqu'au
              </label>
              <input
                id={`${baseId}-until`}
                type="date"
                className="ag-input"
                value={form.recurrence_until}
                min={isIsoDate(form.start_date) ? form.start_date : undefined}
                aria-invalid={errors.recurrence_until ? "true" : undefined}
                aria-describedby={describe("recurrence_until")}
                onChange={(event) => set("recurrence_until", event.target.value)}
              />
              <FieldError id={`${baseId}-recurrence_until-error`} message={errors.recurrence_until} />
            </div>
          ) : null}
        </div>
        {form.recurrence_freq ? (
          <p className="ag-help">Les rappels Discord ne concernent que la première occurrence de la série.</p>
        ) : null}

        <div className="ag-field">
          <label className="ag-label" htmlFor={`${baseId}-location`}>
            Lieu <span className="ag-label-optional">(facultatif)</span>
          </label>
          <input
            id={`${baseId}-location`}
            type="text"
            className="ag-input"
            value={form.location}
            maxLength={TEXT_LIMITS.location + 20}
            placeholder="Vocal Événements"
            aria-invalid={errors.location ? "true" : undefined}
            aria-describedby={describe("location")}
            onChange={(event) => set("location", event.target.value)}
          />
          <FieldError id={`${baseId}-location-error`} message={errors.location} />
        </div>

        <div className="ag-field">
          <label className="ag-label" htmlFor={`${baseId}-description`}>
            Description <span className="ag-label-optional">(facultatif)</span>
          </label>
          <textarea
            id={`${baseId}-description`}
            className="ag-textarea"
            value={form.description}
            rows={4}
            maxLength={TEXT_LIMITS.description + 100}
            aria-invalid={errors.description ? "true" : undefined}
            aria-describedby={describe("description")}
            onChange={(event) => set("description", event.target.value)}
          />
          <Counter value={form.description} max={TEXT_LIMITS.description} />
          <FieldError id={`${baseId}-description-error`} message={errors.description} />
        </div>

        <div className="ag-field">
          <PeoplePicker
            mode="multiple"
            label={form.type === "permanence" ? "Personnes de permanence" : "Participants"}
            selected={form.participants}
            onChange={(next) => set("participants", next)}
            emptyLabel={form.type === "permanence" ? "Personne n'est de permanence pour l'instant." : "Aucun participant pour l'instant."}
            invalid={Boolean(errors.participant_ids)}
            describedBy={describe("participant_ids")}
          />
          <FieldError id={`${baseId}-participant_ids-error`} message={errors.participant_ids} />
        </div>

        <ReminderFields
          value={form.reminders}
          onChange={(next) => set("reminders", next)}
          allDay={form.all_day}
          startDate={form.start_date}
          startTime={form.start_time}
          canPing={isResponsable}
          settings={settingsQuery.data || null}
          disabled={saving}
          error={errors.reminders || null}
        />
      </div>
    </AgendaDialog>
  );
}

// Fenêtre d'un événement, d'une échéance, d'un rappel, d'une permanence ou d'un autre type.
// `entry` : EntryOut à modifier (PATCH des seuls champs changés) ; `template` : EntryOut à dupliquer (sans id) ;
// `defaults` : { title, start, end, allDay, startTime, endTime } (ajout rapide). Repart de zéro à chaque ouverture.
export default function EntryDialog({
  open,
  onOpenChange,
  entry = null,
  template = null,
  defaults = null,
  type = "evenement",
  today,
  isResponsable = false,
  onSaved = null,
}) {
  if (!open) return null;
  return (
    <EntryDialogContent
      entry={entry}
      template={template}
      defaults={defaults}
      type={type}
      today={today}
      isResponsable={isResponsable}
      onOpenChange={onOpenChange}
      onSaved={onSaved}
    />
  );
}

export { EntryDialog };
