import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Info } from "lucide-react";

import "@/Agenda.css";

import AgendaDialog from "../AgendaDialog";
import PeoplePicker from "../PeoplePicker";
import { createAbsence, invalidateAfterAbsenceChange, updateAbsence } from "../agendaApi";
import { DATE_LIMITS, TEXT_LIMITS } from "../agendaConstants";
import { splitAgendaError } from "../agendaErrors";
import { helperName } from "../calendarModel";
import { addDaysIso, daysBetween, isIsoDate } from "../dateUtils";
import { Counter, FieldError, FormBanner, FormSwitch } from "./FormControls";
import "./agenda-calendar.css";

// Champs du serveur → champs du formulaire (la durée maximale est annoncée sous « Fin »).
const FIELD_ALIASES = { range: "end_date" };
const FORM_FIELDS = ["start_date", "end_date", "open_ended", "reason", "helper_id"];

function initialForm(absence, defaults, today) {
  if (absence) {
    const openEnded = Boolean(absence.open_ended) || !absence.end_date;
    return {
      start_date: absence.start_date || today,
      end_date: openEnded ? "" : absence.end_date,
      open_ended: openEnded,
      reason: absence.reason || "",
      helper: null,
    };
  }
  const start = isIsoDate(defaults?.start) ? defaults.start : today;
  return {
    start_date: start,
    end_date: isIsoDate(defaults?.end) && defaults.end >= start ? defaults.end : start,
    open_ended: Boolean(defaults?.openEnded),
    reason: defaults?.reason || "",
    helper: null,
  };
}

// Les bornes ne sont revérifiées que pour une date que la personne a changée (comme le serveur).
function validate(form, initial, today, editing) {
  const errors = {};
  const lowest = addDaysIso(today, -DATE_LIMITS.pastDays);
  const highest = addDaysIso(today, DATE_LIMITS.futureDays);
  if (!isIsoDate(form.start_date)) {
    errors.start_date = "Indiquez une date de début valide.";
  } else if (
    (!editing || form.start_date !== initial.start_date) &&
    lowest &&
    highest &&
    (form.start_date < lowest || form.start_date > highest)
  ) {
    errors.start_date = "Date de début hors limites.";
  }
  if (!form.open_ended) {
    if (!isIsoDate(form.end_date)) {
      errors.end_date = "Indiquez une date de fin ou cochez « Fin indéterminée ».";
    } else if (isIsoDate(form.start_date) && form.end_date < form.start_date) {
      errors.end_date = "La date de fin doit suivre la date de début.";
    } else if (isIsoDate(form.start_date) && daysBetween(form.start_date, form.end_date) > DATE_LIMITS.absenceMaxDays) {
      errors.end_date = "Une absence ne peut pas dépasser un an.";
    }
  }
  if (form.reason.length > TEXT_LIMITS.reason) errors.reason = `Le motif est limité à ${TEXT_LIMITS.reason} caractères.`;
  return errors;
}

// PATCH des seuls champs modifiés ; la fin indéterminée s'envoie avec sa date de fin (null ou saisie).
function buildAbsencePatch(initial, form) {
  const patch = {};
  if (form.start_date !== initial.start_date) patch.start_date = form.start_date;
  if (form.reason.trim() !== initial.reason.trim()) patch.reason = form.reason.trim();
  if (form.open_ended !== initial.open_ended) {
    patch.open_ended = form.open_ended;
    patch.end_date = form.open_ended ? null : form.end_date;
  } else if (!form.open_ended && form.end_date !== initial.end_date) {
    patch.end_date = form.end_date;
  }
  return patch;
}

