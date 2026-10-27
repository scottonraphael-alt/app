import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CircleAlert, ListChecks, Plus, X } from "lucide-react";

import "./meetings.css";

import AgendaDialog from "../AgendaDialog";
import PeoplePicker from "../PeoplePicker";
import ReminderFields from "../ReminderFields";
import {
  agendaKeys,
  agendaQueries,
  buildPatch,
  commitMeetingDetail,
  createMeeting,
  isEmptyPatch,
  updateMeeting,
} from "../agendaApi";
import { DATE_LIMITS, DEFAULT_REMINDERS, DISABLED_REMINDERS, TEXT_LIMITS, remindersPayload } from "../agendaConstants";
import { isRevisionConflict, revisionConflictInfo, splitAgendaError } from "../agendaErrors";
import { addDaysIso, isIsoDate, isTime, resolveToday } from "../dateUtils";

const FIELD_ALIASES = { start_date: "meeting_date" };
const FORM_FIELDS = ["title", "meeting_date", "start_time", "end_time", "location", "participant_ids", "agenda_items", "reminders"];
const PATCH_KEYS = ["title", "meeting_date", "start_time", "end_time", "location", "participant_ids", "reminders"];

let itemCounter = 0;
function newItem(title = "") {
  itemCounter += 1;
  return { key: `point-${itemCounter}`, title };
}

function participantsOf(meeting) {
  return Array.isArray(meeting?.participants)
    ? meeting.participants
        .filter((person) => person && person.id)
        .map((person) => ({
          id: String(person.id),
          username: person.username || "",
          display_name: person.display_name ?? null,
          avatar_url: person.avatar_url ?? null,
        }))
    : [];
}

function initialForm(meeting, defaultDate, today) {
  if (meeting) {
    return {
      title: meeting.title || "",
      meeting_date: isIsoDate(meeting.meeting_date) ? meeting.meeting_date : "",
      start_time: isTime(meeting.start_time) ? meeting.start_time : "",
      end_time: isTime(meeting.end_time) ? meeting.end_time : "",
      location: meeting.location || "",
      participants: participantsOf(meeting),
      agendaItems: [],
      reminders: remindersPayload(meeting.reminders || DISABLED_REMINDERS),
    };
  }
  return {
    title: "",
    meeting_date: isIsoDate(defaultDate) ? defaultDate : today,
    start_time: "",
    end_time: "",
    location: "",
    participants: [],
    agendaItems: [],
    reminders: remindersPayload(DEFAULT_REMINDERS),
  };
}

// Valeurs comparables au document (pour le PATCH) : chaînes vides des heures → null.
function comparable(form) {
  const startTime = isTime(form.start_time) ? form.start_time : null;
  return {
    title: form.title.trim(),
    meeting_date: form.meeting_date,
    start_time: startTime,
    end_time: startTime && isTime(form.end_time) ? form.end_time : null,
    location: form.location.trim(),
    participant_ids: form.participants.map((person) => String(person.id)),
    reminders: remindersPayload(form.reminders),
  };
}

// `keptDate` : date déjà enregistrée, que le serveur ne revérifie pas si elle ne change pas.
function validate(form, today, keptDate = "") {
  const errors = {};
  if (!form.title.trim()) errors.title = "Indiquez un titre.";
  if (!isIsoDate(form.meeting_date)) {
    errors.meeting_date = "Indiquez une date valide.";
  } else if (
    form.meeting_date !== keptDate &&
    isIsoDate(today) &&
    (form.meeting_date < addDaysIso(today, -DATE_LIMITS.pastDays) || form.meeting_date > addDaysIso(today, DATE_LIMITS.futureDays))
  ) {
    errors.meeting_date = "Date hors limites.";
  }
  if (form.start_time && !isTime(form.start_time)) errors.start_time = "Heure invalide.";
  if (form.end_time && !isTime(form.end_time)) errors.end_time = "Heure invalide.";
  if (!errors.start_time && !errors.end_time && form.end_time) {
    if (!form.start_time) errors.start_time = "Indiquez une heure de début.";
    else if (form.end_time <= form.start_time) errors.end_time = "L'heure de fin doit suivre l'heure de début.";
  }
  return errors;
}

function FieldError({ id, message }) {
  if (!message) return null;
  return (
    <p className="ag-field-error" id={id} role="alert">
      <CircleAlert size={14} aria-hidden="true" />
      {message}
    </p>
  );
}

