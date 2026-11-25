import { resolveAvatarUrl } from "../utils/avatar";
import { useState } from "react";
import {
  ArrowRight,
  Archive,
  BookHeart,
  FolderOpen,
  HeartHandshake,
  PanelRightOpen,
  Plus,
  Users,
} from "lucide-react";
import { Link } from "react-router-dom";
import TicketPreview from "./casework/TicketPreview";
import ChangeCue from "./ux/ChangeCue";

function ticketDate(ticket) {
  const value = Date.parse(ticket.updated_at || ticket.created_at || "");
  return Number.isNaN(value) ? 0 : value;
}

export default function HelperDashboardModule({
  tickets = [],
  helper,
  isAdmin = false,
  onTicketUpdate,
  onTicketDeleted,
}) {
  const [preview, setPreview] = useState(null);
  const openTickets = tickets.filter(ticket => ticket.status === "active");
  const unassignedCount = openTickets.filter(ticket => !ticket.assigned_helper?.id).length;
  const mineCount = helper?.id ? openTickets.filter(ticket => String(ticket.assigned_helper?.id) === String(helper.id)).length : 0;
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
          <div className="iris-assignment-counts" aria-label="Attribution des suivis ouverts">
            <span>À attribuer <ChangeCue as="strong" value={unassignedCount}>{unassignedCount}</ChangeCue></span>
            <span>Mes suivis <ChangeCue as="strong" value={mineCount}>{mineCount}</ChangeCue></span>
          </div>
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
            <span className="nd-helper-v2-symbol" data-iris-reveal="badge">
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
                  <div className="iris-ticket-row nd-helper-preview-row" key={ticket.id}>
                  <Link
                    to={`/tickets/${ticket.id}`}
                    className="nd-helper-v2-ticket"
                    data-iris-reveal="message"
                    data-iris-link=""
                  >
                    <span className="nd-helper-v2-avatar" data-iris-link-icon="" data-preview-avatar="" data-preview-fallback={name.slice(0, 1).toUpperCase()}>
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
                      <strong data-preview-title="">{name}</strong>
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
                  <button type="button" className="iris-preview-trigger" aria-label={`Aperçu du dossier de ${name}`} onClick={event => {
                    event.currentTarget.focus();
                    setPreview({ ticket, source: event.currentTarget.closest(".iris-ticket-row") });
                  }}><PanelRightOpen size={17} aria-hidden="true" /></button>
                  </div>
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
              data-iris-reveal="card"
              data-iris-link=""
            >
              <span className="nd-helper-v2-shortcut-icon" data-iris-link-icon="">
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
      {preview && <TicketPreview ticket={preview.ticket} source={preview.source} helper={helper} isAdmin={isAdmin}
        onClose={() => setPreview(null)} onTicketUpdate={onTicketUpdate} onTicketDeleted={onTicketDeleted} />}
    </section>
  );
}