function AbsenceDialogContent({ absence, defaults, today, isResponsable, viewerId, onOpenChange, onSaved }) {
  const queryClient = useQueryClient();
  const baseId = `ag-absence-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const editing = Boolean(absence);
  const [initial] = useState(() => initialForm(absence, defaults, today));
  const [form, setForm] = useState(initial);
  const [errors, setErrors] = useState({});
  const [banner, setBanner] = useState("");
  const [saving, setSaving] = useState(false);

  const set = (key, value) => {
    setForm((old) => ({ ...old, [key]: value }));
    setErrors((old) => (old[key] ? { ...old, [key]: undefined } : old));
  };

  const toggleOpenEnded = (checked) => {
    setForm((old) => ({
      ...old,
      open_ended: checked,
      end_date: !checked && !isIsoDate(old.end_date) ? old.start_date : old.end_date,
    }));
    setErrors((old) => ({ ...old, end_date: undefined }));
  };

  const close = () => onOpenChange(false);

  const applyError = (failure) => {
    const { field, message } = splitAgendaError(failure);
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
    const found = validate(form, initial, today, editing);
    setErrors(found);
    setBanner("");
    if (Object.keys(found).length) return;
    setSaving(true);
    try {
      let saved;
      if (editing) {
        const patch = buildAbsencePatch(initial, form);
        if (!Object.keys(patch).length) {
          close();
          return;
        }
        saved = await updateAbsence(absence.id, patch);
        toast.success("Absence mise à jour.");
      } else {
        const payload = {
          start_date: form.start_date,
          end_date: form.open_ended ? null : form.end_date,
          open_ended: form.open_ended,
          reason: form.reason.trim(),
        };
        if (isResponsable && form.helper && String(form.helper.id) !== String(viewerId)) {
          payload.helper_id = String(form.helper.id);
        }
        saved = await createAbsence(payload);
        toast.success(payload.helper_id ? "Absence déclarée." : "Absence déclarée. Bon courage !");
      }
      await invalidateAfterAbsenceChange(queryClient);
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

  return (
    <AgendaDialog
      open
      onOpenChange={onOpenChange}
      title={editing ? "Modifier l'absence" : "Déclarer une absence"}
      eyebrow="Absence"
      description={
        editing
          ? `Période d'absence de ${helperName(absence.helper)}.`
          : "Indiquez la période où vous n'êtes pas disponible : l'équipe la voit dans le calendrier."
      }
      size="md"
      onSubmit={submit}
      dismissible={!saving}
      busy={saving}
      note="Les absences ne déclenchent pas de rappel Discord."
      footer={
        <div className="ag-dialog-footer-end">
          <button type="button" className="ag-button ag-button--secondary" onClick={close} disabled={saving}>
            Annuler
          </button>
          <button type="submit" className="ag-button" disabled={saving}>
            {saving ? "Enregistrement…" : "Enregistrer l'absence"}
          </button>
        </div>
      }
    >
      <div className="ag-form ag-cal-form">
        <FormBanner message={banner} />

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
          <div className="ag-field">
            <label className="ag-label" htmlFor={`${baseId}-end`}>
              Fin
            </label>
            <input
              id={`${baseId}-end`}
              type="date"
              className="ag-input"
              value={form.open_ended ? "" : form.end_date}
              min={isIsoDate(form.start_date) ? form.start_date : undefined}
              disabled={form.open_ended}
              aria-invalid={errors.end_date ? "true" : undefined}
              aria-describedby={describe("end_date")}
              onChange={(event) => set("end_date", event.target.value)}
            />
            <FieldError id={`${baseId}-end_date-error`} message={errors.end_date} />
          </div>
        </div>

        <div className="ag-field">
          <FormSwitch
            checked={form.open_ended}
            onChange={toggleOpenEnded}
            label="Fin indéterminée"
            describedBy={`${baseId}-open-help`}
          />
          <p className="ag-help" id={`${baseId}-open-help`}>
            Pour une absence dont tu ne connais pas encore la date de retour. Tu pourras indiquer ton retour en un clic.
          </p>
        </div>

        <div className="ag-field">
          <label className="ag-label" htmlFor={`${baseId}-reason`}>
            Motif <span className="ag-label-optional">(facultatif)</span>
          </label>
          <textarea
            id={`${baseId}-reason`}
            className="ag-textarea"
            value={form.reason}
            rows={3}
            maxLength={TEXT_LIMITS.reason + 40}
            placeholder="Vacances, examens, repos…"
            aria-invalid={errors.reason ? "true" : undefined}
            aria-describedby={describe("reason")}
            onChange={(event) => set("reason", event.target.value)}
          />
          <Counter value={form.reason} max={TEXT_LIMITS.reason} />
          <FieldError id={`${baseId}-reason-error`} message={errors.reason} />
        </div>

        {isResponsable && !editing ? (
          <div className="ag-field">
            <PeoplePicker
              mode="single"
              label="Pour un autre membre"
              selected={form.helper}
              onChange={(next) => set("helper", next)}
              noneLabel="Moi (par défaut)"
              allowNone
              invalid={Boolean(errors.helper_id)}
              describedBy={describe("helper_id")}
            />
            <p className="ag-help">Réservé aux responsables : l'absence sera déclarée au nom du membre choisi.</p>
            <FieldError id={`${baseId}-helper_id-error`} message={errors.helper_id} />
          </div>
        ) : null}

        {editing && absence.created_by && absence.created_by.id !== absence.helper?.id ? (
          <p className="ag-callout ag-callout--info">
            <Info size={15} aria-hidden="true" />
            <span>Déclarée par {helperName(absence.created_by)}.</span>
          </p>
        ) : null}
      </div>
    </AgendaDialog>
  );
}

// Fenêtre « Déclarer une absence » / « Modifier l'absence ». Le formulaire repart de zéro à chaque ouverture.
// `defaults` : { start, end, openEnded, reason } (ajout rapide, glisser sur plusieurs jours).
export default function AbsenceDialog({
  open,
  onOpenChange,
  absence = null,
  defaults = null,
  today,
  isResponsable = false,
  viewerId = null,
  onSaved = null,
}) {
  if (!open) return null;
  return (
    <AbsenceDialogContent
      absence={absence}
      defaults={defaults}
      today={today}
      isResponsable={isResponsable}
      viewerId={viewerId}
      onOpenChange={onOpenChange}
      onSaved={onSaved}
    />
  );
}

export { AbsenceDialog };
