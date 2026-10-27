import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useInfiniteQuery } from "@tanstack/react-query";
import { CalendarPlus, CircleDot, Gavel, ListChecks, Lock, NotebookPen, Search, SearchX, X } from "lucide-react";

import "./meetings.css";

import { PhaseBadge, typeClass } from "../TypeBadge";
import { agendaQueries, flattenMeetingPages } from "../agendaApi";
import { MEETING_FILTERS, MEETING_PHASES, SEARCH_DEBOUNCE_MS, TEXT_LIMITS } from "../agendaConstants";
import { groupMeetingsByMonth, helperName } from "../calendarModel";
import { dateBlockParts, formatDayLong, formatTime } from "../dateUtils";
import { PanelError, PanelSkeleton } from "./MeetingsStates";

function plural(count, singular, pluralForm) {
  return `${count} ${count > 1 ? pluralForm : singular}`;
}

// Ligne de la liste, entièrement cliquable : bloc date, titre, informations, extrait, phase et compteurs.
export function MeetingRow({ meeting }) {
  const phase = MEETING_PHASES[meeting.phase] ? meeting.phase : null;
  const upcoming = phase === "a_venir";
  const cancelled = phase === "annulee" || Boolean(meeting.cancelled);
  const parts = dateBlockParts(meeting.meeting_date);
  const author = meeting.author ? helperName(meeting.author) : "";
  const info = [formatTime(meeting.start_time), meeting.location, author ? `par ${author}` : ""].filter(Boolean);
  const agendaCount = Number(meeting.agenda_count) || 0;
  const agendaDone = Number(meeting.agenda_done_count) || 0;
  const decisions = Number(meeting.decisions_count) || 0;
  const openActions = Number(meeting.open_actions_count) || 0;
  const preview = Array.isArray(meeting.agenda_preview) ? meeting.agenda_preview.filter(Boolean) : [];
  const excerpt = (meeting.excerpt || "").trim();

  return (
    <li>
      <Link
        to={`/staff/meetings/${encodeURIComponent(meeting.id)}`}
        className={`ag-meet-row${cancelled ? " is-cancelled" : ""}`}
      >
        <span
          className={`ag-date-block ${upcoming ? typeClass("reunion") : "ag-date-block--muted"}`}
          aria-hidden="true"
        >
          <strong>{parts.dayNumber}</strong>
          <small>{parts.weekday}</small>
        </span>
        <span className="ag-meet-row-main">
          <span className={`ag-meet-row-title${cancelled ? " ag-strike" : ""}`}>{meeting.title || "Réunion"}</span>
          <span className="ag-sr-only">, {formatDayLong(meeting.meeting_date)}</span>
          {info.length ? <span className="ag-meet-row-info">{info.join(" · ")}</span> : null}
          {excerpt ? (
            <span className="ag-meet-row-excerpt">{excerpt}</span>
          ) : preview.length ? (
            <span className="ag-meet-row-excerpt ag-meet-row-excerpt--agenda">Ordre du jour : {preview.join(" · ")}</span>
          ) : null}
        </span>
        <span className="ag-meet-row-side">
          {phase ? <PhaseBadge phase={phase} size="sm" /> : null}
          <span className="ag-meet-row-stats">
            {agendaCount > 0 ? (
              <span className="ag-meet-stat" title="Points de l'ordre du jour abordés">
                <ListChecks size={14} aria-hidden="true" />
                {agendaDone}/{agendaCount}
                <span className="ag-sr-only"> points abordés</span>
              </span>
            ) : null}
            {decisions > 0 ? (
              <span className="ag-meet-stat" title="Décisions">
                <Gavel size={14} aria-hidden="true" />
                {decisions}
                <span className="ag-sr-only"> {decisions > 1 ? "décisions" : "décision"}</span>
              </span>
            ) : null}
            {openActions > 0 ? (
              <span className="ag-meet-stat ag-meet-stat--actions">
                <CircleDot size={14} aria-hidden="true" />
                {plural(openActions, "action ouverte", "actions ouvertes")}
              </span>
            ) : null}
            {meeting.is_locked ? (
              <span className="ag-meet-stat" title="Verrouillée">
                <Lock size={14} aria-hidden="true" />
                <span className="ag-sr-only">Verrouillée</span>
              </span>
            ) : null}
          </span>
        </span>
      </Link>
    </li>
  );
}

function RowsSkeleton() {
  return <PanelSkeleton rows={4} height={72} />;
}

