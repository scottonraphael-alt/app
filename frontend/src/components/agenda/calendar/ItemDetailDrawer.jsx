import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  CircleAlert,
  Copy,
  FileText,
  ListChecks,
  MapPin,
  Pencil,
  RefreshCw,
  Trash2,
  UserCheck,
  UserRound,
  Users,
} from "lucide-react";

import "@/Agenda.css";

import AgendaDialog from "../AgendaDialog";
import { AvatarStack, PersonLabel, peopleSummary } from "../HelperAvatar";
import ReminderSchedule from "../ReminderSchedule";
import TypeBadge, { PhaseBadge, Pill } from "../TypeBadge";
import { agendaQueries } from "../agendaApi";
import { ATTENDANCE, isValidAgendaId } from "../agendaConstants";
import { helperName, formatItemWhen } from "../calendarModel";
import { formatInstantRelative } from "../dateUtils";
import "./agenda-calendar.css";

const DESCRIPTION_PREVIEW = 280;
const AGENDA_PREVIEW = 5;
const MEETING_PEOPLE_MAX = 12;

function SectionTitle({ icon: Icon, children }) {
  return (
    <h3 className="ag-cal-drawer-title">
      <Icon size={15} aria-hidden="true" />
      {children}
    </h3>
  );
}

function DrawerSkeleton() {
  return (
    <div className="ag-skeleton-stack ag-cal-drawer-skeleton" aria-hidden="true">
      <span className="ag-skeleton ag-skeleton-line" style={{ width: "40%" }} />
      <span className="ag-skeleton" style={{ height: 44 }} />
      <span className="ag-skeleton ag-skeleton-line" style={{ width: "70%" }} />
      <span className="ag-skeleton" style={{ height: 64 }} />
    </div>
  );
}

// Description tronquée avec « Lire la suite » (texte brut, retours à la ligne conservés).
function Description({ text }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return null;
  const long = text.length > DESCRIPTION_PREVIEW;
  const shown = long && !expanded ? `${text.slice(0, DESCRIPTION_PREVIEW).trimEnd()}…` : text;
  return (
    <section className="ag-cal-drawer-section">
      <SectionTitle icon={FileText}>Description</SectionTitle>
      <p className="ag-cal-drawer-text">{shown}</p>
      {long ? (
        <button type="button" className="ag-link-button" onClick={() => setExpanded((old) => !old)}>
          {expanded ? "Réduire" : "Lire la suite"}
        </button>
      ) : null}
    </section>
  );
}

function EntryBody({ item }) {
  const entry = item.raw || {};
  const people = item.people || [];
  const author = entry.created_by;
  return (
    <>
      <Description text={item.description} />
      {people.length ? (
        <section className="ag-cal-drawer-section">
          <SectionTitle icon={Users}>{item.type === "permanence" ? "Personnes de permanence" : "Participants"}</SectionTitle>
          <div className="ag-cal-drawer-people">
            <AvatarStack people={people} max={6} size={30} />
            <span>{peopleSummary(people, 6)}</span>
          </div>
        </section>
      ) : null}
      <section className="ag-cal-drawer-section">
        <SectionTitle icon={ListChecks}>Rappels Discord</SectionTitle>
        <ReminderSchedule reminders={entry.reminders} />
      </section>
      {author ? (
        <p className="ag-cal-drawer-meta">
          Ajouté par {helperName(author)}
          {entry.updated_at ? ` · modifié ${formatInstantRelative(entry.updated_at)}` : ""}
        </p>
      ) : null}
    </>
  );
}

