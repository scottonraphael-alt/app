import "./casier-list.css";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Clock, RotateCw, SearchX, ShieldCheck, TriangleAlert } from "lucide-react";

import Highlight from "./Highlight";
import MemberAvatar from "./MemberAvatar";
import StatusPill from "./StatusPill";
import { CASIER_LIST_PAGE_SIZE, LIST_MATCHES_SHOWN } from "./casierConstants";
import {
  formatDate,
  formatRelative,
  formatUntil,
  matchLabel,
  memberHandle,
  memberName,
  plural,
} from "./formatters";

const SKELETON_ROWS = [0, 1, 2, 3];
const SCROLL_MARGIN = 8;

function isFuture(value) {
  const time = Date.parse(value || "");
  return Number.isFinite(time) && time > Date.now();
}

function matchKey(match, index) {
  return [match?.kind, match?.field, match?.sanction_id, match?.note_id, match?.fiche_id, index].join(":");
}

// Ramène la ligne dans la zone visible du conteneur qui défile (jamais scrollIntoView : la fenêtre bougerait).
function revealRow(row) {
  const scroller = row.closest(".cz-panel-scroll");
  if (!scroller || scroller.scrollHeight <= scroller.clientHeight) return;
  const overflow = window.getComputedStyle(scroller).overflowY;
  if (overflow !== "auto" && overflow !== "scroll") return;

  const box = scroller.getBoundingClientRect();
  const rect = row.getBoundingClientRect();
  if (rect.top < box.top + SCROLL_MARGIN) {
    scroller.scrollTop -= box.top + SCROLL_MARGIN - rect.top;
  } else if (rect.bottom > box.bottom - SCROLL_MARGIN) {
    scroller.scrollTop += rect.bottom - (box.bottom - SCROLL_MARGIN);
  }
}

function CasierMatches({ casier }) {
  const matches = Array.isArray(casier.matches) ? casier.matches : [];
  if (matches.length === 0) return null;

  const shown = matches.slice(0, LIST_MATCHES_SHOWN);
  const total = Math.max(Number(casier.matches_total) || 0, matches.length);
  const extra = total - shown.length;

  return (
    <span className="cz-list-matches">
      {shown.map((match, index) => (
        <span key={matchKey(match, index)} className="cz-list-match">
          <span className="cz-list-match-label">{matchLabel(match)} :</span>{" "}
          <Highlight segments={match.segments} fallback={match.snippet || ""} />
        </span>
      ))}
      {extra > 0 && (
        <span className="cz-list-match-more">
          +{plural(extra, "autre correspondance", "autres correspondances")}
        </span>
      )}
    </span>
  );
}

function CasierRow({ casier, selected, showMatches, onSelect }) {
  const member = casier.member;
  const name = memberName(member);
  // Pseudo masqué quand il répète le nom affiché.
  const handle = member?.username && member.username !== name ? memberHandle(member) : "";
  const activity = casier.last_activity_at || casier.last_sanction_at || casier.created_at;
  const openFlags = Number(casier.ai_flags_open) || 0;
  const muteUntil = isFuture(casier.active_mute_until) ? casier.active_mute_until : null;

  return (
    <button
      type="button"
      className="cz-list-row"
      data-casier-id={casier.id}
      aria-current={selected ? "true" : undefined}
      onClick={() => onSelect?.(casier.id)}
    >
      <MemberAvatar member={member} size={40} />

      <span className="cz-list-main">
        <span className="cz-list-top">
          <span className="cz-list-ident">
            <span className="cz-list-name">{name}</span>
            {handle && <span className="cz-list-handle">{handle}</span>}
          </span>
          {activity && (
            <time className="cz-list-date" dateTime={activity} title={formatDate(activity)}>
              {formatRelative(activity)}
            </time>
          )}
        </span>

        <span className="cz-list-tags">
          <StatusPill status={casier.status} size="sm" />

          {casier.has_active_fiche_s && (
            <span className="cz-list-flag cz-list-flag--fiche" title="Fiche S active">
              <span aria-hidden="true">S</span>
              <span className="cz-sr-only">Fiche S active</span>
            </span>
          )}

          {casier.is_prevention && <span className="cz-list-flag cz-list-flag--prevention">Prévention</span>}

          {openFlags > 0 && (
            <span
              className="cz-list-flag cz-list-flag--ia"
              title={plural(openFlags, "signalement IA à traiter", "signalements IA à traiter")}
            >
              IA {openFlags}
              <span className="cz-sr-only"> à traiter</span>
            </span>
          )}

          {muteUntil && (
            <span className="cz-list-flag cz-list-flag--mute" title={formatDate(muteUntil)}>
              <Clock size={12} aria-hidden="true" />
              Mute {formatUntil(muteUntil)}
            </span>
          )}
        </span>

        {showMatches && <CasierMatches casier={casier} />}
      </span>
    </button>
  );
}

