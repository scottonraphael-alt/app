import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { Gavel } from "lucide-react";

import "../Agenda.css";
import "../components/meetings-extras/meetings-extras.css";

import AgendaHomeLink from "../components/agenda/AgendaHomeLink";
import useAgendaNoNav from "../components/agenda/useAgendaNoNav";
import { agendaErrorMessage, isForbidden, shouldRetryAgendaQuery } from "../components/agenda/agendaErrors";
import { isIsoDate, formatDayMedium } from "../components/agenda/dateUtils";
import { MeetingsForbidden } from "../components/agenda/meetings/MeetingsStates";
import { extrasKeys, fetchDecisionsRegister } from "../components/meetings-extras/meetingExtrasApi";

const PAGE_SIZE = 50;

function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

// Registre des décisions de toutes les réunions : recherche, date, lien vers la réunion.
export default function DecisionsPage() {
  useAgendaNoNav();
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const query = useInfiniteQuery({
    queryKey: extrasKeys.register(q),
    queryFn: ({ pageParam = 0 }) => fetchDecisionsRegister({ q, limit: PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (last?.has_more ? pages.reduce((sum, p) => sum + p.items.length, 0) : undefined),
    retry: shouldRetryAgendaQuery,
    placeholderData: keepPreviousData,
  });

  const items = (query.data?.pages || []).flatMap((page) => (Array.isArray(page?.items) ? page.items : []));
  const total = query.data?.pages?.[0]?.total ?? items.length;

  const header = (intro) => (
    <header className="ag-header">
      <div>
        <p className="ag-eyebrow">Espace staff</p>
        <h1>Registre des décisions</h1>
        {intro ? <p className="ag-intro">{intro}</p> : null}
      </div>
      <div className="ag-header-actions">
        <AgendaHomeLink />
      </div>
    </header>
  );

  if (isForbidden(query.error)) {
    return (
      <main className="ag-page" data-testid="decisions-page">
        {header()}
        <MeetingsForbidden />
      </main>
    );
  }

  return (
    <main className="ag-page" data-testid="decisions-page">
      {header("Retrouvez ce que l'équipe a décidé, réunion après réunion.")}

      <section className="ag-panel" aria-labelledby="ag-decisions-title">
        <div className="ag-panel-header">
          <span className="ag-panel-icon">
            <Gavel size={20} aria-hidden="true" />
          </span>
          <div className="ag-panel-heading">
            <h2 id="ag-decisions-title">Décisions</h2>
          </div>
          {query.isSuccess ? <span className="ag-count">{total}</span> : null}
        </div>
        <div className="ag-panel-body ag-mx">
          <div className="ag-mx-search">
            <label className="ag-sr-only" htmlFor="ag-decisions-search">
              Rechercher une décision
            </label>
            <input
              id="ag-decisions-search"
              type="search"
              className="ag-input"
              value={search}
              maxLength={100}
              placeholder="Rechercher dans les décisions ou le titre d'une réunion"
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>

          {query.isPending ? (
            <div className="ag-skeleton-stack" aria-busy="true" aria-label="Chargement des décisions">
              <span className="ag-skeleton" style={{ height: 64 }} />
              <span className="ag-skeleton" style={{ height: 64 }} />
              <span className="ag-skeleton" style={{ height: 64 }} />
            </div>
          ) : query.isError ? (
            <div className="ag-error" role="alert">
              <span className="ag-error-text">{agendaErrorMessage(query.error, "Impossible de charger le registre.")}</span>
              <button type="button" className="ag-error-retry" onClick={() => query.refetch()}>
                Réessayer
              </button>
            </div>
          ) : items.length === 0 ? (
            <p className="ag-meeting-empty" role="status">
              {q ? "Aucune décision ne correspond à cette recherche." : "Aucune décision enregistrée pour l'instant."}
            </p>
          ) : (
            <>
              <p className="ag-sr-only" role="status">
                {total} décision{total > 1 ? "s" : ""}
              </p>
              <ul className="ag-mx-list">
                {items.map((item) => (
                  <li key={item.id} className="ag-mx-row ag-mx-decision">
                    <div className="ag-mx-row-main">
                      <p className="ag-mx-decision-text">{item.text}</p>
                      <span className="ag-mx-row-meta">
                        <Link to={item.link || `/staff/meetings/${item.meeting_id}`} className="ag-mx-link">
                          {item.meeting_title || "Réunion"}
                        </Link>
                        {isIsoDate(item.meeting_date) ? ` · ${formatDayMedium(item.meeting_date, { withYear: true })}` : ""}
                        {item.marked_by ? ` · marquée par ${item.marked_by}` : ""}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
              {query.hasNextPage ? (
                <button
                  type="button"
                  className="ag-button ag-button--secondary ag-button--small ag-mx-import"
                  disabled={query.isFetchingNextPage}
                  onClick={() => query.fetchNextPage()}
                >
                  {query.isFetchingNextPage ? "Chargement…" : "Afficher plus"}
                </button>
              ) : null}
            </>
          )}
        </div>
      </section>
    </main>
  );
}
