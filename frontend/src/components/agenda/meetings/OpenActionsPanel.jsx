import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowUpRight, CalendarDays, Check, CircleCheckBig, UserX } from "lucide-react";

import "./meetings.css";

import { PersonLabel } from "../HelperAvatar";
import { Pill } from "../TypeBadge";
import { agendaKeys, applyActionToggleResult, toggleMeetingAction } from "../agendaApi";
import { agendaErrorMessage, isNotFound } from "../agendaErrors";
import { formatDayShort, isIsoDate, relativeDayLabel } from "../dateUtils";
import { PanelError, PanelSkeleton } from "./MeetingsStates";

function actionKey(entry) {
  return `${entry.meeting_id}:${entry.item?.id}`;
}

// Après un cochage : la liste des réunions (compteurs) et le détail de la réunion sont périmés. La vue
// d'ensemble n'est pas relue tout de suite, pour que la ligne cochée reste visible (et annulable).
function refreshAfterToggle(queryClient, meetingId) {
  return Promise.all([
    queryClient.invalidateQueries({
      queryKey: agendaKeys.meetingsAll,
      predicate: (query) => query.queryKey[2] !== "overview",
    }),
    queryClient.invalidateQueries({ queryKey: agendaKeys.meeting(meetingId), exact: true }),
  ]);
}

function DueDate({ value, done, today }) {
  if (!isIsoDate(value)) return null;
  const withYear = isIsoDate(today) && value.slice(0, 4) !== today.slice(0, 4);
  const short = formatDayShort(value, { withYear });
  if (!done && isIsoDate(today) && value < today) {
    return (
      <Pill icon={CalendarDays} tone="danger" size="sm" title="Échéance dépassée">
        En retard · {short}
      </Pill>
    );
  }
  const relative = isIsoDate(today) ? relativeDayLabel(value, today) : null;
  return (
    <Pill icon={CalendarDays} tone="white" size="sm" title={`Échéance : ${short}`}>
      {relative || short}
    </Pill>
  );
}

function ActionRow({ entry, done, busy, today, onToggle }) {
  const item = entry.item;
  const text = item.text || "Action sans intitulé";
  return (
    <li className={`ag-action-row${done ? " is-done" : ""}`}>
      <button
        type="button"
        role="checkbox"
        aria-checked={done ? "true" : "false"}
        aria-label={done ? `Rouvrir l'action : ${text}` : `Marquer comme faite : ${text}`}
        className="ag-action-check"
        disabled={busy}
        onClick={() => onToggle(entry, !done)}
      >
        <Check size={14} strokeWidth={3} aria-hidden="true" />
      </button>
      <div className="ag-action-main">
        <p className="ag-action-text">{text}</p>
        <div className="ag-action-meta">
          {item.assignee ? (
            <PersonLabel person={item.assignee} size={20} className="ag-action-assignee" />
          ) : (
            <span className="ag-action-unassigned">
              <UserX size={14} aria-hidden="true" />
              Non attribuée
            </span>
          )}
          <DueDate value={item.due_date} done={done} today={today} />
          <Link
            to={`/staff/meetings/${encodeURIComponent(entry.meeting_id)}`}
            className="ag-action-meeting"
            title={`Ouvrir la réunion « ${entry.meeting_title || "Réunion"} »`}
          >
            <ArrowUpRight size={14} aria-hidden="true" />
            <span>{entry.meeting_title || "Réunion"}</span>
          </Link>
        </div>
      </div>
    </li>
  );
}