function AbsenceBody({ item }) {
  const absence = item.raw || {};
  const person = absence.helper || item.people[0];
  const declaredByOther = absence.created_by && absence.created_by.id !== absence.helper?.id;
  return (
    <>
      <section className="ag-cal-drawer-section">
        <SectionTitle icon={UserRound}>Personne</SectionTitle>
        <div className="ag-cal-drawer-people">{person ? <PersonLabel person={person} size={30} /> : null}</div>
        {item.openEnded ? (
          <p className="ag-help">Fin indéterminée : l'absence reste affichée jusqu'à l'indication du retour.</p>
        ) : null}
      </section>
      {item.description ? (
        <section className="ag-cal-drawer-section">
          <SectionTitle icon={FileText}>Motif</SectionTitle>
          <p className="ag-cal-drawer-text">{item.description}</p>
        </section>
      ) : null}
      {declaredByOther ? <p className="ag-cal-drawer-meta">Déclarée par {helperName(absence.created_by)}.</p> : null}
      <p className="ag-cal-drawer-meta">Les absences ne déclenchent pas de rappel Discord.</p>
    </>
  );
}

function MeetingBody({ item, query }) {
  const summary = item.raw || {};
  const detail = query.data;
  const preview = Array.isArray(summary.agenda_preview) ? summary.agenda_preview : [];
  const total = Number(summary.agenda_count) || preview.length;
  const extra = Math.max(0, total - Math.min(preview.length, AGENDA_PREVIEW));
  const participants = Array.isArray(detail?.participants) ? detail.participants : [];
  return (
    <>
      {preview.length ? (
        <section className="ag-cal-drawer-section">
          <SectionTitle icon={ListChecks}>Ordre du jour</SectionTitle>
          <ol className="ag-cal-drawer-agenda">
            {preview.slice(0, AGENDA_PREVIEW).map((title, index) => (
              <li key={`${index}-${title}`}>{title}</li>
            ))}
          </ol>
          {extra > 0 ? <p className="ag-help">+ {extra} autre{extra > 1 ? "s" : ""} point{extra > 1 ? "s" : ""}</p> : null}
        </section>
      ) : null}

      <section className="ag-cal-drawer-section">
        <SectionTitle icon={Users}>Participants</SectionTitle>
        {query.isPending ? (
          <div className="ag-skeleton-stack ag-cal-drawer-skeleton" aria-hidden="true">
            <span className="ag-skeleton" style={{ height: 30 }} />
          </div>
        ) : query.isError ? null : participants.length ? (
          <ul className="ag-cal-drawer-attendees">
            {participants.slice(0, MEETING_PEOPLE_MAX).map((person) => (
              <li key={person.id}>
                <PersonLabel person={person} size={26} />
                {person.attendance && person.attendance !== "invite" ? (
                  <small>{ATTENDANCE[person.attendance]?.label || ""}</small>
                ) : null}
              </li>
            ))}
            {participants.length > MEETING_PEOPLE_MAX ? (
              <li className="ag-cal-drawer-more">+ {participants.length - MEETING_PEOPLE_MAX} autres</li>
            ) : null}
          </ul>
        ) : (
          <p className="ag-help">Aucun participant renseigné.</p>
        )}
      </section>

      <section className="ag-cal-drawer-section">
        <SectionTitle icon={ListChecks}>Rappels Discord</SectionTitle>
        {query.isPending ? (
          <div className="ag-skeleton-stack ag-cal-drawer-skeleton" aria-hidden="true">
            <span className="ag-skeleton" style={{ height: 44 }} />
          </div>
        ) : query.isError ? null : (
          <ReminderSchedule reminders={detail?.reminders} />
        )}
      </section>

      {query.isError ? (
        <div className="ag-error" role="alert">
          <span className="ag-error-text">
            <CircleAlert size={15} aria-hidden="true" />
            Détails indisponibles.
          </span>
          <button type="button" className="ag-error-retry" onClick={() => query.refetch()}>
            <RefreshCw size={13} aria-hidden="true" />
            Réessayer
          </button>
        </div>
      ) : null}

      {item.cancelled && detail?.cancel_reason ? (
        <p className="ag-callout ag-callout--warning">
          <CircleAlert size={15} aria-hidden="true" />
          <span>Annulée : {detail.cancel_reason}</span>
        </p>
      ) : null}

      <Link className="ag-button ag-button--secondary ag-cal-drawer-open" to={`/staff/meetings/${encodeURIComponent(item.id)}`}>
        Ouvrir la réunion
        <ArrowUpRight size={16} aria-hidden="true" />
      </Link>
    </>
  );
}

