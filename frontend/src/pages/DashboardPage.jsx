import { resolveAvatarUrl } from "../utils/avatar";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  HeartHandshake,
  Plus,
  Search,
  Users,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";

import "@/TicketList.css";

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

function timestamp(value) {
  const result = Date.parse(value || "");
  return Number.isNaN(result) ? 0 : result;
}

function formatDate(value) {
  const date = new Date(value);

  if (!value || Number.isNaN(date.getTime())) {
    return "Non renseignée";
  }

  return date.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function MemberAvatar({ member }) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [member?.avatar_url]);

  return (
    <span className="tl-avatar">
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

const STATUS_FILTERS = [
  { value: "all", label: "Tous les statuts" },
  {
    value: "en attente de réponse",
    label: "En attente de réponse",
  },
  { value: "en cours", label: "En cours" },
  { value: "à conclure", label: "À conclure" },
];

function statusClass(status) {
  if (status === "en cours") return "is-progress";
  if (status === "à conclure") return "is-closing";
  return "is-waiting";
}

export default function DashboardPage({
  tickets = [],
  helper,
  loading = false,
  error = "",
  onRetry,
}) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [assignmentFilter, setAssignmentFilter] = useState("all");

  useEffect(() => {
    document.body.classList.add("ticket-list-no-nav");

    return () => {
      document.body.classList.remove("ticket-list-no-nav");
    };
  }, []);

  const activeTickets = useMemo(
    () =>
      tickets
        .filter((ticket) => ticket.status === "active")
        .sort(
          (a, b) =>
            timestamp(b.updated_at) - timestamp(a.updated_at)
        ),
    [tickets]
  );

  const visibleTickets = useMemo(() => {
    const term = normalize(search.trim());

    return activeTickets.filter((ticket) => {
      const followUpStatus =
        ticket.follow_up_status || "en attente de réponse";

      if (
        statusFilter !== "all" &&
        followUpStatus !== statusFilter
      ) {
        return false;
      }

      if (
        assignmentFilter === "unassigned" &&
        ticket.assigned_helper?.id
      ) {
        return false;
      }

      if (
        assignmentFilter === "mine" &&
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
  }, [
    activeTickets,
    search,
    statusFilter,
    assignmentFilter,
    helper?.id,
  ]);

  const hasFilters =
    Boolean(search.trim()) ||
    statusFilter !== "all" ||
    assignmentFilter !== "all";

  const clearFilters = () => {
    setSearch("");
    setStatusFilter("all");
    setAssignmentFilter("all");
  };

  return (
    <section
      className="tl-page"
      data-testid="dashboard-page"
    >
      <header className="tl-header">
        <div>
          <p className="tl-eyebrow">ESPACE HELPER</p>
          <h1>Suivis ouverts</h1>

          <p className="tl-intro">
            Retrouvez les accompagnements en cours et accédez
            aux dossiers pour poursuivre les échanges.
          </p>
        </div>

        <div className="tl-header-actions">
          <Link to="/" className="tl-home">
            Accueil
            <ArrowRight size={18} aria-hidden="true" />
          </Link>

          <Link
            to="/new"
            className="tl-primary-button"
            data-testid="import-discord-channel-button"
          >
            <Plus size={17} aria-hidden="true" />
            Nouveau suivi
          </Link>
        </div>
      </header>

      <section className="tl-panel" aria-labelledby="tl-list-title">
        <header className="tl-panel-header">
          <span className="tl-panel-icon">
            <HeartHandshake size={23} aria-hidden="true" />
          </span>

          <div>
            <h2 id="tl-list-title">Les accompagnements</h2>
            <p>
              Une vue partagée pour retrouver le bon dossier.
            </p>
          </div>

          {!loading && !error && (
            <span className="tl-count" role="status">
              {visibleTickets.length} suivi
              {visibleTickets.length > 1 ? "s" : ""}
            </span>
          )}
        </header>

        <div className="tl-toolbar">
          <div className="tl-search-row">
            <label className="tl-search">
              <Search size={18} aria-hidden="true" />

              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Rechercher un membre, un salon ou un interlocuteur…"
                aria-label="Rechercher un suivi"
              />
            </label>

            <select
              className="tl-status-select"
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.target.value)
              }
              aria-label="Filtrer par statut de suivi"
            >
              {STATUS_FILTERS.map((status) => (
                <option key={status.value} value={status.value}>
                  {status.label}
                </option>
              ))}
            </select>
          </div>

          <div className="tl-filters" aria-label="Filtrer les attributions">
            <button
              type="button"
              className={
                assignmentFilter === "all" ? "is-selected" : ""
              }
              aria-pressed={assignmentFilter === "all"}
              onClick={() => setAssignmentFilter("all")}
            >
              Tous les suivis
            </button>

            {helper?.id && (
              <button
                type="button"
                className={
                  assignmentFilter === "mine" ? "is-selected" : ""
                }
                aria-pressed={assignmentFilter === "mine"}
                onClick={() => setAssignmentFilter("mine")}
              >
                Mes suivis
              </button>
            )}

            <button
              type="button"
              className={
                assignmentFilter === "unassigned"
                  ? "is-selected"
                  : ""
              }
              aria-pressed={assignmentFilter === "unassigned"}
              onClick={() => setAssignmentFilter("unassigned")}
            >
              Sans interlocuteur
            </button>

            {hasFilters && (
              <button
                type="button"
                className="tl-reset"
                onClick={clearFilters}
              >
                <X size={14} aria-hidden="true" />
                Effacer les filtres
              </button>
            )}
          </div>
        </div>

        {loading ? (
          <div className="tl-empty" role="status">
            <p>Chargement des suivis…</p>
          </div>
        ) : error ? (
          <div className="tl-empty tl-error" role="alert">
            <h3>Les suivis n’ont pas pu être chargés.</h3>
            <p>{error}</p>

            {onRetry && (
              <button
                type="button"
                className="tl-empty-button"
                onClick={onRetry}
              >
                Réessayer
              </button>
            )}
          </div>
        ) : visibleTickets.length === 0 ? (
          <div
            className="tl-empty"
            data-testid="dashboard-empty-state"
          >
            <HeartHandshake size={32} aria-hidden="true" />

            <h3>
              {hasFilters
                ? "Aucun suivi ne correspond à cette sélection."
                : "Aucun suivi ouvert pour le moment."}
            </h3>

            <p>
              {hasFilters
                ? "Essayez une autre recherche ou retirez les filtres."
                : "Importez un salon Discord pour démarrer un accompagnement."}
            </p>

            {hasFilters ? (
              <button
                type="button"
                className="tl-empty-button"
                onClick={clearFilters}
              >
                Afficher tous les suivis
              </button>
            ) : (
              <Link to="/new" className="tl-empty-button">
                <Plus size={16} aria-hidden="true" />
                Nouveau suivi
              </Link>
            )}
          </div>
        ) : (
          <div className="tl-list">
            {visibleTickets.map((ticket) => {
              const followUpStatus =
                ticket.follow_up_status || "en attente de réponse";

              return (
                <Link
                  key={ticket.id}
                  to={`/tickets/${ticket.id}`}
                  className="tl-ticket"
                  data-testid={`ticket-row-${ticket.id}`}
                >
                  <MemberAvatar member={ticket.member} />

                  <span className="tl-ticket-copy">
                    <strong>{displayName(ticket.member)}</strong>

                    <small>
                      {ticket.title || ticket.channel_name}
                    </small>

                    <span
                      className={`tl-interlocutor ${
                        !ticket.assigned_helper ? "is-unassigned" : ""
                      }`}
                    >
                      {ticket.assigned_helper
                        ? `Interlocuteur : ${displayName(
                            ticket.assigned_helper
                          )}`
                        : "Aucun interlocuteur attribué"}
                    </span>
                  </span>

                  <span className="tl-ticket-date">
                    <small>Dernière modification</small>
                    <span>{formatDate(ticket.updated_at)}</span>
                  </span>

                  <span
                    className={`tl-status ${statusClass(
                      followUpStatus
                    )}`}
                  >
                    {followUpStatus}
                  </span>

                  <ArrowRight
                    className="tl-ticket-arrow"
                    size={19}
                    aria-hidden="true"
                  />
                </Link>
              );
            })}
          </div>
        )}

        <footer className="tl-panel-footer">
          <span>
            Recherche et filtres sur les tickets déjà chargés.
          </span>

          <Link to="/archives">
            Consulter les archives
            <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </footer>
      </section>
    </section>
  );
}