export default function CasierList({
  casiers = [],
  isLoading = false,
  isUpdating = false,
  error = null,
  onRetry,
  selectedId = null,
  onSelect,
  searchQuery = "",
  isFiltered = false,
  resultsKey = "",
  onClearFilters,
  onCreate,
  selectable = false,
  checkedIds = null,
  onToggleChecked,
}) {
  const items = Array.isArray(casiers) ? casiers : [];
  const listRef = useRef(null);
  const revealedRef = useRef(null);
  const focusIndexRef = useRef(null);

  // « Afficher plus » repart de 150 dès que les filtres envoyés changent (pas sur un simple rafraîchissement).
  const [paging, setPaging] = useState({ key: resultsKey, limit: CASIER_LIST_PAGE_SIZE });
  const baseLimit = paging.key === resultsKey ? paging.limit : CASIER_LIST_PAGE_SIZE;
  const selectedIndex = selectedId ? items.findIndex((item) => item?.id === selectedId) : -1;
  const limit =
    selectedIndex >= baseLimit
      ? Math.ceil((selectedIndex + 1) / CASIER_LIST_PAGE_SIZE) * CASIER_LIST_PAGE_SIZE
      : baseLimit;
  const visible = items.slice(0, limit);
  const remaining = items.length - visible.length;

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;

    if (focusIndexRef.current !== null) {
      const rows = list.querySelectorAll(".cz-list-row");
      const target = rows[Math.min(focusIndexRef.current, rows.length - 1)];
      focusIndexRef.current = null;
      target?.focus();
    }

    if (!selectedId || revealedRef.current === selectedId) return;
    const row = Array.from(list.querySelectorAll(".cz-list-row")).find(
      (element) => element.dataset.casierId === selectedId
    );
    if (!row) return;
    revealedRef.current = selectedId;
    revealRow(row);
  });

  const showMore = () => {
    focusIndexRef.current = visible.length;
    setPaging({ key: resultsKey, limit: limit + CASIER_LIST_PAGE_SIZE });
  };

  if (isLoading && items.length === 0) {
    return (
      <div className="cz-skeleton-list" aria-busy="true">
        <span className="cz-sr-only" role="status">
          Chargement des casiers…
        </span>
        {SKELETON_ROWS.map((row) => (
          <div key={row} className="cz-skeleton-row" aria-hidden="true">
            <span className="cz-skeleton cz-skeleton--circle" />
            <div className="cz-skeleton-stack">
              <span className="cz-skeleton cz-skeleton--title" />
              <span className="cz-skeleton cz-skeleton--short" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error && items.length === 0) {
    return (
      <div className="cz-empty cz-empty--error" role="alert">
        <TriangleAlert size={26} aria-hidden="true" />
        <h3>Impossible de charger les casiers.</h3>
        <p>{error}</p>
        <div className="cz-empty-actions">
          <button type="button" className="cz-button" onClick={() => onRetry?.()}>
            <RotateCw size={16} aria-hidden="true" />
            Réessayer
          </button>
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    if (!isFiltered) {
      return (
        <div className="cz-empty">
          <ShieldCheck size={26} aria-hidden="true" />
          <h3>Aucun casier pour l'instant.</h3>
          <p>Les casiers se créent automatiquement quand OasisBot publie une sanction, ou à la main.</p>
          <div className="cz-empty-actions">
            <button type="button" className="cz-button" onClick={() => onCreate?.()}>
              <ShieldCheck size={16} aria-hidden="true" />
              Créer un casier
            </button>
          </div>
        </div>
      );
    }

    return (
      <div className="cz-empty" aria-busy={isUpdating || undefined}>
        <SearchX size={26} aria-hidden="true" />
        <h3>
          {searchQuery ? `Aucun casier ne correspond à « ${searchQuery} ».` : "Aucun casier pour ces filtres."}
        </h3>
        <p>
          {searchQuery
            ? "Vérifiez l'orthographe, élargissez la portée à « Tout » ou retirez des filtres."
            : "Retirez un filtre pour voir plus de casiers."}
        </p>
        <div className="cz-empty-actions">
          <button type="button" className="cz-button" onClick={() => onClearFilters?.()}>
            {searchQuery ? "Effacer la recherche" : "Réinitialiser les filtres"}
          </button>
        </div>
      </div>
    );
  }

  const showMatches = Boolean(searchQuery);

  return (
    <div className={`cz-list-wrap${isUpdating ? " is-updating" : ""}`}>
      <ul ref={listRef} className="cz-list" aria-label="Casiers" aria-busy={isUpdating || undefined}>
        {visible.map((casier) => (
          <li key={casier.id} className={`cz-list-item${selectable ? " has-check" : ""}`}>
            {selectable && (
              <label className="cz-list-check">
                <input
                  type="checkbox"
                  checked={Boolean(checkedIds?.has(casier.id))}
                  onChange={() => onToggleChecked?.(casier.id)}
                />
                <span className="cz-sr-only">Sélectionner {memberName(casier.member)}</span>
              </label>
            )}
            <CasierRow
              casier={casier}
              selected={casier.id === selectedId}
              showMatches={showMatches}
              onSelect={onSelect}
            />
          </li>
        ))}
      </ul>

      {remaining > 0 && (
        <div className="cz-list-more">
          <p className="cz-meta">
            {visible.length.toLocaleString("fr-FR")} sur {plural(items.length, "casier", "casiers")}
          </p>
          <button type="button" className="cz-button cz-button--compact" onClick={showMore}>
            <ChevronDown size={16} aria-hidden="true" />
            Afficher plus
          </button>
        </div>
      )}
    </div>
  );
}
