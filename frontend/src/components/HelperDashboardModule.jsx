import { resolveAvatarUrl } from "../utils/avatar";
import {
  ArrowRight,
  Archive,
  BookHeart,
  FolderOpen,
  HeartHandshake,
  Plus,
  Users,
} from "lucide-react";
import { Link } from "react-router-dom";

function ticketDate(ticket) {
  const value = Date.parse(ticket.updated_at || ticket.created_at || "");
  return Number.isNaN(value) ? 0 : value;
}

export default function HelperDashboardModule({
  tickets = [],
  helper,
  isAdmin = false,
}) {
  const myTickets = helper?.id
    ? tickets
        .filter(
          (ticket) =>
            String(ticket.assigned_helper?.id) === String(helper.id)
        )
        .sort((a, b) => ticketDate(b) - ticketDate(a))
        .slice(0, 5)
    : [];

  const shortcuts = [
    {
      to: "/suivis",
      title: "Tous les suivis",
      description: "Retrouver l’ensemble des dossiers d’aide.",
      Icon: FolderOpen,
      tone: "sage",
    },
    {
      to: "/archives",
      title: "Archives des suivis",
      description: "Consulter les accompagnements archivés.",
      Icon: Archive,
      tone: "clay",
    },
    {
      to: "/resources",
      title: "Ressources",
      description: "Ouvrir les documents et outils d’accompagnement.",
      Icon: BookHeart,
      tone: "blue",
    },
  ];

  return (
    <section className="nd-helper-v2" aria-labelledby="helper-module-title">
      <header className="nd-helper-v2-heading">
        <div>
          <p className="nd-eyebrow">ACCOMPAGNEMENT</p>
          <h2 id="helper-module-title">Mon espace helper</h2>
          <p className="nd-description">
            Retrouvez vos suivis et les outils pour accompagner les membres.
          </p>
        </div>

        <div className="nd-helper-v2-actions">
          {isAdmin && (
            <Link to="/admin" className="nd-helper-v2-manage">
              <Users size={17} aria-hidden="true" />
              Gérer les attributions
            </Link>
          )}

          <Link to="/new" className="nd-button">
            <Plus size={17} aria-hidden="true" />
            Nouveau suivi
          </Link>
        </div>
      </header>

      <div className="nd-helper-v2-layout">
        <section
          className="nd-helper-v2-panel"
          aria-labelledby="helper-recent-title"
        >
          <div className="nd-helper-v2-panel-heading">
            <span className="nd-helper-v2-symbol">
              <HeartHandshake size={21} aria-hidden="true" />
            </span>

            <div>
              <h3 id="helper-recent-title">Mes derniers suivis</h3>
              <p>Les dossiers dont vous êtes l’interlocuteur.</p>
            </div>
          </div>

          {myTickets.length > 0 ? (
            <div className="nd-helper-v2-list">
              {myTickets.map((ticket) => {
                const member = ticket.member || {};
                const name =
                  member.display_name ||
                  member.username ||
                  "Membre";

                const active = ticket.status === "active";

                return (
                  <Link
                    key={ticket.id}
                    to={`/tickets/${ticket.id}`}
                    className="nd-helper-v2-ticket"
                  >
                    <span className="nd-helper-v2-avatar">
                      {member.avatar_url ? (
                        <img
                          src={resolveAvatarUrl(member.avatar_url)}
                          alt=""
                          loading="lazy"
                        />
                      ) : (
                        <Users size={19} aria-hidden="true" />
                      )}
                    </span>

                    <span className="nd-helper-v2-ticket-copy">
                      <strong>{name}</strong>
                      <small>{ticket.title || "Ticket d’aide"}</small>
                    </span>

                    <span
                      className={`nd-helper-v2-status ${
                        active ? "is-active" : ""
                      }`}
                    >
                      {active ? "En cours" : "Archivé"}
                    </span>

                    <ArrowRight
                      className="nd-helper-v2-ticket-arrow"
                      size={17}
                      aria-hidden="true"
                    />
                  </Link>
                );
              })}
            </div>
          ) : (
            <div className="nd-helper-v2-empty">
              <HeartHandshake size={30} aria-hidden="true" />
              <h4>Votre espace est prêt.</h4>
              <p>
                Les suivis qui vous sont attribués apparaîtront ici.
                Vous pouvez déjà consulter les dossiers ou les ressources.
              </p>
            </div>
          )}

          <Link to="/suivis" className="nd-helper-v2-all">
            Voir tous les suivis
            <ArrowRight size={17} aria-hidden="true" />
          </Link>
        </section>

        <nav
          className="nd-helper-v2-shortcuts"
          aria-label="Outils des helpers"
        >
          {shortcuts.map(({ to, title, description, Icon, tone }) => (
            <Link
              key={to}
              to={to}
              className={`nd-helper-v2-shortcut nd-helper-v2-shortcut--${tone}`}
            >
              <span className="nd-helper-v2-shortcut-icon">
                <Icon size={22} aria-hidden="true" />
              </span>

              <span className="nd-helper-v2-shortcut-copy">
                <strong>{title}</strong>
                <small>{description}</small>
              </span>

              <ArrowRight size={18} aria-hidden="true" />
            </Link>
          ))}
        </nav>
      </div>
    </section>
  );
}
