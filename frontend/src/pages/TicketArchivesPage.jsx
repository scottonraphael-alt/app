import { ticketEvent } from "../utils/ticketEvents";
import { resolveAvatarUrl } from "../utils/avatar";
import { useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArrowRight,
  Search,
  Users,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";

import "../TicketArchives.css";

function displayName(member) {
  return (
    member?.display_name ||
    member?.global_name ||
    member?.username ||
    "Membre"
  );
}

function normalize(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function formatDate(value) {
  if (!value) return "Non renseignée";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Non renseignée";
  }

  return date.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function timestamp(value) {
  const result = Date.parse(value || "");
  return Number.isNaN(result) ? 0 : result;
}

function MemberAvatar({ member }) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [member?.avatar_url]);

  return (
    <span className="tar-avatar">
      {member?.avatar_url && !failed ? (
        <img
          src={resolveAvatarUrl(member.avatar_url)}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <Users size={20} aria-hidden="true" />
      )}
    </span>
  );
}

export default function TicketArchivesPage({
  tickets = [],
  helper,
}) {
  const [search, setSearch] = useState("");
  const [onlyMine, setOnlyMine] = useState(false);

  useEffect(() => {
    document.body.classList.add("ticket-archives-no-nav");
    ticketEvent("archives.viewed");

    return () => {
      document.body.classList.remove("ticket-archives-no-nav");
    };
  }, []);

  const archivedTickets = useMemo(
    () =>
      tickets
        .filter((ticket) => ticket.status === "archived")
        .sort(
          (a, b) =>
            timestamp(b.updated_at) - timestamp(a.updated_at)
        ),
    [tickets]
  );

  const visibleTickets = useMemo(() => {
    const term = normalize(search.trim());

    return archivedTickets.filter((ticket) => {
      if (
        onlyMine &&
        (!helper?.id ||
          String(ticket.assigned_helper?.id) !== String(helper.id))
      ) {
        return false;
      }

      if (!term) return true;

      const text = normalize(
        [
          ticket.title,
          ticket.channel_name,
          ticket.id,
          ticket.member?.id,
          displayName(ticket.member),
          ticket.assigned_helper
            ? displayName(ticket.assigned_helper)
            : "",
        ].join(" ")
      );

      return text.includes(term);
    });
  }, [archivedTickets, search, onlyMine, helper?.id]);

  const hasFilters = Boolean(search.trim() || onlyMine);

  const clearFilters = () => {
    ticketEvent("archives.filter_changed", null, "reset");
    setSearch("");
    setOnlyMine(false);
  };

  return (
    <section
      className="tar-page"
      data-testid="ticket-archives-page"
    >
      <header className="tar-header">
        <div>
          <p className="tar-eyebrow">ESPACE HELPER</p>
          <h1>Archives des suivis</h1>
          <p className="tar-intro">
            Retrouvez les accompagnements archivés et consultez
            leurs échanges, notes et repères.
          </p>
        </div>

        <Link to="/" className="tar-home">
          Accueil
          <ArrowRight size={18} aria-hidden="true" />
        </Link>
      </header>

      <section
        className="tar-panel"
        aria-labelledby="tar-list-title"
      >
        <header className="tar-panel-header">
          <span className="tar-panel-icon">
            <Archive size={23} aria-hidden="true" />
          </span>

          <div>
            <h2 id="tar-list-title">Les dossiers archivés</h2>
            <p>
              Un historique accessible lorsque vous en avez besoin.
            </p>
          </div>

          <span className="tar-count">
            {visibleTickets.length}
            {" dossier"}
            {visibleTickets.length > 1 ? "s" : ""}
          </span>
        </header>

        <div className="tar-toolbar">
          <label className="tar-search">
            <Search size={18} aria-hidden="true" />

            <input
              type="search"
              value={search}
              onBlur={() => { if (search.trim()) ticketEvent("archives.search_submitted", null, search.trim().length); }}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Rechercher un membre, un salon ou un interlocuteur…"
              aria-label="Rechercher dans les suivis archivés"
            />
          </label>

          <div className="tar-filters">
            <button
              type="button"
              className={!onlyMine ? "is-selected" : ""}
              aria-pressed={!onlyMine}
              onClick={() => { setOnlyMine(false); ticketEvent("archives.filter_changed", null, "all"); }}
            >
              Toutes les archives
            </button>

            {helper?.id && (
              <button
                type="button"
                className={onlyMine ? "is-selected" : ""}
                aria-pressed={onlyMine}
                onClick={() => { setOnlyMine(true); ticketEvent("archives.filter_changed", null, "mine"); }}
              >
                Mes anciens suivis
              </button>
            )}

            {hasFilters && (
              <button
                type="button"
                className="tar-reset"
                onClick={clearFilters}
              >
                <X size={14} aria-hidden="true" />
                Effacer les filtres
              </button>
            )}
          </div>
        </div>

        {visibleTickets.length === 0 ? (
          <div className="tar-empty">
            <Archive size={32} aria-hidden="true" />

            <h3>
              {hasFilters
                ? "Aucun dossier ne correspond à votre recherche."
                : "Aucun suivi archivé pour le moment."}
            </h3>

            <p>
              {hasFilters
                ? "Essayez un autre nom ou retirez les filtres."
                : "Les dossiers archivés apparaîtront ici."}
            </p>

            {hasFilters && (
              <button
                type="button"
                className="tar-empty-button"
                onClick={clearFilters}
              >
                Afficher toutes les archives
              </button>
            )}
          </div>
        ) : (
          <div className="tar-list">
            {visibleTickets.map((ticket) => (
              <Link
                key={ticket.id}
                to={`/tickets/${ticket.id}`}
                className="tar-ticket"
              >
                <MemberAvatar member={ticket.member} />

                <span className="tar-ticket-copy">
                  <strong>{displayName(ticket.member)}</strong>
                  <small>{ticket.title || ticket.channel_name}</small>

                  <span className="tar-ticket-helper">
                    Interlocuteur :{" "}
                    {ticket.assigned_helper
                      ? displayName(ticket.assigned_helper)
                      : "Non attribué"}
                  </span>
                </span>

                <span className="tar-ticket-date">
                  <small>Dernière modification</small>
                  <span>{formatDate(ticket.updated_at)}</span>
                </span>

                <span className="tar-status">Archivé</span>

                <ArrowRight
                  className="tar-ticket-arrow"
                  size={19}
                  aria-hidden="true"
                />
              </Link>
            ))}
          </div>
        )}

        <footer className="tar-panel-footer">
          La recherche porte sur les tickets déjà chargés dans Iris.
        </footer>
      </section>
    </section>
  );
}
