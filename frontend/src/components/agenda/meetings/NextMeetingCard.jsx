import { Link } from "react-router-dom";
import { ArrowRight, CalendarDays, CalendarPlus, Clock, ListChecks, MapPin, TriangleAlert } from "lucide-react";

import "./meetings.css";

import { AvatarStack } from "../HelperAvatar";
import ReminderSchedule from "../ReminderSchedule";
import { capitalize, formatDayLong, formatDaysUntil, formatTimeRange } from "../dateUtils";
import { PanelError } from "./MeetingsStates";

const AGENDA_PREVIEW = 3;

function agendaTitles(meeting) {
  const items = Array.isArray(meeting?.agenda_items) ? meeting.agenda_items : [];
  const titles = items.map((item) => (typeof item?.title === "string" ? item.title.trim() : "")).filter(Boolean);
  if (titles.length) return titles;
  return Array.isArray(meeting?.agenda_preview) ? meeting.agenda_preview.filter(Boolean) : [];
}

function plural(count, singular, pluralForm) {
  return `${count} ${count > 1 ? pluralForm : singular}`;
}

// Carte « Prochaine réunion » : overview.next_meeting (MeetingDetailOut complet), aucun appel en plus.
export default function NextMeetingCard({ meeting, today, loading = false, error = null, onRetry, canManage = false, onPlan }) {
  if (loading) {
    return (
      <section className="ag-meet-hero" aria-busy="true" aria-label="Prochaine réunion">
        <div className="ag-meet-hero-skeleton" aria-hidden="true">
          <span className="ag-skeleton ag-skeleton-line" style={{ width: "40%" }} />
          <span className="ag-skeleton" style={{ height: 30, width: "70%" }} />
          <span className="ag-skeleton ag-skeleton-line" style={{ width: "55%" }} />
          <span className="ag-skeleton" style={{ height: 64 }} />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="ag-meet-hero ag-meet-hero--error" aria-label="Prochaine réunion">
        <p className="ag-eyebrow">Prochaine réunion</p>
        <PanelError message="Impossible de charger la prochaine réunion." onRetry={onRetry} />
      </section>
    );
  }

  if (!meeting) {
    return (
      <section className="ag-meet-hero ag-meet-hero--empty" aria-labelledby="ag-meet-next-title">
        <p className="ag-eyebrow">Prochaine réunion</p>
        <h2 id="ag-meet-next-title" className="ag-meet-hero-title">
          Aucune réunion prévue.
        </h2>
        <p className="ag-meet-hero-text">
          {canManage
            ? "Planifiez la prochaine réunion : l'équipe recevra les rappels sur Discord."
            : "Un responsable planifiera la prochaine réunion de l'équipe."}
        </p>
        {canManage ? (
          <div className="ag-meet-hero-actions">
            <button type="button" className="ag-button ag-button--blue" onClick={onPlan}>
              <CalendarPlus size={16} aria-hidden="true" />
              Planifier une réunion
            </button>
          </div>
        ) : null}
      </section>
    );
  }

  const when = formatDaysUntil(meeting.meeting_date, today);
  const titles = agendaTitles(meeting);
  const total = Array.isArray(meeting.agenda_items) && meeting.agenda_items.length
    ? meeting.agenda_items.length
    : Number(meeting.agenda_count) || titles.length;
  const hidden = Math.max(0, total - AGENDA_PREVIEW);
  const participants = Array.isArray(meeting.participants) ? meeting.participants : [];
  const absent = Array.isArray(meeting.participants_absent) ? meeting.participants_absent.length : 0;
  const time = formatTimeRange(meeting.start_time, meeting.end_time);
  const detailUrl = `/staff/meetings/${encodeURIComponent(meeting.id)}`;

  return (
    <section className="ag-meet-hero" aria-labelledby="ag-meet-next-title">
      <p className="ag-eyebrow">{when ? `Prochaine réunion · ${when}` : "Prochaine réunion"}</p>
      <h2 id="ag-meet-next-title" className="ag-meet-hero-title">
        {meeting.title || "Réunion"}
      </h2>

      <ul className="ag-meet-hero-info">
        <li>
          <CalendarDays size={15} aria-hidden="true" />
          {capitalize(formatDayLong(meeting.meeting_date))}
        </li>
        {time ? (
          <li>
            <Clock size={15} aria-hidden="true" />
            {time}
          </li>
        ) : null}
        {meeting.location ? (
          <li>
            <MapPin size={15} aria-hidden="true" />
            <span className="ag-meet-hero-location">{meeting.location}</span>
          </li>
        ) : null}
      </ul>

      <div className="ag-meet-hero-agenda">
        <p className="ag-meet-hero-label">
          <ListChecks size={14} aria-hidden="true" />
          Ordre du jour
        </p>
        {titles.length ? (
          <ol>
            {titles.slice(0, AGENDA_PREVIEW).map((title, index) => (
              <li key={`${index}-${title}`}>{title}</li>
            ))}
          </ol>
        ) : (
          <p className="ag-meet-hero-muted">Aucun point pour l'instant.</p>
        )}
        {hidden > 0 ? <p className="ag-meet-hero-more">+ {plural(hidden, "autre point", "autres points")}</p> : null}
      </div>

      <div className="ag-meet-hero-people">
        {participants.length ? (
          <>
            <AvatarStack people={participants} max={5} size={28} />
            <span>{plural(participants.length, "participant", "participants")}</span>
          </>
        ) : (
          <span className="ag-meet-hero-muted">Aucun participant indiqué.</span>
        )}
        {absent > 0 ? (
          <span className="ag-meet-hero-absent">
            <TriangleAlert size={14} aria-hidden="true" />
            {absent > 1 ? `${absent} participants absents ce jour-là` : "1 participant absent ce jour-là"}
          </span>
        ) : null}
      </div>

      <ReminderSchedule reminders={meeting.reminders} variant="short" className="ag-meet-hero-reminders" />

      <div className="ag-meet-hero-actions">
        <Link to={detailUrl} className="ag-button ag-button--blue">
          Ouvrir
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
        <Link to={`${detailUrl}#ordre-du-jour`} className="ag-button ag-button--secondary ag-meet-hero-secondary">
          <ListChecks size={16} aria-hidden="true" />
          Préparer l'ordre du jour
        </Link>
      </div>
    </section>
  );
}

export { NextMeetingCard };