// Tiroir de détail d'un élément du calendrier (ouvert par `?element=`). `item` null avec `loading` : squelette.
// Les actions arrivent du parent : `onEdit(item, detail)`, `onDuplicate(item)`, `onReturn(item)`, `onDelete(item)`.
export default function ItemDetailDrawer({
  open,
  onOpenChange,
  item,
  loading = false,
  today,
  isResponsable = false,
  viewerId = null,
  busy = false,
  onEdit,
  onDuplicate,
  onReturn,
  onDelete,
  onCloseAutoFocus,
}) {
  const isMeeting = item?.kind === "meeting";
  const meetingQuery = useQuery({
    ...agendaQueries.meeting(item?.id),
    enabled: Boolean(open && isMeeting && isValidAgendaId(item?.id)),
  });

  if (!item) {
    return (
      <AgendaDialog
        open={open}
        onOpenChange={onOpenChange}
        side="right"
        title="Chargement…"
        description="Chargement de l'élément du calendrier."
        descriptionHidden
        busy={loading}
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <DrawerSkeleton />
      </AgendaDialog>
    );
  }

  const mineAbsence = item.kind === "absence" && String(item.raw?.helper?.id) === String(viewerId);
  const canReturn = mineAbsence && item.phase === "en_cours" && item.start < today;
  const canEdit = item.canEdit && (!isMeeting || isResponsable);
  const canDelete = item.canEdit && (!isMeeting || isResponsable);
  const canDuplicate = item.kind === "entry";

  const header = (
    <>
      <TypeBadge type={item.type} label={item.label} strike={item.cancelled} />
      {item.cancelled ? (
        <Pill tone="neutral" size="sm">
          Annulée
        </Pill>
      ) : item.kind === "meeting" && item.phase ? (
        <PhaseBadge phase={item.phase} size="sm" />
      ) : null}
      {item.kind === "absence" && item.phase ? <PhaseBadge phase={item.phase} kind="absence" size="sm" /> : null}
    </>
  );

  const footer =
    canEdit || canDelete || canDuplicate || canReturn ? (
      <>
        <div className="ag-dialog-footer-start">
          {canDelete ? (
            <button
              type="button"
              className="ag-button ag-button--danger"
              disabled={busy}
              onClick={() => onDelete(item)}
            >
              <Trash2 size={15} aria-hidden="true" />
              Supprimer
            </button>
          ) : null}
        </div>
        <div className="ag-dialog-footer-end">
          {canDuplicate ? (
            <button type="button" className="ag-button ag-button--secondary" onClick={() => onDuplicate(item)}>
              <Copy size={15} aria-hidden="true" />
              Dupliquer
            </button>
          ) : null}
          {canReturn ? (
            <button type="button" className="ag-button ag-button--secondary" disabled={busy} onClick={() => onReturn(item)}>
              <UserCheck size={15} aria-hidden="true" />
              Je suis de retour
            </button>
          ) : null}
          {canEdit ? (
            <button
              type="button"
              className="ag-button"
              disabled={busy || (isMeeting && !meetingQuery.data)}
              onClick={() => onEdit(item, meetingQuery.data || null)}
            >
              <Pencil size={15} aria-hidden="true" />
              Modifier
            </button>
          ) : null}
        </div>
      </>
    ) : null;

  return (
    <AgendaDialog
      open={open}
      onOpenChange={onOpenChange}
      side="right"
      headerExtra={header}
      title={item.title}
      description={formatItemWhen(item)}
      footer={footer}
      busy={busy}
      bodyClassName="ag-cal-drawer-body"
      onCloseAutoFocus={onCloseAutoFocus}
    >
      {item.location ? (
        <p className="ag-cal-drawer-location">
          <MapPin size={15} aria-hidden="true" />
          {item.location}
        </p>
      ) : null}
      {item.kind === "meeting" ? <MeetingBody item={item} query={meetingQuery} /> : null}
      {item.kind === "entry" ? <EntryBody item={item} /> : null}
      {item.kind === "absence" ? <AbsenceBody item={item} /> : null}
    </AgendaDialog>
  );
}

export { ItemDetailDrawer };
