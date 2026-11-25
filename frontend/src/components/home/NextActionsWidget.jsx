import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, ClipboardCheck, UserRoundPlus } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { agendaQueries } from "../agenda/agendaApi";
import { normalizeNextEvents } from "../agenda/calendarModel";
import { addDaysIso, relativeDayLabel } from "../agenda/dateUtils";
import { MotionRows } from "../motion/Motion";

const parisClock = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris", hourCycle: "h23", hour: "2-digit", minute: "2-digit",
});

export default function NextActionsWidget({ tickets, helperId, canSeeTickets, canSeeAgenda, canSeeProjects, isResponsable }) {
  const projects = useQuery({
    queryKey: ["home", "next-actions", "projects", helperId],
    enabled: Boolean(helperId && canSeeProjects),
    queryFn: async ({ signal }) => (await api.get("/animateur/projects/workspace/overview", { signal })).data,
    retry: false,
  });
  const upcoming = useQuery({ ...agendaQueries.upcoming(), enabled: canSeeAgenda });
  const today = upcoming.data?.today;
  const now = parisClock.format();
  const events = today ? normalizeNextEvents(upcoming.data.next_events).filter(event =>
    !event.cancelled && event.start >= today && event.start <= addDaysIso(today, 2)
    && (event.start !== today || !event.startTime || event.startTime >= now),
  ) : [];
  const reviews = (projects.data?.projects || []).filter(project =>
    project.status === "en_cours" && project.task_counts?.rendu > 0
    && (isResponsable || String(project.created_by?.id) === String(helperId)),
  );
  const waiting = canSeeTickets ? tickets.filter(ticket => ticket.status === "active" && !ticket.assigned_helper?.id) : [];

  const nextReview = project => ({
    key: `review:${project.id}`, Icon: ClipboardCheck, title: project.title,
    detail: `${project.task_counts.rendu} à valider`,
    to: `/animateur/projects/${encodeURIComponent(project.id)}?taches=a-valider`,
  });
  const nextTicket = ticket => ({
    key: `ticket:${ticket.id}`, Icon: UserRoundPlus, title: ticket.title || ticket.member?.display_name || "Dossier d’accompagnement",
    detail: "Sans interlocuteur", to: `/tickets/${encodeURIComponent(ticket.id)}`,
  });
  const nextEvent = event => ({
    key: event.key, Icon: CalendarClock, title: event.title,
    detail: [relativeDayLabel(event.start, today), event.startTime].filter(Boolean).join(" · "),
    to: `/staff/calendrier?element=${encodeURIComponent(`${event.kind}:${event.id}`)}`,
  });
  const actions = [];
  // Leave room for one action of each kind before filling the remaining slots.
  for (let index = 0; index < 3 && actions.length < 3; index++) {
    if (reviews[index]) actions.push(nextReview(reviews[index]));
    if (waiting[index]) actions.push(nextTicket(waiting[index]));
    if (events[index]) actions.push(nextEvent(events[index]));
  }
  const loading = (canSeeProjects && projects.isPending) || (canSeeAgenda && upcoming.isPending);
  const failed = (canSeeProjects && projects.isError) || (canSeeAgenda && upcoming.isError);

  return <section className="hm-card hm-next-actions" aria-labelledby="hm-next-actions-title" data-iris-reveal="card">
    <div className="hm-card-head"><h2 id="hm-next-actions-title">À traiter maintenant</h2></div>
    <MotionRows as="ul" className="hm-next-list">
      {actions.slice(0, 3).map(({ key, Icon, title, detail, to }) => <li key={key}>
        <Link to={to} data-iris-link="">
          <span className="hm-next-icon" data-iris-link-icon=""><Icon size={17} aria-hidden="true" /></span>
          <span><strong>{title}</strong><small>{detail}</small></span>
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </li>)}
    </MotionRows>
    {!actions.length && <p className="hm-muted" role="status">{loading ? "Recherche des actions à venir…" : failed ? "Certaines actions sont indisponibles." : "Rien à traiter pour le moment."}</p>}
  </section>;
}
