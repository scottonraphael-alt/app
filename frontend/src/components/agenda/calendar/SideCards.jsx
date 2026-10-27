import { useMemo } from "react";
import { BellRing, CalendarClock, CircleAlert, MapPin, RefreshCw, Settings2, TriangleAlert } from "lucide-react";

import "@/Agenda.css";

import { settingsStatus } from "../agendaConstants";
import { normalizeNextEvents } from "../calendarModel";
import { dateBlockParts, formatTimeRange, relativeDayLabel } from "../dateUtils";
import { typeClass } from "../TypeBadge";
import { joinClasses } from "./calendarHelpers";
import "./agenda-calendar.css";

function PanelError({ message, onRetry }) {
  return (
    <div className="ag-error" role="alert">
      <span className="ag-error-text">
        <CircleAlert size={15} aria-hidden="true" />
        {message}
      </span>
      {onRetry ? (
        <button type="button" className="ag-error-retry" onClick={onRetry}>
          <RefreshCw size={13} aria-hidden="true" />
          Réessayer
        </button>
      ) : null}
    </div>
  );
}

// « Prochains rendez-vous » : réunions et entrées à venir (upcoming.next_events), un clic ouvre le tiroir.
export function NextEventsCard({ events, today, loading = false, error = false, onRetry, onOpen }) {
  const items = useMemo(() => normalizeNextEvents(events), [events]);
  return (
    <section className="ag-panel ag-cal-side-card" aria-labelledby="ag-cal-next-title" aria-busy={loading}>
      <div className="ag-panel-header">
        <span className="ag-panel-icon">
          <CalendarClock size={20} aria-hidden="true" />
        </span>
        <div className="ag-panel-heading">
          <p className="ag-eyebrow">À venir</p>
          <h2 className="ag-panel-title" id="ag-cal-next-title">
            Prochains rendez-vous
          </h2>
        </div>
      </div>
      {error ? (
        <PanelError message="Impossible de charger les rendez-vous." onRetry={onRetry} />
      ) : loading ? (
        <div className="ag-skeleton-stack" aria-hidden="true">
          <span className="ag-skeleton" style={{ height: 52 }} />
          <span className="ag-skeleton" style={{ height: 52 }} />
        </div>
      ) : items.length ? (
        <ul className="ag-panel-body ag-cal-next-list">
          {items.map((item) => {
            const parts = dateBlockParts(item.start);
            const relative = relativeDayLabel(item.start, today);
            const time = item.allDay ? "Journée" : formatTimeRange(item.startTime, item.endTime);
            return (
              <li key={item.key}>
                <button type="button" className="ag-cal-next-item" onClick={() => onOpen(item)}>
                  <span className={joinClasses("ag-date-block ag-date-block--sm", typeClass(item.type))} aria-hidden="true">
                    <strong>{parts.dayNumber}</strong>
                    <small>{parts.weekday}</small>
                  </span>
                  <span className="ag-cal-next-text">
                    <strong className={item.cancelled ? "ag-strike" : undefined}>{item.title}</strong>
                    <small>
                      {[relative, time, item.label].filter(Boolean).join(" · ")}
                    </small>
                    {item.location ? (
                      <small className="ag-cal-next-place">
                        <MapPin size={11} aria-hidden="true" />
                        {item.location}
                      </small>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="ag-empty ag-empty--compact">
          <p>Aucun rendez-vous dans les 60 prochains jours.</p>
        </div>
      )}
    </section>
  );
}

const TONE_CLASS = { sage: "is-ok", danger: "is-error", muted: "is-muted" };

// Carte compacte « Rappels Discord » : état du salon, avertissement de salon public, lien « Configurer ».
export function RemindersCard({ settings, loading = false, error = false, isResponsable = false, onRetry, onConfigure }) {
  const status = settings ? settingsStatus(settings) : null;
  const StatusIcon = status?.icon || BellRing;
  const isPublic = settings?.channel_visibility === "public";
  return (
    <section className="ag-panel ag-cal-side-card" aria-labelledby="ag-cal-reminders-title" aria-busy={loading}>
      <div className="ag-panel-header">
        <span className="ag-panel-icon">
          <BellRing size={20} aria-hidden="true" />
        </span>
        <div className="ag-panel-heading">
          <p className="ag-eyebrow">Discord</p>
          <h2 className="ag-panel-title" id="ag-cal-reminders-title">
            Rappels Discord
          </h2>
        </div>
      </div>
      {error ? (
        <PanelError message="État des rappels indisponible." onRetry={onRetry} />
      ) : loading ? (
        <div className="ag-skeleton-stack" aria-hidden="true">
          <span className="ag-skeleton ag-skeleton-line" style={{ width: "70%" }} />
        </div>
      ) : (
        <div className="ag-panel-body ag-cal-reminders">
          <p className={joinClasses("ag-channel-status", TONE_CLASS[status?.tone] || "is-muted")}>
            <StatusIcon size={16} aria-hidden="true" />
            <span>{status ? status.label : "État des rappels inconnu"}</span>
          </p>
          {isPublic ? (
            <p className="ag-callout ag-callout--warning">
              <TriangleAlert size={15} aria-hidden="true" />
              <span>
                Ce salon semble visible par tous les membres. Les rappels contiennent l'ordre du jour : choisissez un salon
                réservé au staff.
              </span>
            </p>
          ) : null}
          <p className="ag-help">Rappels 7 jours, 2 jours, 1 jour et 1 heure avant, sauf pour les absences.</p>
          {isResponsable ? (
            <button type="button" className="ag-link-button" onClick={onConfigure}>
              <Settings2 size={14} aria-hidden="true" />
              Configurer
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}