// Carte « Toutes les réunions » : recherche (300 ms), filtres par phase, liste groupée par mois, « Afficher plus ».
// `phase` est contrôlée par la page (la carte « À rédiger » peut la changer) ; `panelRef` vise la carte.
export default function MeetingsListPanel({ phase, onPhaseChange, canManage = false, onPlan, panelRef = null }) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    const next = input.trim();
    if (next === query) return undefined;
    const timer = window.setTimeout(() => setQuery(next), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [input, query]);

  const listQuery = useInfiniteQuery(agendaQueries.meetingsPages({ q: query, phase }));
  const { items, total, counts } = useMemo(() => flattenMeetingPages(listQuery.data), [listQuery.data]);
  const groups = useMemo(() => groupMeetingsByMonth(items), [items]);
  const allCount = Number(counts?.all ?? total) || 0;
  const loading = listQuery.isPending;
  const refreshing = listQuery.isFetching && !listQuery.isFetchingNextPage && !loading;

  const clearSearch = () => {
    setInput("");
    setQuery("");
  };

  const submitSearch = (event) => {
    event.preventDefault();
    setQuery(input.trim());
  };

  let body;
  if (loading) {
    body = <RowsSkeleton />;
  } else if (listQuery.isError && !items.length) {
    body = <PanelError message="Impossible de charger les réunions." onRetry={() => listQuery.refetch()} />;
  } else if (!items.length) {
    if (query) {
      body = (
        <div className="ag-empty">
          <span className="ag-empty-icon">
            <SearchX size={28} aria-hidden="true" />
          </span>
          <h3>Aucune réunion ne correspond à « {query} ».</h3>
          <button type="button" className="ag-button ag-button--secondary" onClick={clearSearch}>
            Effacer la recherche
          </button>
        </div>
      );
    } else if (phase) {
      body = (
        <div className="ag-empty">
          <span className="ag-empty-icon">
            <NotebookPen size={28} aria-hidden="true" />
          </span>
          <h3>Aucune réunion dans ce filtre.</h3>
          <button type="button" className="ag-button ag-button--secondary" onClick={() => onPhaseChange("")}>
            Voir toutes les réunions
          </button>
        </div>
      );
    } else {
      body = (
        <div className="ag-empty">
          <span className="ag-empty-icon">
            <NotebookPen size={28} aria-hidden="true" />
          </span>
          <h3>Aucune réunion pour le moment.</h3>
          {canManage ? (
            <button type="button" className="ag-button" onClick={onPlan}>
              <CalendarPlus size={16} aria-hidden="true" />
              Planifier une réunion
            </button>
          ) : null}
        </div>
      );
    }
  } else {
    body = (
      <>
        {listQuery.isError ? (
          <PanelError message="Impossible d'actualiser la liste." onRetry={() => listQuery.refetch()} />
        ) : null}
        {groups.map((group) => (
          <section key={group.key || "sans-date"} className="ag-meet-month" aria-label={group.label}>
            <h3 className="ag-meet-month-title">{group.label}</h3>
            <ul className="ag-meet-rows">
              {group.items.map((meeting) => (
                <MeetingRow key={meeting.id} meeting={meeting} />
              ))}
            </ul>
          </section>
        ))}
        {listQuery.hasNextPage ? (
          <div className="ag-meet-more">
            <button
              type="button"
              className="ag-button ag-button--secondary"
              onClick={() => listQuery.fetchNextPage()}
              disabled={listQuery.isFetchingNextPage}
            >
              {listQuery.isFetchingNextPage ? "Chargement…" : "Afficher plus"}
            </button>
            <span className="ag-meet-more-count">
              {items.length} sur {total}
            </span>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <section
      ref={panelRef}
      tabIndex={-1}
      className="ag-panel ag-meet-list"
      aria-labelledby="ag-meet-list-title"
      aria-busy={loading || refreshing ? "true" : undefined}
    >
      <div className="ag-panel-header ag-panel-header--meetings">
        <span className="ag-panel-icon">
          <NotebookPen size={20} aria-hidden="true" />
        </span>
        <div className="ag-panel-heading">
          <p className="ag-eyebrow">Archives</p>
          <h2 id="ag-meet-list-title">Toutes les réunions</h2>
        </div>
        {!loading ? <span className="ag-count">{plural(allCount, "réunion", "réunions")}</span> : null}
      </div>

      <div className="ag-toolbar ag-meet-toolbar">
        <form className="ag-search ag-meet-search" role="search" onSubmit={submitSearch}>
          <Search size={17} aria-hidden="true" />
          <input
            type="search"
            value={input}
            maxLength={TEXT_LIMITS.search}
            placeholder="Rechercher un titre, un point, une décision…"
            aria-label="Rechercher une réunion"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && input) {
                event.preventDefault();
                clearSearch();
              }
            }}
          />
          {input ? (
            <button type="button" className="ag-meet-search-clear" aria-label="Effacer la recherche" onClick={clearSearch}>
              <X size={15} aria-hidden="true" />
            </button>
          ) : null}
        </form>
        <div className="ag-filters" role="group" aria-label="Filtrer par phase">
          {MEETING_FILTERS.map((filter) => {
            const count = counts ? Number(counts[filter.countKey]) || 0 : null;
            return (
              <button
                key={filter.key || "toutes"}
                type="button"
                className="ag-chip"
                aria-pressed={phase === filter.key ? "true" : "false"}
                onClick={() => onPhaseChange(filter.key)}
              >
                {filter.label}
                {count !== null ? <span className="ag-chip-count">{count}</span> : null}
              </button>
            );
          })}
        </div>
      </div>

      <div className={`ag-meet-list-body${refreshing ? " is-refreshing" : ""}`}>{body}</div>
      <p className="ag-sr-only" aria-live="polite">
        {loading ? "" : query ? `${plural(total, "réunion trouvée", "réunions trouvées")}` : ""}
      </p>
    </section>
  );
}

export { MeetingsListPanel };