// Carte « Actions à suivre » (overview.open_actions) : cochage optimiste par PATCH …/actions/{id}.
export default function OpenActionsPanel({ actions, counts, today, loading = false, error = null, onRetry }) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState(null);
  const [overrides, setOverrides] = useState(() => new Map());
  const [pending, setPending] = useState(() => new Set());

  const list = useMemo(
    () => (Array.isArray(actions) ? actions.filter((entry) => entry?.meeting_id && entry?.item?.id) : []),
    [actions],
  );

  const isDone = useCallback(
    (entry) => {
      const key = actionKey(entry);
      return overrides.has(key) ? overrides.get(key) : Boolean(entry.item.done);
    },
    [overrides],
  );

  // open_actions ne contient que des actions ouvertes au chargement : on retire des compteurs du serveur
  // celles qui ont été cochées depuis.
  const closedAll = list.filter((entry) => isDone(entry)).length;
  const closedMine = list.filter((entry) => entry.is_mine && isDone(entry)).length;
  const totalAll = Math.max(0, (Number(counts?.open_actions) || list.length) - closedAll);
  const totalMine = Math.max(0, (Number(counts?.my_open_actions) || list.filter((entry) => entry.is_mine).length) - closedMine);
  const hasMine = Number(counts?.my_open_actions) > 0 || list.some((entry) => entry.is_mine);
  const current = filter || (hasMine ? "mine" : "all");
  const visible = current === "mine" ? list.filter((entry) => entry.is_mine) : list;

  const setOverride = useCallback((key, value) => {
    setOverrides((old) => {
      const next = new Map(old);
      if (value === undefined) next.delete(key);
      else next.set(key, value);
      return next;
    });
  }, []);

  const setBusy = useCallback((key, busy) => {
    setPending((old) => {
      const next = new Set(old);
      if (busy) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);

  const toggle = useCallback(
    async (entry, done) => {
      const key = actionKey(entry);
      setOverride(key, done);
      setBusy(key, true);
      try {
        const result = await toggleMeetingAction(entry.meeting_id, entry.item.id, done);
        applyActionToggleResult(queryClient, result);
        setOverride(key, Boolean(result?.item?.done ?? done));
        refreshAfterToggle(queryClient, entry.meeting_id);
        if (done) {
          toast.success("Action terminée.", {
            action: { label: "Annuler", onClick: () => toggle(entry, false) },
          });
        } else {
          toast.success("Action rouverte.");
        }
      } catch (err) {
        setOverride(key, undefined);
        toast.error(agendaErrorMessage(err));
        if (isNotFound(err)) queryClient.invalidateQueries({ queryKey: agendaKeys.meetingsOverview });
      } finally {
        setBusy(key, false);
      }
    },
    [queryClient, setBusy, setOverride],
  );

  return (
    <section className="ag-panel ag-meet-actions" aria-labelledby="ag-meet-actions-title" aria-busy={loading ? "true" : undefined}>
      <div className="ag-panel-header ag-panel-header--actions">
        <span className="ag-panel-icon">
          <CircleCheckBig size={20} aria-hidden="true" />
        </span>
        <div className="ag-panel-heading">
          <p className="ag-eyebrow">Suivi</p>
          <h2 id="ag-meet-actions-title">Actions à suivre</h2>
        </div>
        {!loading && !error ? (
          <div className="ag-filters ag-meet-actions-filters" role="group" aria-label="Filtrer les actions">
            <button
              type="button"
              className="ag-chip"
              aria-pressed={current === "mine" ? "true" : "false"}
              onClick={() => setFilter("mine")}
            >
              Les miennes
              <span className="ag-chip-count">{totalMine}</span>
            </button>
            <button
              type="button"
              className="ag-chip"
              aria-pressed={current === "all" ? "true" : "false"}
              onClick={() => setFilter("all")}
            >
              Toutes
              <span className="ag-chip-count">{totalAll}</span>
            </button>
          </div>
        ) : null}
      </div>

      {loading ? (
        <PanelSkeleton rows={3} height={40} />
      ) : error ? (
        <PanelError message="Impossible de charger les actions à suivre." onRetry={onRetry} />
      ) : visible.length === 0 ? (
        <div className="ag-empty ag-empty--compact">
          <span className="ag-empty-icon">
            <CircleCheckBig size={24} aria-hidden="true" />
          </span>
          <h3>Aucune action en cours.</h3>
          {current === "mine" && list.length ? (
            <button type="button" className="ag-link-button" onClick={() => setFilter("all")}>
              Voir toutes les actions
            </button>
          ) : null}
        </div>
      ) : (
        <ul className="ag-action-list">
          {visible.map((entry) => {
            const key = actionKey(entry);
            return (
              <ActionRow
                key={key}
                entry={entry}
                done={isDone(entry)}
                busy={pending.has(key)}
                today={today}
                onToggle={toggle}
              />
            );
          })}
        </ul>
      )}
    </section>
  );
}

export { OpenActionsPanel };
