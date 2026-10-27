import { useId, useRef, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight } from "lucide-react";

import "@/Agenda.css";

import {
  commitMeetingDetail,
  createAbsence,
  createEntry,
  createMeeting,
  invalidateAfterAbsenceChange,
  invalidateAgenda,
} from "../agendaApi";
import { DEFAULT_REMINDERS, SINGLE_DAY_TYPES, TEXT_LIMITS, remindersPayload, typeMeta } from "../agendaConstants";
import { splitAgendaError } from "../agendaErrors";
import { formatDayTitle, isIsoDate } from "../dateUtils";
import { TypeIcon, typeClass } from "../TypeBadge";
import { isEndTimeBeforeStart, joinClasses, restoreFocus, useVirtualAnchor } from "./calendarHelpers";
import { FieldError, FormCheckbox } from "./FormControls";
import "./agenda-calendar.css";

// Types proposés dans l'ajout rapide ; « Autre » (libellé libre) passe par « Plus d'options ».
const QUICK_TYPES = ["absence", "reunion", "evenement", "echeance", "rappel", "permanence"];
const BOUNDED_TYPES = ["reunion", ...SINGLE_DAY_TYPES];

function QuickAddContent({ anchorEl, start, end, fromRange, canManage, onOpenChange, onOpenFull, onCreated }) {
  const queryClient = useQueryClient();
  const baseId = `ag-qa-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const virtualRef = useVirtualAnchor(anchorEl);
  const titleRef = useRef(null);
  const types = QUICK_TYPES.filter((type) => type !== "reunion" || canManage);

  const [type, setType] = useState(fromRange ? "absence" : "evenement");
  const [title, setTitle] = useState("");
  const [allDay, setAllDay] = useState(true);
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [endDate, setEndDate] = useState(isIsoDate(end) ? end : start);
  const [openEnded, setOpenEnded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const isAbsence = type === "absence";
  const isMeeting = type === "reunion";
  const singleDay = BOUNDED_TYPES.includes(type);
  const timeless = isAbsence;
  const lastDay = isIsoDate(endDate) && endDate >= start ? endDate : start;
  const hasRange = lastDay !== start;

  const close = () => onOpenChange(false);

  const values = () => ({
    type,
    title: title.trim(),
    start,
    end: singleDay ? start : lastDay,
    allDay: timeless ? true : allDay,
    startTime: allDay ? "" : startTime,
    endTime: allDay ? "" : endTime,
    openEnded: isAbsence ? openEnded : false,
  });

  const submit = async (event) => {
    event.preventDefault();
    if (saving) return;
    const current = values();
    if (!isAbsence && !current.title) {
      setError("Indiquez un titre.");
      return;
    }
    if (isAbsence && !openEnded && isIsoDate(endDate) && endDate < start) {
      setError("La date de fin doit suivre la date de début.");
      return;
    }
    if (!isAbsence && !allDay) {
      if (!startTime) {
        setError("Indiquez une heure de début.");
        return;
      }
      if (isEndTimeBeforeStart(startTime, endTime) && !hasRange) {
        setError("L'heure de fin doit suivre l'heure de début.");
        return;
      }
    }
    setSaving(true);
    setError("");
    try {
      if (isAbsence) {
        await createAbsence({
          start_date: start,
          end_date: openEnded ? null : lastDay,
          open_ended: openEnded,
          reason: current.title,
        });
        await invalidateAfterAbsenceChange(queryClient);
        toast.success("Absence déclarée.");
      } else if (isMeeting) {
        const detail = await createMeeting({
          title: current.title,
          meeting_date: start,
          start_time: allDay ? null : startTime,
          end_time: allDay || !endTime ? null : endTime,
          reminders: remindersPayload(DEFAULT_REMINDERS),
        });
        commitMeetingDetail(queryClient, detail);
        toast.success("Réunion planifiée.");
      } else {
        await createEntry({
          type,
          title: current.title,
          all_day: allDay,
          start_date: start,
          end_date: singleDay || !hasRange ? null : lastDay,
          start_time: allDay ? null : startTime,
          end_time: allDay || !endTime ? null : endTime,
          reminders: remindersPayload(DEFAULT_REMINDERS),
        });
        await invalidateAgenda(queryClient);
        toast.success("Élément ajouté au calendrier.");
      }
      onCreated(start);
      close();
    } catch (failure) {
      setSaving(false);
      setError(splitAgendaError(failure).message);
    }
  };

  const openFull = () => {
    const current = values();
    onOpenFull({ ...current, reason: isAbsence ? current.title : "" });
    close();
  };

  const titleLabel = isAbsence ? "Motif (facultatif)" : "Titre";

  return (
    <Popover.Root open onOpenChange={onOpenChange}>
      <Popover.Anchor virtualRef={virtualRef} />
      <Popover.Portal>
        <Popover.Content
          className="ag-popover ag-cal-quick"
          side="bottom"
          align="start"
          sideOffset={6}
          collisionPadding={12}
          aria-label="Ajout rapide"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            if (titleRef.current) titleRef.current.focus();
          }}
          onCloseAutoFocus={(event) => restoreFocus(event, anchorEl)}
        >
          <form className="ag-cal-quick-form" onSubmit={submit} noValidate>
            <p className="ag-cal-quick-date">
              {formatDayTitle(start, { withYear: true })}
              {hasRange && !singleDay ? (
                <>
                  <ArrowRight size={13} aria-hidden="true" />
                  {formatDayTitle(lastDay)}
                </>
              ) : null}
            </p>

            <div className="ag-cal-quick-types" role="radiogroup" aria-label="Type d'élément">
              {types.map((key) => (
                <button
                  key={key}
                  type="button"
                  role="radio"
                  aria-checked={type === key}
                  className={joinClasses("ag-chip", typeClass(key), type === key ? "is-selected" : "")}
                  onClick={() => {
                    setType(key);
                    setError("");
                  }}
                >
                  <TypeIcon type={key} size={13} />
                  {typeMeta(key).label}
                </button>
              ))}
            </div>

            <div className="ag-field">
              <label className="ag-label" htmlFor={`${baseId}-title`}>
                {titleLabel}
              </label>
              <input
                ref={titleRef}
                id={`${baseId}-title`}
                type="text"
                className="ag-input"
                value={title}
                maxLength={isAbsence ? TEXT_LIMITS.reason : TEXT_LIMITS.title}
                autoComplete="off"
                placeholder={isAbsence ? "Vacances, examen…" : isMeeting ? "Réunion mensuelle" : "Soirée jeux"}
                aria-invalid={error && !isAbsence && !title.trim() ? "true" : undefined}
                onChange={(event) => {
                  setTitle(event.target.value);
                  setError("");
                }}
              />
            </div>

            {isAbsence ? (
              <>
                <FormCheckbox checked={openEnded} onChange={setOpenEnded} label="Fin indéterminée" />
                {!openEnded ? (
                  <div className="ag-field">
                    <label className="ag-label" htmlFor={`${baseId}-end`}>
                      Dernier jour d'absence
                    </label>
                    <input
                      id={`${baseId}-end`}
                      type="date"
                      className="ag-input"
                      value={endDate}
                      min={start}
                      onChange={(event) => setEndDate(event.target.value)}
                    />
                  </div>
                ) : null}
              </>
            ) : (
              <>
                <FormCheckbox checked={allDay} onChange={setAllDay} label="Toute la journée" />
                {!allDay ? (
                  <div className="ag-form-row">
                    <div className="ag-field">
                      <label className="ag-label" htmlFor={`${baseId}-start-time`}>
                        Début
                      </label>
                      <input
                        id={`${baseId}-start-time`}
                        type="time"
                        className="ag-input"
                        value={startTime}
                        onChange={(event) => setStartTime(event.target.value)}
                      />
                    </div>
                    <div className="ag-field">
                      <label className="ag-label" htmlFor={`${baseId}-end-time`}>
                        Fin <span className="ag-label-optional">(facultatif)</span>
                      </label>
                      <input
                        id={`${baseId}-end-time`}
                        type="time"
                        className="ag-input"
                        value={endTime}
                        onChange={(event) => setEndTime(event.target.value)}
                      />
                    </div>
                  </div>
                ) : null}
                {singleDay && fromRange ? (
                  <p className="ag-help">Ce type porte sur un seul jour : seul le premier jour est gardé.</p>
                ) : null}
              </>
            )}

            <FieldError message={error} />

            <div className="ag-cal-quick-actions">
              <button type="button" className="ag-link-button" onClick={openFull}>
                Plus d'options
              </button>
              <button type="submit" className="ag-button ag-button--small" disabled={saving}>
                {saving ? "Création…" : "Créer"}
              </button>
            </div>
          </form>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

// Ajout rapide ancré sur le jour cliqué : type en pastilles, titre, heure facultative. Entrée crée l'élément
// avec les rappels par défaut ; « Plus d'options » ouvre la fenêtre complète avec les valeurs saisies.
// Le formulaire repart de zéro à chaque ouverture.
export default function QuickAddPopover({ request, canManage = false, onClose, onOpenFull, onCreated }) {
  if (!request || !isIsoDate(request.start)) return null;
  return (
    <QuickAddContent
      key={`${request.start}-${request.end}-${request.nonce || 0}`}
      anchorEl={request.anchorEl || null}
      start={request.start}
      end={request.end || request.start}
      fromRange={Boolean(request.fromRange)}
      canManage={canManage}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      onOpenFull={onOpenFull}
      onCreated={onCreated}
    />
  );
}

export { QuickAddPopover };
