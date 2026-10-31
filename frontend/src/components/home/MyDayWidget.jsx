import { Link } from "react-router-dom";
import { ArrowRight, Bell, CalendarClock, ClipboardList, Users } from "lucide-react";

function Section({ icon: Icon, title, items, empty, to, renderTail }) {
  return (
    <section className="hm-day-block" aria-label={title}>
      <h3><Icon size={16} aria-hidden="true" /> {title}</h3>
      {items.length === 0 ? (
        <p className="hm-muted">{empty}</p>
      ) : (
        <ul>
          {items.slice(0, 4).map((item) => (
            <li key={item.id}>
              <Link to={item.to || to}>
                {item.time && <span className="hm-time">{item.time}</span>}
                <span className="hm-item-title">{item.title}</span>
                {renderTail && renderTail(item)}
              </Link>
            </li>
          ))}
          {items.length > 4 && <li className="hm-muted">+ {items.length - 4} autre(s)</li>}
        </ul>
      )}
    </section>
  );
}

export default function MyDayWidget({ day }) {
  const { meetings, entries, tasks, unreadNotifications, isLoading, isError } = day;
  return (
    <section className="hm-card hm-day" aria-labelledby="hm-day-title" data-testid="my-day-widget">
      <div className="hm-card-head">
        <h2 id="hm-day-title">Ma journée</h2>
        <Link to="/staff/calendrier" className="hm-card-link">
          Agenda <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
      {isLoading ? (
        <p className="hm-muted" role="status">Chargement de ta journée…</p>
      ) : isError ? (
        <p className="hm-muted" role="alert">Impossible de charger ta journée pour le moment.</p>
      ) : (
        <div className="hm-day-grid">
          <Section icon={Users} title="Réunions" items={meetings} empty="Aucune réunion." to="/staff/meetings" />
          <Section icon={CalendarClock} title="Échéances" items={entries} empty="Aucune échéance." to="/staff/calendrier" />
          <Section icon={ClipboardList} title="Tâches à rendre" items={tasks} empty="Aucune tâche à rendre."
            to="/animateur/projects"
            renderTail={(t) => (t.sub ? <span className="hm-sub">{t.sub}</span> : null)} />
        </div>
      )}
      {unreadNotifications > 0 && (
        <Link to="/notifications" className="hm-notif">
          <Bell size={15} aria-hidden="true" />
          {unreadNotifications} notification{unreadNotifications > 1 ? "s" : ""} non lue{unreadNotifications > 1 ? "s" : ""}
        </Link>
      )}
    </section>
  );
}