// Ordre du jour saisi à la suite : Entrée dans « Ajouter un point » ajoute la ligne.
function AgendaItemsField({ items, onChange, error, disabled }) {
  const baseId = `ag-meet-agenda-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const [draft, setDraft] = useState("");
  const draftRef = useRef(null);
  const rowRefs = useRef(new Map());
  const [focusKey, setFocusKey] = useState(null);
  const full = items.length >= TEXT_LIMITS.listItems;

  useEffect(() => {
    if (!focusKey) return;
    const node = focusKey === "draft" ? draftRef.current : rowRefs.current.get(focusKey);
    if (node) node.focus();
    setFocusKey(null);
  }, [focusKey]);

  const addDraft = () => {
    const title = draft.trim();
    if (!title || full) return;
    onChange([...items, newItem(title)]);
    setDraft("");
  };

  const update = (key, title) => onChange(items.map((item) => (item.key === key ? { ...item, title } : item)));

  const remove = (index) => {
    const next = items.filter((_, position) => position !== index);
    onChange(next);
    setFocusKey(next[index - 1]?.key || next[index]?.key || "draft");
  };

  const move = (index, delta) => {
    const target = index + delta;
    if (target < 0 || target >= items.length) return;
    const next = [...items];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
    setFocusKey(next[target].key);
  };

  const onRowKeyDown = (event, index) => {
    if (event.key === "Enter") {
      event.preventDefault();
      setFocusKey(items[index + 1]?.key || "draft");
    } else if (event.key === "Backspace" && !event.currentTarget.value) {
      event.preventDefault();
      remove(index);
    } else if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      event.preventDefault();
      move(index, event.key === "ArrowUp" ? -1 : 1);
    }
  };

  return (
    <fieldset className="ag-fieldset ag-meet-agenda-field" disabled={disabled} aria-describedby={`${baseId}-help`}>
      <legend className="ag-legend">
        <ListChecks size={16} aria-hidden="true" />
        Ordre du jour
        <span className="ag-label-optional">(facultatif)</span>
      </legend>
      {items.length ? (
        <ol className="ag-meet-agenda-items">
          {items.map((item, index) => (
            <li key={item.key} className="ag-meet-agenda-item">
              <span className="ag-meet-agenda-number" aria-hidden="true">
                {index + 1}.
              </span>
              <input
                ref={(node) => {
                  if (node) rowRefs.current.set(item.key, node);
                  else rowRefs.current.delete(item.key);
                }}
                type="text"
                className="ag-input"
                value={item.title}
                maxLength={TEXT_LIMITS.agendaItem}
                aria-label={`Point ${index + 1}`}
                onChange={(event) => update(item.key, event.target.value)}
                onKeyDown={(event) => onRowKeyDown(event, index)}
              />
              <button
                type="button"
                className="ag-icon-button ag-icon-button--small"
                aria-label={`Retirer le point ${index + 1}`}
                onClick={() => remove(index)}
              >
                <X size={15} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ol>
      ) : null}
      <div className="ag-meet-agenda-add">
        <input
          ref={draftRef}
          id={`${baseId}-draft`}
          type="text"
          className="ag-input"
          value={draft}
          maxLength={TEXT_LIMITS.agendaItem}
          placeholder={full ? "50 points au maximum" : "Ajouter un point puis Entrée"}
          aria-label="Ajouter un point à l'ordre du jour"
          disabled={full}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addDraft();
            } else if (event.key === "Backspace" && !draft && items.length) {
              event.preventDefault();
              setFocusKey(items[items.length - 1].key);
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
      <p className="ag-help" id={`${baseId}-help`}>
        Entrée ajoute le point. Il reste modifiable sur la page de la réunion.
      </p>
      <FieldError id={`${baseId}-error`} message={error} />
    </fieldset>
  );
}

function MeetingDialogContent({ onOpenChange, meeting, defaultDate, today: todayProp, beforeSubmit, onSaved }) {
  const baseId = `ag-meet-form-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const editing = Boolean(meeting?.id);
  const today = resolveToday(todayProp);
  const [initial] = useState(() => initialForm(meeting, defaultDate, today));
  const [form, setForm] = useState(initial);
  const [errors, setErrors] = useState({});
  const [banner, setBanner] = useState("");
  const [saving, setSaving] = useState(false);
  const settingsQuery = useQuery(agendaQueries.settings());

  const set = (field, value) => {
    setForm((old) => {
      const next = { ...old, [field]: value };
      if (field === "start_time" && !value) next.end_time = "";
      return next;
    });
    setErrors((old) => {
      if (!old[field] && !(field === "start_time" && old.end_time)) return old;
      const next = { ...old };
      delete next[field];
      if (field === "start_time") delete next.end_time;
      return next;
    });
  };

  const close = () => onOpenChange?.(false);

  const applyError = (error) => {
    if (isRevisionConflict(error)) {
      const info = revisionConflictInfo(error);
      setBanner(`${info?.message || "Ce compte-rendu a été modifié par quelqu'un d'autre."} Fermez la fenêtre, rechargez la réunion puis recommencez.`);
      return;
    }
    const { field, message } = splitAgendaError(error);
    const key = FIELD_ALIASES[field] || field;
    if (key && FORM_FIELDS.includes(key)) {
      setErrors((old) => ({ ...old, [key]: message }));
      setBanner("");
    } else {
      setBanner(message);
    }
  };

  const submit = async () => {
    if (saving) return;
    const found = validate(form, today, editing ? initial.meeting_date : "");
    setErrors(found);
    setBanner("");
    if (Object.keys(found).length) return;
    const values = comparable(form);
    setSaving(true);
    try {
      if (editing) {
        const patch = buildPatch(comparable(initial), values, PATCH_KEYS);
        if (patch.start_time === null) patch.end_time = null;
        if (isEmptyPatch(patch)) {
          close();
          return;
        }
        const flushed = beforeSubmit ? await beforeSubmit() : undefined;
        const cached = queryClient.getQueryData(agendaKeys.meeting(meeting.id));
        const revision = Number.isInteger(flushed) ? flushed : Number(cached?.revision ?? meeting.revision) || 0;
        const detail = await updateMeeting(meeting.id, { expected_revision: revision, ...patch });
        commitMeetingDetail(queryClient, detail);
        toast.success("Réunion mise à jour.");
        onSaved?.(detail, { created: false });
      } else {
        const payload = {
          ...values,
          agenda_items: form.agendaItems
            .map((item) => item.title.trim())
            .filter(Boolean)
            .map((title) => ({ title })),
        };
        const detail = await createMeeting(payload);
        commitMeetingDetail(queryClient, detail);
        const url = `/staff/meetings/${encodeURIComponent(detail.id)}`;
        toast.success("Réunion planifiée.", { action: { label: "Ouvrir", onClick: () => navigate(url) } });
        onSaved?.(detail, { created: true });
      }
      setSaving(false);
      close();
    } catch (error) {
      setSaving(false);
      applyError(error);
    }
  };

  const describe = (field) => (errors[field] ? `${baseId}-${field}-error` : undefined);
  const titleLength = form.title.length;

  return (
    <AgendaDialog
      open
      onOpenChange={onOpenChange}
      title={editing ? "Modifier les informations" : "Nouvelle réunion"}
      eyebrow="Réunion staff"
      description={
        editing
          ? "Date, horaires, lieu, participants et rappels de la réunion."
          : "Planifiez la réunion : l'ordre du jour et le compte-rendu se complètent ensuite sur sa page."
      }
      size="md"
      onSubmit={submit}
      dismissible={!saving}
      busy={saving}
      className="ag-meet-dialog"
      footer={
        <div className="ag-dialog-footer-end">
          <button type="button" className="ag-button ag-button--secondary" onClick={close} disabled={saving}>
            Annuler
          </button>
          <button type="submit" className="ag-button" disabled={saving}>
            {saving ? "Enregistrement…" : editing ? "Enregistrer" : "Planifier la réunion"}
          </button>
        </div>
      }
    >
      <div className="ag-form">
        {banner ? (
          <div className="ag-error" role="alert">
            <span className="ag-error-text">
              <CircleAlert size={15} aria-hidden="true" />
              {banner}
            </span>
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
            maxLength={TEXT_LIMITS.title}
            placeholder="Réunion mensuelle de novembre"
            autoComplete="off"
            aria-invalid={errors.title ? "true" : undefined}
            aria-describedby={describe("title")}
            onChange={(event) => set("title", event.target.value)}
          />
          {titleLength > TEXT_LIMITS.title - 30 ? (
            <span className={`ag-counter${titleLength >= TEXT_LIMITS.title ? " is-over" : ""}`}>
              {titleLength}/{TEXT_LIMITS.title}
            </span>
          ) : null}
          <FieldError id={`${baseId}-title-error`} message={errors.title} />
        </div>

        <div className="ag-meet-form-when">
          <div className="ag-field">
            <label className="ag-label" htmlFor={`${baseId}-date`}>
              Date
            </label>
            <input
              id={`${baseId}-date`}
              type="date"
              className="ag-input"
              value={form.meeting_date}
              min={addDaysIso(today, -DATE_LIMITS.pastDays) || undefined}
              max={addDaysIso(today, DATE_LIMITS.futureDays) || undefined}
              aria-invalid={errors.meeting_date ? "true" : undefined}
              aria-describedby={describe("meeting_date")}
              onChange={(event) => set("meeting_date", event.target.value)}
            />
            <FieldError id={`${baseId}-meeting_date-error`} message={errors.meeting_date} />
          </div>
          <div className="ag-field">
            <label className="ag-label" htmlFor={`${baseId}-start`}>
              Début <span className="ag-label-optional">(facultatif)</span>
            </label>
            <input
              id={`${baseId}-start`}
              type="time"
              className="ag-input"
              value={form.start_time}
              aria-invalid={errors.start_time ? "true" : undefined}
              aria-describedby={describe("start_time")}
              onChange={(event) => set("start_time", event.target.value)}
            />
            <FieldError id={`${baseId}-start_time-error`} message={errors.start_time} />
          </div>
          <div className="ag-field">
            <label className="ag-label" htmlFor={`${baseId}-end`}>
              Fin <span className="ag-label-optional">(facultatif)</span>
            </label>
            <input
              id={`${baseId}-end`}
              type="time"
              className="ag-input"
              value={form.end_time}
              disabled={!form.start_time}
              aria-invalid={errors.end_time ? "true" : undefined}
              aria-describedby={describe("end_time")}
              onChange={(event) => set("end_time", event.target.value)}
            />
            <FieldError id={`${baseId}-end_time-error`} message={errors.end_time} />
          </div>
        </div>
        {!form.start_time ? (
          <p className="ag-help ag-meet-form-hint">Sans heure, la réunion s'affiche sur la journée.</p>
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
            maxLength={TEXT_LIMITS.location}
            placeholder="Vocal Staff"
            onChange={(event) => set("location", event.target.value)}
          />
        </div>

        <div className="ag-field">
          <PeoplePicker
            mode="multiple"
            label="Participants"
            selected={form.participants}
            onChange={(next) => set("participants", next)}
            emptyLabel="Aucun participant pour l'instant."
            invalid={Boolean(errors.participant_ids)}
            describedBy={describe("participant_ids")}
          />
          <FieldError id={`${baseId}-participant_ids-error`} message={errors.participant_ids} />
        </div>

        {editing ? null : (
          <AgendaItemsField
            items={form.agendaItems}
            onChange={(next) => set("agendaItems", next)}
            error={errors.agenda_items}
            disabled={saving}
          />
        )}

        <ReminderFields
          value={form.reminders}
          onChange={(next) => set("reminders", next)}
          allDay={!form.start_time}
          startDate={form.meeting_date}
          startTime={form.start_time}
          canPing
          settings={settingsQuery.data || null}
          disabled={saving}
          error={errors.reminders || null}
        />
      </div>
    </AgendaDialog>
  );
}

// Fenêtre « Nouvelle réunion » / « Modifier les informations » (responsables). Le formulaire repart de
// zéro à chaque ouverture. En modification : `meeting` = MeetingDetailOut, PATCH des seuls champs changés
// avec expected_revision ; `beforeSubmit` (ex. autosave.flush) est attendu avant l'envoi et peut renvoyer
// la révision à jour.
export default function MeetingDialog({
  open,
  onOpenChange,
  meeting = null,
  defaultDate = "",
  today = null,
  beforeSubmit = null,
  onSaved = null,
}) {
  if (!open) return null;
  return (
    <MeetingDialogContent
      onOpenChange={onOpenChange}
      meeting={meeting}
      defaultDate={defaultDate}
      today={today}
      beforeSubmit={beforeSubmit}
      onSaved={onSaved}
    />
  );
}

export { MeetingDialog };
