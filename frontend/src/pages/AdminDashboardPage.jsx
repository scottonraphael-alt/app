import { ticketEvent } from "../utils/ticketEvents";
import { resolveAvatarUrl } from "../utils/avatar";
import { useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  HeartHandshake,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  UserRound,
  UsersRound,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";
import TicketReminderTestPanel from "../components/TicketReminderTestPanel";
import "../TicketAssignments.css";

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

function Avatar({ member, className = "" }) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [member?.avatar_url]);

  return (
    <span className={`ta-avatar ${className}`}>
      {member?.avatar_url && !failed ? (
        <img
          src={resolveAvatarUrl(member.avatar_url)}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <UserRound size={20} aria-hidden="true" />
      )}
    </span>
  );
}

export default function AdminDashboardPage() {
  const queryClient = useQueryClient();

  const [filter, setFilter] = useState("unassigned");
  const [search, setSearch] = useState("");
  const [helperSearch, setHelperSearch] = useState("");

  const [selectedTicketId, setSelectedTicketId] = useState(null);
  const [selectedHelperId, setSelectedHelperId] = useState("");
  const [selectionChanged, setSelectionChanged] = useState(false);

  useEffect(() => {
    document.body.classList.add("assignments-no-nav");
    ticketEvent("coordination.viewed");

    return () => {
      document.body.classList.remove("assignments-no-nav");
    };
  }, []);

  const panelQuery = useQuery({
    queryKey: ["admin", "assignment-panel"],
    queryFn: async ({ signal }) => {
      // Vérifie d'abord les droits coordinateur.
      const overviewResponse = await api.get("/admin/overview", {
        signal,
      });

      const ticketsResponse = await api.get("/tickets", {
        signal,
      });

      if (
        !Array.isArray(overviewResponse.data?.helpers) ||
        !Array.isArray(ticketsResponse.data)
      ) {
        throw new Error("Format de réponse inattendu.");
      }

      return {
        overview: overviewResponse.data,
        tickets: ticketsResponse.data.filter(
          (ticket) => ticket.status === "active"
        ),
      };
    },
    staleTime: 20_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const tickets = panelQuery.data?.tickets || [];
  const helperEntries = panelQuery.data?.overview?.helpers || [];

  const unassignedCount = tickets.filter(
    (ticket) => !ticket.assigned_helper?.id
  ).length;

  const assignedCount = tickets.length - unassignedCount;

  const visibleTickets = tickets.filter((ticket) => {
    const assigned = Boolean(ticket.assigned_helper?.id);

    if (filter === "unassigned" && assigned) return false;
    if (filter === "assigned" && !assigned) return false;

    const text = normalize(
      [
        ticket.title,
        displayName(ticket.member),
        ticket.channel_name,
        ticket.member?.id,
        ticket.assigned_helper
          ? displayName(ticket.assigned_helper)
          : "",
      ].join(" ")
    );

    return text.includes(normalize(search.trim()));
  });

  const selectedTicket = tickets.find(
    (ticket) => ticket.id === selectedTicketId
  );

  const currentHelperId = selectedTicket?.assigned_helper?.id
    ? String(selectedTicket.assigned_helper.id)
    : "";

  const effectiveHelperId = selectionChanged
    ? selectedHelperId
    : currentHelperId;

  const selectedHelperEntry = helperEntries.find(
    (entry) => String(entry.helper.id) === effectiveHelperId
  );

  const helperOptions = helperEntries
    .map((entry) => ({
      ...entry,
      openCount: tickets.filter(
        (ticket) =>
          String(ticket.assigned_helper?.id) ===
          String(entry.helper.id)
      ).length,
    }))
    .filter((entry) =>
      normalize(displayName(entry.helper)).includes(
        normalize(helperSearch.trim())
      )
    )
    .sort(
      (a, b) =>
        a.openCount - b.openCount ||
        displayName(a.helper).localeCompare(
          displayName(b.helper),
          "fr"
        )
    );

  const assignmentMutation = useMutation({
    mutationFn: async ({ ticketId, helperId }) => {
      const response = await api.patch(
        `/admin/tickets/${ticketId}/assignment`,
        {
          helper_id: helperId || null,
        }
      );

      return response.data;
    },

    onSuccess: (updatedTicket) => {
      queryClient.setQueryData(
        ["admin", "assignment-panel"],
        (current) => {
          if (!current) return current;

          return {
            ...current,
            tickets: current.tickets.map((ticket) =>
              ticket.id === updatedTicket.id
                ? updatedTicket
                : ticket
            ),
          };
        }
      );

      // Garde aussi la liste du dashboard cohérente.
      queryClient.setQueryData(["tickets"], (current) =>
        Array.isArray(current)
          ? current.map((ticket) =>
              ticket.id === updatedTicket.id
                ? updatedTicket
                : ticket
            )
          : current
      );

      setSelectionChanged(false);

      toast.success(
        updatedTicket.assigned_helper
          ? "Attribution enregistrée."
          : "Attribution retirée."
      );

      queryClient.invalidateQueries({
        queryKey: ["admin", "assignment-panel"],
        exact: true,
      });

      queryClient.invalidateQueries({
        queryKey: ["tickets"],
        exact: true,
      });
    },

    onError: (error) => {
      toast.error(getErrorMessage(error));
    },
  });

  const busy = assignmentMutation.isPending;

  const selectTicket = (ticket) => {
    if (busy) return;

    ticketEvent("coordination.ticket_selected", ticket.id);
    setSelectedTicketId(ticket.id);
    setSelectedHelperId("");
    setSelectionChanged(false);
    setHelperSearch("");
    assignmentMutation.reset();
  };

  const selectHelper = (helperId) => {
    if (busy) return;

    ticketEvent("coordination.helper_selected", selectedTicketId, helperId || "unassigned");
    setSelectedHelperId(helperId);
    setSelectionChanged(true);
    assignmentMutation.reset();
  };

  const hasAssignmentChange =
    Boolean(selectedTicket) &&
    effectiveHelperId !== currentHelperId;

  const canSave =
    hasAssignmentChange &&
    !busy &&
    !panelQuery.isFetching &&
    !panelQuery.isError;

  const filters = [
    {
      id: "unassigned",
      label: "À attribuer",
      count: unassignedCount,
    },
    {
      id: "assigned",
      label: "Attribués",
      count: assignedCount,
    },
    {
      id: "all",
      label: "Tous",
      count: tickets.length,
    },
  ];

  return (
    <section
      className="ta-page"
      data-testid="admin-dashboard-page"
    >
      <header className="ta-header">
        <div>
          <p className="ta-eyebrow">ESPACE COORDINATION</p>
          <h1>Attribution des suivis</h1>
          <p className="ta-intro">
            Répartissez les tickets ouverts en tenant compte
            de la charge et des limites de chaque helper.
          </p>
        </div>

        <Link to="/" className="ta-home-button">
          Accueil
          <ArrowRight size={18} aria-hidden="true" />
        </Link>
      </header>

      {panelQuery.isPending ? (
        <div className="ta-state" role="status">
          <LoaderCircle
            className="ta-spin"
            size={24}
            aria-hidden="true"
          />
          Chargement du panel…
        </div>
      ) : panelQuery.isError && !panelQuery.data ? (
        <section className="ta-error" role="alert">
          <ShieldCheck size={24} aria-hidden="true" />
          <h2>Le panel n’a pas pu être chargé.</h2>
          <p>{getErrorMessage(panelQuery.error)}</p>
          <p>
            Si votre rôle Coordinateur vient d’être ajouté,
            reconnectez-vous avant de réessayer.
          </p>
          <button
            type="button"
            className="ta-secondary-button"
            onClick={() => panelQuery.refetch()}
          >
            <RefreshCw size={16} aria-hidden="true" />
            Réessayer
          </button>
        </section>
      ) : (
        <>
          <TicketReminderTestPanel />
          <div className="ta-summary">
            <div className="ta-summary-item ta-summary-item--orange">
              <span>À attribuer</span>
              <strong>{unassignedCount}</strong>
            </div>

            <div className="ta-summary-item">
              <span>Tickets ouverts chargés</span>
              <strong>{tickets.length}</strong>
            </div>

            <div className="ta-summary-item">
              <span>Helpers disponibles à l’attribution</span>
              <strong>{helperEntries.length}</strong>
            </div>
          </div>

          {panelQuery.isError && (
            <p className="ta-refresh-error" role="alert">
              L’actualisation a échoué. Les dernières données
              chargées restent affichées. Réessayez avant de
              modifier une attribution.
            </p>
          )}

          <div className="ta-layout">
            <section
              className="ta-ticket-panel"
              aria-labelledby="ta-tickets-title"
            >
              <header className="ta-panel-heading">
                <div>
                  <h2 id="ta-tickets-title">Tickets ouverts</h2>
                  <p>Sélectionnez un dossier à attribuer.</p>
                </div>

                <button
                  type="button"
                  className="ta-refresh-button"
                  onClick={() => panelQuery.refetch()}
                  disabled={panelQuery.isFetching || busy}
                  aria-label="Actualiser les tickets et les helpers"
                  title="Actualiser"
                >
                  <RefreshCw
                    className={
                      panelQuery.isFetching ? "ta-spin" : ""
                    }
                    size={17}
                    aria-hidden="true"
                  />
                </button>
              </header>

              <div className="ta-ticket-toolbar">
                <label className="ta-search">
                  <Search size={17} aria-hidden="true" />
                  <input
                    value={search}
                    onBlur={() => { if (search.trim()) ticketEvent("coordination.search_submitted", null, `tickets:${search.trim().length}`); }}
                    onChange={(event) =>
                      setSearch(event.target.value)
                    }
                    placeholder="Rechercher un membre ou un salon…"
                    aria-label="Rechercher un ticket"
                  />
                </label>

                <div
                  className="ta-filters"
                  aria-label="Filtrer les tickets"
                >
                  {filters.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={
                        filter === item.id ? "is-selected" : ""
                      }
                      aria-pressed={filter === item.id}
                      onClick={() => { setFilter(item.id); ticketEvent("coordination.filter_changed", null, item.id); }}
                    >
                      {item.label}
                      <span>{item.count}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="ta-ticket-list">
                {visibleTickets.length === 0 ? (
                  <div className="ta-empty">
                    <HeartHandshake
                      size={29}
                      aria-hidden="true"
                    />
                    <h3>
                      {tickets.length === 0
                        ? "Aucun ticket ouvert."
                        : "Aucun ticket dans cette sélection."}
                    </h3>
                    <p>
                      Essayez un autre filtre ou une autre recherche.
                    </p>
                  </div>
                ) : (
                  visibleTickets.map((ticket) => {
                    const assigned =
                      Boolean(ticket.assigned_helper?.id);

                    return (
                      <button
                        key={ticket.id}
                        type="button"
                        className={`ta-ticket ${
                          selectedTicketId === ticket.id
                            ? "is-selected"
                            : ""
                        }`}
                        onClick={() => selectTicket(ticket)}
                        disabled={busy}
                        aria-pressed={
                          selectedTicketId === ticket.id
                        }
                      >
                        <Avatar member={ticket.member} />

                        <span className="ta-ticket-copy">
                          <strong>
                            {displayName(ticket.member)}
                          </strong>
                          <small>
                            {ticket.title || ticket.channel_name}
                          </small>
                          <span className="ta-ticket-assignee">
                            {assigned
                              ? `Interlocuteur : ${displayName(
                                  ticket.assigned_helper
                                )}`
                              : "Aucun interlocuteur attribué"}
                          </span>
                        </span>

                        <span
                          className={`ta-ticket-badge ${
                            assigned ? "" : "is-unassigned"
                          }`}
                        >
                          {assigned ? "Attribué" : "À attribuer"}
                        </span>
                      </button>
                    );
                  })
                )}
              </div>

              <p className="ta-list-note">
                Les compteurs portent sur les tickets chargés.
                L’API actuelle renvoie au maximum les 250 derniers
                tickets, ouverts et archivés confondus.
              </p>
            </section>

            <aside
              className="ta-assignment-panel"
              aria-labelledby="ta-assignment-title"
            >
              {!selectedTicket ? (
                <div className="ta-assignment-placeholder">
                  <span className="ta-placeholder-icon">
                    <UsersRound size={29} aria-hidden="true" />
                  </span>
                  <h2 id="ta-assignment-title">
                    Choisir le bon interlocuteur
                  </h2>
                  <p>
                    Sélectionnez un ticket à gauche pour consulter
                    les helpers et préparer son attribution.
                  </p>
                </div>
              ) : (
                <>
                  <header className="ta-assignment-heading">
                    <p className="ta-eyebrow">DOSSIER SÉLECTIONNÉ</p>

                    <div className="ta-selected-member">
                      <Avatar member={selectedTicket.member} />
                      <div>
                        <h2 id="ta-assignment-title">
                          {displayName(selectedTicket.member)}
                        </h2>
                        <p>{selectedTicket.title}</p>
                      </div>
                    </div>

                    <Link
                      to={`/tickets/${selectedTicket.id}`}
                      className="ta-open-ticket"
                    >
                      Consulter le dossier avant attribution
                      <ArrowRight size={16} aria-hidden="true" />
                    </Link>
                  </header>

                  <div className="ta-helper-picker">
                    <div className="ta-picker-heading">
                      <h3>Choisir un helper</h3>
                      <p>
                        Triés par nombre de tickets ouverts chargés,
                        du moins au plus sollicité.
                      </p>
                    </div>

                    <label className="ta-search">
                      <Search size={16} aria-hidden="true" />
                      <input
                        value={helperSearch}
                        onBlur={() => { if (helperSearch.trim()) ticketEvent("coordination.search_submitted", null, `helpers:${helperSearch.trim().length}`); }}
                        onChange={(event) =>
                          setHelperSearch(event.target.value)
                        }
                        placeholder="Rechercher un helper…"
                        aria-label="Rechercher un helper"
                      />
                    </label>

                    <div className="ta-helper-list">
                      <button
                        type="button"
                        className={`ta-helper-option ${
                          effectiveHelperId === ""
                            ? "is-selected"
                            : ""
                        }`}
                        onClick={() => selectHelper("")}
                        disabled={busy}
                        aria-pressed={effectiveHelperId === ""}
                      >
                        <span className="ta-no-helper">
                          <UsersRound size={19} aria-hidden="true" />
                        </span>
                        <span className="ta-helper-copy">
                          <strong>Sans interlocuteur</strong>
                          <small>
                            Laisser ou remettre le ticket à attribuer
                          </small>
                        </span>
                        {effectiveHelperId === "" && (
                          <Check size={17} aria-hidden="true" />
                        )}
                      </button>

                      {helperOptions.map((entry) => {
                        const id = String(entry.helper.id);
                        const selected =
                          effectiveHelperId === id;

                        return (
                          <button
                            key={id}
                            type="button"
                            className={`ta-helper-option ${
                              selected ? "is-selected" : ""
                            }`}
                            onClick={() => selectHelper(id)}
                            disabled={busy}
                            aria-pressed={selected}
                          >
                            <Avatar member={entry.helper} />

                            <span className="ta-helper-copy">
                              <strong>
                                {displayName(entry.helper)}
                              </strong>
                              <small>
                                {entry.openCount} suivi
                                {entry.openCount > 1 ? "s" : ""} ouvert
                                {entry.openCount > 1 ? "s" : ""}
                              </small>
                            </span>

                            {selected && (
                              <Check size={17} aria-hidden="true" />
                            )}
                          </button>
                        );
                      })}

                      {helperOptions.length === 0 && (
                        <p className="ta-helper-empty">
                          Aucun helper ne correspond à la recherche.
                        </p>
                      )}
                    </div>

                    {selectedHelperEntry && (
                      <details
                        className="ta-vigilance"
                        key={effectiveHelperId}
                      >
                        <summary>
                          <ShieldCheck
                            size={16}
                            aria-hidden="true"
                          />
                          Points de vigilance du helper
                        </summary>
                        <p>
                          {selectedHelperEntry.triggers ||
                            "Aucun point de vigilance renseigné."}
                        </p>
                      </details>
                    )}
                  </div>

                  <footer className="ta-assignment-footer">
                    <p>
                      {hasAssignmentChange
                        ? effectiveHelperId
                          ? `Nouvel interlocuteur : ${
                              selectedHelperEntry
                                ? displayName(
                                    selectedHelperEntry.helper
                                  )
                                : "helper sélectionné"
                            }`
                          : "L’attribution sera retirée."
                        : "Sélectionnez un autre interlocuteur pour modifier l’attribution."}
                    </p>

                    <button
                      type="button"
                      className="ta-save-button"
                      disabled={!canSave}
                      onClick={() =>
                        assignmentMutation.mutate({
                          ticketId: selectedTicket.id,
                          helperId: effectiveHelperId,
                        })
                      }
                    >
                      {busy ? (
                        <LoaderCircle
                          className="ta-spin"
                          size={17}
                          aria-hidden="true"
                        />
                      ) : (
                        <Check size={17} aria-hidden="true" />
                      )}

                      {busy
                        ? "Enregistrement…"
                        : effectiveHelperId
                          ? "Enregistrer l’attribution"
                          : "Retirer l’attribution"}
                    </button>
                  </footer>
                </>
              )}
            </aside>
          </div>
        </>
      )}
    </section>
  );
}
