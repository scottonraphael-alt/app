import { useEffect, useMemo, useState } from "react";
import {
  addDays,
  addMonths,
  endOfMonth,
  endOfWeek,
  format,
  isBefore,
  isSameDay,
  isSameMonth,
  isWithinInterval,
  parseISO,
  startOfMonth,
  startOfWeek,
  subMonths,
} from "date-fns";
import { fr } from "date-fns/locale";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  FilePlus2,
  FileText,
  Plus,
  RadioTower,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";

const WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

function toIsoDate(date) {
  return format(date, "yyyy-MM-dd");
}

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}



function HelperAvatar({ helper, size = 20 }) {
  const [imageError, setImageError] = useState(false);
  const label = helper?.display_name || helper?.username || "?";
  const avatarUrl = helper?.avatar_url;

  if (!avatarUrl || imageError) {
    return (
      <span
        className="helper-avatar-fallback"
        style={{
          width: size,
          height: size,
          lineHeight: `${size}px`,
        }}
        title={label}
      >
        {label.charAt(0).toUpperCase()}
      </span>
    );
  }

  return (
    <img
      src={avatarUrl}
      alt={label}
      width={size}
      height={size}
      className="helper-avatar-image"
      onError={() => setImageError(true)}
    />
  );
}

export default function AbsenceCalendarPage({ isResponsable }) {
  const [absences, setAbsences] = useState([]);
  const [meetings, setMeetings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [mode, setMode] = useState("view"); // "view" | "absence" | "meeting"
  const [selection, setSelection] = useState(null);
  const [viewedDay, setViewedDay] = useState(null);
  const [reason, setReason] = useState("");
  const [meetingDay, setMeetingDay] = useState(null);
  const [meetingTitle, setMeetingTitle] = useState("");
  const [meetingAgenda, setMeetingAgenda] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let isMounted = true;
    Promise.all([api.get("/staff/calendrier"), api.get("/staff/meetings")])
      .then(([absencesResponse, meetingsResponse]) => {
        if (!isMounted) return;
        setAbsences(absencesResponse.data);
        setMeetings(meetingsResponse.data);
      })
      .catch((error) => {
        toast.error(getErrorMessage(error));
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, []);

  const days = useMemo(() => {
    const start = startOfWeek(startOfMonth(currentMonth), { weekStartsOn: 1 });
    const end = endOfWeek(endOfMonth(currentMonth), { weekStartsOn: 1 });
    const result = [];
    let cursor = start;
    while (cursor <= end) {
      result.push(cursor);
      cursor = addDays(cursor, 1);
    }
    return result;
  }, [currentMonth]);

  const absencesByDay = useMemo(() => {
    const map = new Map();
    for (const entry of absences) {
      const start = parseISO(entry.start_date);
      const end = parseISO(entry.end_date);
      for (const day of days) {
        const withinRange =
          isWithinInterval(day, { start, end }) || isSameDay(day, start) || isSameDay(day, end);
        if (withinRange) {
          const key = toIsoDate(day);
          if (!map.has(key)) map.set(key, []);
          map.get(key).push(entry);
        }
      }
    }
    return map;
  }, [absences, days]);

  const meetingsByDay = useMemo(() => {
    const map = new Map();
    for (const meeting of meetings) {
      if (!meeting.meeting_date) continue;
      if (!map.has(meeting.meeting_date)) map.set(meeting.meeting_date, []);
      map.get(meeting.meeting_date).push(meeting);
    }
    return map;
  }, [meetings]);

  const resetPanels = () => {
    setSelection(null);
    setReason("");
    setMeetingDay(null);
    setMeetingTitle("");
    setMeetingAgenda("");
  };

  const enterAbsenceMode = () => {
    setMode("absence");
    setViewedDay(null);
    resetPanels();
  };

  const enterMeetingMode = () => {
    setMode("meeting");
    setViewedDay(null);
    resetPanels();
  };

  const cancelMode = () => {
    setMode("view");
    resetPanels();
  };

  const handleDayClick = (day) => {
    if (mode === "view") {
      setViewedDay(day);
      return;
    }
    if (mode === "meeting") {
      setMeetingDay(day);
      return;
    }
    if (!selection || !selection.start) {
      setSelection({ start: day, end: day });
      return;
    }
    if (isBefore(day, selection.start)) {
      setSelection({ start: day, end: day });
      return;
    }
    setSelection({ start: selection.start, end: day });
  };

  const submitAbsence = async () => {
    if (!selection) return;
    setSubmitting(true);
    try {
      const response = await api.post("/staff/calendrier", {
        start_date: toIsoDate(selection.start),
        end_date: toIsoDate(selection.end),
        reason,
      });
      setAbsences((current) => [...current, response.data]);
      cancelMode();
      toast.success("Absence enregistrée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  const submitMeeting = async () => {
    if (!meetingDay || !meetingTitle.trim()) {
      toast.error("Ajoutez au moins un titre.");
      return;
    }
    setSubmitting(true);
    try {
      const response = await api.post("/staff/meetings", {
        title: meetingTitle,
        agenda: meetingAgenda,
        meeting_date: toIsoDate(meetingDay),
      });
      setMeetings((current) => [response.data, ...current]);
      cancelMode();
      toast.success("Réunion ajoutée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  const removeAbsence = async (absenceId) => {
    try {
      await api.delete(`/staff/calendrier/${absenceId}`);
      setAbsences((current) => current.filter((entry) => entry.id !== absenceId));
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const upcoming = [...absences].sort((a, b) => a.start_date.localeCompare(b.start_date));
  const viewedDayAbsences = viewedDay ? absencesByDay.get(toIsoDate(viewedDay)) || [] : [];
  const viewedDayMeetings = viewedDay ? meetingsByDay.get(toIsoDate(viewedDay)) || [] : [];

  return (
    <section className="page-content staff-page" data-testid="absence-calendar-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">ESPACE STAFF</p>
          <h1>Calendrier </h1>
        </div>
        <div className="dashboard-actions">
          {mode === "view" && isResponsable && (
            <button className="calm-primary-button is-secondary" type="button" onClick={enterMeetingMode} data-testid="enter-meeting-mode-button">
              <Plus size={17} /> Ajouter une réunion
            </button>
          )}
          {mode === "view" && (
            <button className="calm-primary-button" type="button" onClick={enterAbsenceMode} data-testid="enter-absence-mode-button">
              <CalendarPlus size={17} /> Entrer une absence
            </button>
          )}
          {mode !== "view" && (
            <button className="calm-primary-button is-cancel" type="button" onClick={cancelMode}>
              <X size={17} /> Annuler
            </button>
          )}
        </div>
      </header>

      <div className="staff-grid">
        <div className="absence-calendar">
          <div className="absence-calendar-header">
            <h2>{capitalize(format(currentMonth, "MMMM yyyy", { locale: fr }))}</h2>
            <div className="absence-calendar-nav">
              <button type="button" onClick={() => setCurrentMonth((current) => subMonths(current, 1))} aria-label="Mois précédent">
                <ChevronLeft size={16} />
              </button>
              <button type="button" onClick={() => setCurrentMonth(new Date())}>
                Aujourd’hui
              </button>
              <button type="button" onClick={() => setCurrentMonth((current) => addMonths(current, 1))} aria-label="Mois suivant">
                <ChevronRight size={16} />
              </button>
            </div>
          </div>

          {mode === "absence" && (
            <p className="absence-mode-hint">Sélectionnez une date de début, puis une date de fin (ou cliquez le même jour pour une absence d’un jour).</p>
          )}
          {mode === "meeting" && (
            <p className="absence-mode-hint">Cliquez sur le jour de la réunion à ajouter.</p>
          )}

          <div className="absence-calendar-weekdays">
            {WEEKDAYS.map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>

          <div className="absence-calendar-grid">
            {days.map((day) => {
              const key = toIsoDate(day);
              const dayAbsences = absencesByDay.get(key) || [];
              const dayMeetings = meetingsByDay.get(key) || [];
              const inCurrentMonth = isSameMonth(day, currentMonth);
              const isToday = isSameDay(day, new Date());
              const isSelected =
                mode === "absence" &&
                selection &&
                isWithinInterval(day, { start: selection.start, end: selection.end });
              const isMeetingPicked = mode === "meeting" && meetingDay && isSameDay(day, meetingDay);
              const isViewed = mode === "view" && viewedDay && isSameDay(day, viewedDay);

              const classNames = ["absence-day"];
              if (!inCurrentMonth) classNames.push("is-outside");
              if (isToday) classNames.push("is-today");
              if (isSelected) classNames.push("is-selected");
              if (isMeetingPicked) classNames.push("is-selected");
              if (isViewed) classNames.push("is-viewed");

              return (
                <button type="button" key={key} className={classNames.join(" ")} onClick={() => handleDayClick(day)}>
                  <span className="absence-day-number">{format(day, "d")}</span>
                  <span className="absence-day-chips">
                    {dayAbsences.slice(0, 3).map((entry) => (
                      <HelperAvatar helper={entry.helper} size={18} key={entry.id} />
                    ))}
                    {dayAbsences.length > 3 && <span className="absence-day-chip is-more">+{dayAbsences.length - 3}</span>}
                  </span>
                  {dayMeetings.length > 0 && (
                    <span className="absence-day-events">
                      {dayMeetings.slice(0, 2).map((meeting) => (
                        <span className="absence-day-event" key={meeting.id} title={meeting.title}>
                          {meeting.title}
                        </span>
                      ))}
                      {dayMeetings.length > 2 && <span className="absence-day-event is-more">+{dayMeetings.length - 2}</span>}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {mode === "view" && viewedDay && (
            <div className="absence-detail-panel">
              <div>
                <strong>{capitalize(format(viewedDay, "EEEE d MMMM yyyy", { locale: fr }))}</strong>
                <button type="button" className="icon-button" onClick={() => setViewedDay(null)} aria-label="Fermer">
                  <X size={15} />
                </button>
              </div>

              {viewedDayAbsences.length === 0 && viewedDayMeetings.length === 0 ? (
                <p className="resources-empty">Rien de prévu ce jour.</p>
              ) : (
                <>
                  {viewedDayAbsences.length > 0 && (
                    <div className="absence-detail-list">
                      {viewedDayAbsences.map((entry) => (
                        <div className="absence-detail-row" key={entry.id}>
                          <HelperAvatar helper={entry.helper} size={30} />
                          <div>
                            <strong>{entry.helper.display_name || entry.helper.username}</strong>
                            <small>
                              {entry.start_date === entry.end_date
                                ? entry.start_date
                                : `${entry.start_date} → ${entry.end_date}`}
                            </small>
                            {entry.reason && <p>{entry.reason}</p>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {viewedDayMeetings.length > 0 && (
                    <div className="absence-detail-list">
                      {viewedDayMeetings.map((meeting) => (
                        <div className="absence-detail-row absence-meeting-info-row" key={meeting.id}>
                          <span className="absence-meeting-icon">
                            <FileText size={16} />
                          </span>
                          <div>
                            <strong>{meeting.title}</strong>
                            <small>Par {meeting.author.display_name || meeting.author.username}</small>
                            {meeting.agenda && <p>{meeting.agenda}</p>}
                            <span className={`meeting-status-badge ${meeting.status === "en_attente_resume" ? "is-pending" : "is-done"}`}>
                              {meeting.status === "en_attente_resume" ? "En attente de résumé" : "Rédigé"}
                            </span>
                          </div>
                          <Link className="icon-button absence-meeting-open" to={`/staff/meetings/${meeting.id}`} aria-label="Ouvrir la réunion" title="Ouvrir">
                            <ArrowUpRight size={16} />
                          </Link>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {mode === "absence" && selection && (
            <div className="absence-confirm-panel">
              <div>
                <strong>
                  {isSameDay(selection.start, selection.end)
                    ? format(selection.start, "d MMMM yyyy", { locale: fr })
                    : `${format(selection.start, "d MMM", { locale: fr })} → ${format(selection.end, "d MMMM yyyy", { locale: fr })}`}
                </strong>
                <button type="button" className="icon-button" onClick={() => setSelection(null)} aria-label="Réinitialiser la sélection">
                  <X size={15} />
                </button>
              </div>
              <textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Motif (optionnel)" maxLength={500} rows={2} />
              <button className="calm-primary-button" type="button" onClick={submitAbsence} disabled={submitting}>
                {submitting ? "Enregistrement…" : "Ajouter l’absence"}
              </button>
            </div>
          )}

          {mode === "meeting" && meetingDay && (
            <div className="meeting-inline-form">
              <div className="meeting-inline-form-header">
                <strong>{capitalize(format(meetingDay, "EEEE d MMMM yyyy", { locale: fr }))}</strong>
                <button type="button" className="icon-button" onClick={() => setMeetingDay(null)} aria-label="Réinitialiser la sélection">
                  <X size={15} />
                </button>
              </div>
              <input
                className="meeting-inline-input"
                value={meetingTitle}
                onChange={(event) => setMeetingTitle(event.target.value)}
                placeholder="Titre de la réunion"
                maxLength={160}
              />
              <textarea
                className="meeting-inline-textarea"
                value={meetingAgenda}
                onChange={(event) => setMeetingAgenda(event.target.value)}
                placeholder="Raison / ordre du jour (optionnel)"
                rows={4}
              />
              <p className="meeting-inline-hint">Le résumé détaillé se rédige ensuite depuis la page « Résumés de réunions ».</p>
              <button className="meeting-inline-submit" type="button" onClick={submitMeeting} disabled={submitting}>
                <FilePlus2 size={17} /> {submitting ? "Enregistrement…" : "Ajouter la réunion"}
              </button>
            </div>
          )}
        </div>

        <aside className="absence-upcoming">
          <p className="eyebrow">ABSENCES À VENIR</p>
          {loading ? (
            <p className="resources-empty">Chargement…</p>
          ) : upcoming.length === 0 ? (
            <p className="resources-empty">Aucune absence enregistrée.</p>
          ) : (
            upcoming.map((entry) => (
              <div className="absence-upcoming-row" key={entry.id}>
                <HelperAvatar helper={entry.helper} size={28} />
                <div>
                  <strong>{entry.helper.display_name || entry.helper.username}</strong>
                  <small>
                    {entry.start_date === entry.end_date
                      ? entry.start_date
                      : `${entry.start_date} → ${entry.end_date}`}
                  </small>
                  {entry.reason && <p>{entry.reason}</p>}
                </div>
                <button type="button" className="icon-button" onClick={() => removeAbsence(entry.id)} aria-label="Supprimer l’absence">
                  <Trash2 size={15} />
                </button>
              </div>
            ))
          )}
        </aside>
      </div>
    </section>
  );
}
