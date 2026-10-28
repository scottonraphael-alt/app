import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BellRing, Pause, Play, Plus, RotateCcw, SkipBack, SkipForward, Timer } from "lucide-react";

import "../../Agenda.css";
import "./meetings-extras.css";

import { agendaErrorMessage, shouldRetryAgendaQuery } from "../agenda/agendaErrors";
import { extrasKeys, fetchTimer, formatClock, initTimer, timerAction } from "./meetingExtrasApi";

const POLL_MS = 15000;

// Temps écoulé d'un point : valeur du serveur + secondes écoulées depuis la dernière lecture (point en cours).
function liveSeconds(item, isCurrent, running, receivedAt, now) {
  const base = Number(item.spent_sec) || 0;
  if (!isCurrent || !running) return base;
  return base + Math.max(0, Math.floor((now - receivedAt) / 1000));
}

// Minuteur de réunion : temps prévu et écoulé par point de l'ordre du jour, alerte douce au dépassement
// (message poli + une notification discrète une seule fois par point, sans son).
export default function MeetingTimer({ meetingId }) {
  const queryClient = useQueryClient();
  const key = extrasKeys.timer(meetingId);
  const query = useQuery({
    queryKey: key,
    queryFn: () => fetchTimer(meetingId),
    retry: shouldRetryAgendaQuery,
    refetchInterval: (q) => (q.state.data?.running ? POLL_MS : false),
  });
  const data = query.data;
  const initialized = data?.initialized === true;
  const running = initialized && data.running === true;
  const receivedAt = query.dataUpdatedAt || Date.now();

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return undefined;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running, query.dataUpdatedAt]);

  const items = initialized && Array.isArray(data.items) ? data.items : [];
  const current = initialized ? data.current : 0;
  const active = items[current] || null;
  const activeSpent = active ? liveSeconds(active, true, running, receivedAt, now) : 0;
  const activeOver = active ? Math.max(0, activeSpent - active.planned_sec) : 0;
  const canControl = Boolean(data?.can_control);

  // Alerte douce : une seule notification discrète par point dépassé.
  const warned = useRef(new Set());
  useEffect(() => {
    if (active && running && activeOver > 0 && !warned.current.has(active.id)) {
      warned.current.add(active.id);
      toast.info(`Le temps prévu pour « ${active.title} » est écoulé.`);
    }
  }, [active, running, activeOver]);

  const settle = (next) => queryClient.setQueryData(key, next);
  const fail = (error) => toast.error(agendaErrorMessage(error));
  const init = useMutation({
    mutationFn: (payload) => initTimer(meetingId, payload),
    onSuccess: settle,
    onError: fail,
  });
  const act = useMutation({
    mutationFn: (payload) => timerAction(meetingId, payload),
    onSuccess: settle,
    onError: (error) => {
      fail(error);
      queryClient.invalidateQueries({ queryKey: key });
    },
  });
  const run = (action, index) => act.mutate(index === undefined ? { action } : { action, index });
  const busy = act.isPending || init.isPending;

  if (query.isPending) {
    return <span className="ag-skeleton" style={{ height: 80 }} aria-busy="true" aria-label="Chargement du minuteur" />;
  }
  if (query.isError) {
    return (
      <div className="ag-error" role="alert">
        <span className="ag-error-text">{agendaErrorMessage(query.error, "Impossible de charger le minuteur.")}</span>
        <button type="button" className="ag-error-retry" onClick={() => query.refetch()}>
          Réessayer
        </button>
      </div>
    );
  }

  if (!initialized) {
    return (
      <div className="ag-mx">
        <p className="ag-meeting-empty">
          {canControl
            ? "Préparez le minuteur à partir des points proposés ou de l'ordre du jour : chaque point reçoit son temps."
            : "Le minuteur n'est pas encore prêt. Un responsable, l'auteur ou un participant peut le préparer."}
        </p>
        {canControl ? (
          <button
            type="button"
            className="ag-button ag-button--secondary ag-button--small"
            disabled={busy}
            onClick={() => init.mutate({ source: "auto" })}
          >
            <Timer size={14} aria-hidden="true" />
            {init.isPending ? "Préparation…" : "Préparer le minuteur"}
          </button>
        ) : null}
      </div>
    );
  }

  const finished = data.finished === true;
  const totalSpent = items.reduce((sum, item, i) => sum + liveSeconds(item, i === current, running, receivedAt, now), 0);

  return (
    <div className="ag-mx">
      <div className="ag-mx-timer" data-over={activeOver > 0 ? "true" : "false"}>
        <div className="ag-mx-timer-main">
          <p className="ag-mx-timer-label">{finished ? "Réunion terminée" : active ? active.title : "—"}</p>
          <p className="ag-mx-timer-clock" role="timer" aria-label="Temps écoulé sur le point en cours">
            {formatClock(activeSpent)}
            {active ? <span className="ag-mx-timer-planned"> / {formatClock(active.planned_sec)}</span> : null}
          </p>
        </div>
        {canControl ? (
          <div className="ag-mx-timer-actions">
            <button
              type="button"
              className="ag-icon-button"
              aria-label="Point précédent"
              disabled={busy || current === 0}
              onClick={() => run("previous")}
            >
              <SkipBack size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="ag-button ag-button--small"
              disabled={busy || finished}
              onClick={() => run(running ? "pause" : "start")}
            >
              {running ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}
              {running ? "Pause" : "Démarrer"}
            </button>
            <button
              type="button"
              className="ag-icon-button"
              aria-label={current + 1 >= items.length ? "Terminer la réunion" : "Point suivant"}
              disabled={busy || finished}
              onClick={() => run("next")}
            >
              <SkipForward size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="ag-button ag-button--secondary ag-button--small"
              disabled={busy || finished}
              onClick={() => run("extend")}
            >
              <Plus size={14} aria-hidden="true" />5 min
            </button>
            <button
              type="button"
              className="ag-icon-button"
              aria-label="Réinitialiser le minuteur"
              disabled={busy}
              onClick={() => run("reset")}
            >
              <RotateCcw size={16} aria-hidden="true" />
            </button>
          </div>
        ) : null}
      </div>

      {activeOver > 0 && !finished ? (
        <p className="ag-callout ag-callout--warning ag-mx-over" role="status">
          <BellRing size={16} aria-hidden="true" />
          <span>
            Le temps prévu pour ce point est dépassé de {formatClock(activeOver)}. Concluez ou prolongez de 5 minutes.
          </span>
        </p>
      ) : null}

      <ol className="ag-mx-list">
        {items.map((item, index) => {
          const spent = liveSeconds(item, index === current, running, receivedAt, now);
          const over = Math.max(0, spent - item.planned_sec);
          const state = finished || index < current ? "done" : index === current ? "current" : "todo";
          return (
            <li key={item.id} className="ag-mx-row" data-state={state}>
              <span className="ag-mx-rank" aria-hidden="true">
                {index + 1}
              </span>
              <div className="ag-mx-row-main">
                <span className="ag-mx-row-title">{item.title}</span>
                <span className="ag-mx-row-meta">
                  {formatClock(spent)} sur {formatClock(item.planned_sec)}
                  {over > 0 ? ` · dépassé de ${formatClock(over)}` : ""}
                  {state === "current" && !finished ? " · en cours" : ""}
                </span>
              </div>
              {canControl && state !== "current" ? (
                <button
                  type="button"
                  className="ag-button ag-button--secondary ag-button--small"
                  disabled={busy}
                  onClick={() => run("select", index)}
                  aria-label={`Passer au point ${index + 1} : ${item.title}`}
                >
                  Passer ici
                </button>
              ) : null}
            </li>
          );
        })}
      </ol>
      <p className="ag-mx-hint">
        Temps total : {formatClock(totalSpent)} sur {formatClock(data.total_planned_sec)} prévus.
      </p>
    </div>
  );
}
