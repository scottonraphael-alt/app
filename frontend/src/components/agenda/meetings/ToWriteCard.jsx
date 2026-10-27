import { Link } from "react-router-dom";
import { ArrowRight, CircleCheck } from "lucide-react";

import "./meetings.css";

import { formatDayShort } from "../dateUtils";
import { PanelError } from "./MeetingsStates";

const VISIBLE = 3;

// Carte « À rédiger » : comptes-rendus en attente (overview.to_write, la plus récente d'abord).
export default function ToWriteCard({ meetings, count, today, loading = false, error = null, onRetry, onShowAll }) {
  const list = Array.isArray(meetings) ? meetings.filter((meeting) => meeting?.id) : [];
  const total = Number.isFinite(Number(count)) ? Number(count) : list.length;

  if (loading) {
    return (
      <section className="ag-meet-towrite" aria-busy="true" aria-label="À rédiger">
        <div className="ag-meet-hero-skeleton" aria-hidden="true">
          <span className="ag-skeleton ag-skeleton-line" style={{ width: "40%" }} />
          <span className="ag-skeleton" style={{ height: 38, width: 60 }} />
          <span className="ag-skeleton" style={{ height: 36 }} />
          <span className="ag-skeleton" style={{ height: 36 }} />
        </div>
      </section>
    );
  }

  return (
    <section className="ag-meet-towrite" aria-labelledby="ag-meet-towrite-title">
      <p className="ag-eyebrow" id="ag-meet-towrite-title">
        À rédiger
      </p>
      {error ? (
        <PanelError message="Impossible de charger les comptes-rendus à rédiger." onRetry={onRetry} />
      ) : total === 0 ? (
        <div className="ag-meet-towrite-done">
          <CircleCheck size={22} aria-hidden="true" />
          <p>Tous les comptes-rendus sont à jour.</p>
        </div>
      ) : (
        <>
          <p className="ag-meet-towrite-count">
            <strong>{total}</strong>
            <span>{total > 1 ? "comptes-rendus à rédiger" : "compte-rendu à rédiger"}</span>
          </p>
          <ul className="ag-meet-towrite-list">
            {list.slice(0, VISIBLE).map((meeting) => {
              const withYear = Boolean(today) && String(meeting.meeting_date || "").slice(0, 4) !== String(today).slice(0, 4);
              const date = formatDayShort(meeting.meeting_date, { withYear });
              return (
                <li key={meeting.id}>
                  <Link to={`/staff/meetings/${encodeURIComponent(meeting.id)}`} className="ag-meet-towrite-link">
                    <span className="ag-meet-towrite-name">{meeting.title || "Réunion"}</span>
                    {date ? <span className="ag-meet-towrite-date">· {date}</span> : null}
                    <ArrowRight size={15} aria-hidden="true" />
                  </Link>
                </li>
              );
            })}
          </ul>
          {total > VISIBLE && onShowAll ? (
            <button type="button" className="ag-link-button ag-meet-towrite-all" onClick={onShowAll}>
              Voir les {total} réunions à rédiger
            </button>
          ) : null}
        </>
      )}
    </section>
  );
}

export { ToWriteCard };
