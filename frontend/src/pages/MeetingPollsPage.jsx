import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarCheck, CircleAlert, Lock, Plus, RefreshCw, Trash2, X } from "lucide-react";

import AgendaHomeLink from "../components/agenda/AgendaHomeLink";
import useAgendaNoNav from "../components/agenda/useAgendaNoNav";
import { invalidateAgenda } from "../components/agenda/agendaApi";
import { agendaErrorMessage, errorStatus } from "../components/agenda/agendaErrors";
import { closePoll, createPoll, deletePoll, fetchPolls, pollKeys, votePoll } from "../components/agenda/pollsApi";
import { formatDayTitle } from "../components/agenda/dateUtils";
import "../components/agenda/polls/polls.css";

const CHOICES = [
  { value: "yes", label: "Oui" },
  { value: "maybe", label: "Si besoin" },
  { value: "no", label: "Non" },
];
const MAX_SLOTS = 12;

function slotLabel(slot) {
  const hours = slot.end_time ? `${slot.start_time} – ${slot.end_time}` : slot.start_time;
  return `${formatDayTitle(slot.date, { withYear: true })} · ${hours}`;
}

function personName(person) {
  return person?.display_name || person?.username || "Membre du staff";
}

function emptySlot() {
  return { date: "", start_time: "", end_time: "" };
}

function NewPollForm({ onCreated, onCancel }) {
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [slots, setSlots] = useState([emptySlot(), emptySlot()]);
  const [error, setError] = useState("");
  const mutation = useMutation({ mutationFn: createPoll });

  const update = (index, key, value) =>
    setSlots((old) => old.map((slot, i) => (i === index ? { ...slot, [key]: value } : slot)));

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    if (!title.trim()) return setError("Indiquez un titre.");
    const complete = slots.filter((slot) => slot.date && slot.start_time);
    if (complete.length < 2) return setError("Proposez au moins deux créneaux (date et heure de début).");
    try {
      const payload = {
        title: title.trim(),
        location: location.trim(),
        description: description.trim(),
        slots: complete.map((slot) => ({
          date: slot.date,
          start_time: slot.start_time,
          ...(slot.end_time ? { end_time: slot.end_time } : {}),
        })),
      };
      const created = await mutation.mutateAsync(payload);
      toast.success("Sondage créé : le staff est prévenu.");
      onCreated(created);
    } catch (failure) {
      setError(agendaErrorMessage(failure));
    }
  };

  return (
    <form className="ag-panel ag-poll-form" onSubmit={submit} aria-label="Nouveau sondage de créneaux">
      <h2 className="ag-panel-title">Nouveau sondage</h2>
      {error ? (
        <p className="ag-error-text" role="alert">
          <CircleAlert size={15} aria-hidden="true" /> {error}
        </p>
      ) : null}
      <div className="ag-field">
        <label className="ag-label" htmlFor="poll-title">Titre</label>
        <input id="poll-title" className="ag-input" value={title} maxLength={160} onChange={(e) => setTitle(e.target.value)} placeholder="Réunion de novembre" />
      </div>
      <div className="ag-field">
        <label className="ag-label" htmlFor="poll-location">Lieu <span className="ag-label-optional">(facultatif)</span></label>
        <input id="poll-location" className="ag-input" value={location} maxLength={200} onChange={(e) => setLocation(e.target.value)} placeholder="Vocal Staff" />
      </div>
      <div className="ag-field">
        <label className="ag-label" htmlFor="poll-description">Précisions <span className="ag-label-optional">(facultatif)</span></label>
        <textarea id="poll-description" className="ag-textarea" rows={2} value={description} maxLength={1000} onChange={(e) => setDescription(e.target.value)} />
      </div>
      <fieldset className="ag-poll-slots" style={{ border: 0, padding: 0, margin: 0, display: "grid", gap: 10 }}>
        <legend className="ag-label">Créneaux proposés ({slots.length}/{MAX_SLOTS})</legend>
        {slots.map((slot, index) => (
          <div className="ag-poll-slot-row" key={index}>
            <div className="ag-field">
              <label className="ag-label" htmlFor={`poll-date-${index}`}>Date</label>
              <input id={`poll-date-${index}`} type="date" className="ag-input" value={slot.date} onChange={(e) => update(index, "date", e.target.value)} />
            </div>
            <div className="ag-field">
              <label className="ag-label" htmlFor={`poll-start-${index}`}>Début</label>
              <input id={`poll-start-${index}`} type="time" className="ag-input" value={slot.start_time} onChange={(e) => update(index, "start_time", e.target.value)} />
            </div>
            <div className="ag-field">
              <label className="ag-label" htmlFor={`poll-end-${index}`}>Fin</label>
              <input id={`poll-end-${index}`} type="time" className="ag-input" value={slot.end_time} onChange={(e) => update(index, "end_time", e.target.value)} />
            </div>
            <button
              type="button"
              className="ag-icon-button ag-icon-button--small"
              aria-label={`Retirer le créneau ${index + 1}`}
              disabled={slots.length <= 2}
              onClick={() => setSlots((old) => old.filter((_, i) => i !== index))}
            >
              <X size={15} aria-hidden="true" />
            </button>
          </div>
        ))}
        <div>
          <button type="button" className="ag-button ag-button--secondary ag-button--small" disabled={slots.length >= MAX_SLOTS} onClick={() => setSlots((old) => [...old, emptySlot()])}>
            <Plus size={14} aria-hidden="true" /> Ajouter un créneau
          </button>
        </div>
      </fieldset>
      <div className="ag-poll-actions">
        <button type="submit" className="ag-button" disabled={mutation.isPending}>
          {mutation.isPending ? "Création…" : "Créer le sondage"}
        </button>
        <button type="button" className="ag-button ag-button--secondary" onClick={onCancel}>Annuler</button>
      </div>
    </form>
  );
}

function PollCard({ poll, canManage, onChanged }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(null);
  const [includeMaybe, setIncludeMaybe] = useState(true);
  const [busy, setBusy] = useState(false);
  const votes = draft || poll.my_votes || {};
  const open = poll.status === "open";
  const dirty = draft !== null;

  const choose = (slotId, choice) =>
    setDraft((old) => {
      const base = old || { ...poll.my_votes };
      return { ...base, [slotId]: choice };
    });

  const run = async (action, success) => {
    setBusy(true);
    try {
      const result = await action();
      if (success) toast.success(success);
      setDraft(null);
      await onChanged(result);
    } catch (failure) {
      toast.error(agendaErrorMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const save = () => run(() => votePoll(poll.id, votes), "Réponses enregistrées.");
  const close = (slot) => {
    if (!window.confirm(`Planifier la réunion le ${slotLabel(slot)} ? Elle sera ajoutée à l'agenda.`)) return;
    run(async () => {
      const result = await closePoll(poll.id, slot.id, includeMaybe);
      await invalidateAgenda(queryClient);
      return result;
    }, "Réunion créée dans l'agenda.");
  };
  const remove = () => {
    if (!window.confirm("Supprimer ce sondage ?")) return;
    run(() => deletePoll(poll.id), "Sondage supprimé.");
  };

  return (
    <article className="ag-panel ag-poll" aria-labelledby={`poll-${poll.id}`}>
      <div className="ag-poll-head">
        <div>
          <h2 id={`poll-${poll.id}`}>{poll.title}</h2>
          <p className="ag-poll-meta">
            Par {personName(poll.created_by)} · {poll.responses} réponse{poll.responses > 1 ? "s" : ""}
            {poll.location ? ` · ${poll.location}` : ""}
          </p>
          {poll.description ? <p className="ag-poll-meta">{poll.description}</p> : null}
        </div>
        <span className="ag-poll-status">{open ? "Ouvert" : "Clos"}</span>
      </div>

      <div className="ag-poll-table-wrap">
        <table className="ag-poll-table">
          <caption className="ag-sr-only">Créneaux proposés et disponibilités</caption>
          <thead>
            <tr>
              <th scope="col">Créneau</th>
              <th scope="col">Oui / Si besoin / Non</th>
              <th scope="col">Ma réponse</th>
              {open && canManage ? <th scope="col"><span className="ag-sr-only">Choisir</span></th> : null}
            </tr>
          </thead>
          <tbody>
            {poll.slots.map((slot) => (
              <tr key={slot.id} className={slot.id === poll.chosen_slot_id ? "is-chosen" : open && slot.id === poll.best_slot_id ? "is-best" : ""}>
                <th scope="row">
                  {slotLabel(slot)}
                  {slot.id === poll.chosen_slot_id ? <small> · retenu</small> : null}
                  {open && slot.id === poll.best_slot_id ? <small> · le plus plébiscité</small> : null}
                </th>
                <td>
                  <span className="ag-poll-count" aria-label={`${slot.yes} oui, ${slot.maybe} si besoin, ${slot.no} non`}>
                    <b>{slot.yes}</b> / <b>{slot.maybe}</b> / <b>{slot.no}</b>
                  </span>
                </td>
                <td>
                  <span className="ag-poll-choices" role="group" aria-label={`Ma réponse pour ${slotLabel(slot)}`}>
                    {CHOICES.map((choice) => (
                      <button
                        key={choice.value}
                        type="button"
                        data-choice={choice.value}
                        className="ag-poll-choice"
                        aria-pressed={votes[slot.id] === choice.value}
                        disabled={!open || busy}
                        onClick={() => choose(slot.id, choice.value)}
                      >
                        {choice.label}
                      </button>
                    ))}
                  </span>
                </td>
                {open && canManage ? (
                  <td>
                    <button type="button" className="ag-button ag-button--secondary ag-button--small" disabled={busy} onClick={() => close(slot)}>
                      <CalendarCheck size={14} aria-hidden="true" /> Retenir
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {poll.votes.length ? (
        <details className="ag-poll-who">
          <summary>Qui a répondu ({poll.votes.length})</summary>
          <ul>
            {poll.votes.map((row) => (
              <li key={row.voter.id}>
                <strong>{personName(row.voter)}</strong> :{" "}
                {poll.slots
                  .map((slot) => {
                    const choice = CHOICES.find((c) => c.value === row.choices[slot.id]);
                    return `${slot.date.slice(8)}/${slot.date.slice(5, 7)} ${slot.start_time} ${choice ? choice.label.toLowerCase() : "?"}`;
                  })
                  .join(" · ")}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <div className="ag-poll-actions">
        {open ? (
          <button type="button" className="ag-button" disabled={!dirty || busy} onClick={save}>
            Enregistrer mes réponses
          </button>
        ) : null}
        {open && canManage ? (
          <label className="ag-check">
            <input type="checkbox" className="ag-check-input" checked={includeMaybe} onChange={(e) => setIncludeMaybe(e.target.checked)} />
            <span>Inviter aussi les « si besoin »</span>
          </label>
        ) : null}
        {!open && poll.meeting_id ? (
          <Link className="ag-button ag-button--secondary" to={`/staff/calendrier?element=meeting:${encodeURIComponent(poll.meeting_id)}`}>
            Voir la réunion dans l'agenda
          </Link>
        ) : null}
        {canManage ? (
          <button type="button" className="ag-button ag-button--secondary" disabled={busy} onClick={remove}>
            <Trash2 size={15} aria-hidden="true" /> Supprimer
          </button>
        ) : null}
      </div>
    </article>
  );
}

// Sondages de créneaux (façon Doodle) : le staff vote, un responsable retient un créneau et la réunion est créée.
export default function MeetingPollsPage() {
  useAgendaNoNav();
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const query = useQuery({ queryKey: pollKeys.all, queryFn: ({ signal }) => fetchPolls({ signal }) });
  const items = useMemo(() => query.data?.items || [], [query.data]);
  const canManage = Boolean(query.data?.can_manage);
  const refresh = () => queryClient.invalidateQueries({ queryKey: pollKeys.all });

  return (
    <main className="ag-page ag-cal-page">
      <header className="ag-header">
        <div>
          <p className="ag-eyebrow">Espace staff</p>
          <h1>Sondages de créneaux</h1>
          <p className="ag-intro">Trouvez le meilleur moment pour une réunion : chacun indique ses disponibilités.</p>
        </div>
        <div className="ag-header-actions">
          <AgendaHomeLink />
          <Link to="/staff/calendrier" className="ag-button ag-button--secondary">Calendrier</Link>
          {canManage && !creating ? (
            <button type="button" className="ag-button" onClick={() => setCreating(true)}>
              <Plus size={16} aria-hidden="true" /> Nouveau sondage
            </button>
          ) : null}
        </div>
      </header>

      {errorStatus(query.error) === 403 ? (
        <div className="ag-panel">
          <div className="ag-empty">
            <span className="ag-empty-icon"><Lock size={28} aria-hidden="true" /></span>
            <h3>Cette page est réservée au staff.</h3>
          </div>
        </div>
      ) : (
        <div className="ag-poll-list">
          {creating ? (
            <NewPollForm
              onCancel={() => setCreating(false)}
              onCreated={async () => {
                setCreating(false);
                await refresh();
              }}
            />
          ) : null}
          {query.isPending ? (
            <div className="ag-skeleton" style={{ height: 160 }} aria-hidden="true" />
          ) : query.isError ? (
            <div className="ag-error" role="alert">
              <span className="ag-error-text"><CircleAlert size={15} aria-hidden="true" /> Impossible de charger les sondages.</span>
              <button type="button" className="ag-error-retry" onClick={() => query.refetch()}>
                <RefreshCw size={13} aria-hidden="true" /> Réessayer
              </button>
            </div>
          ) : items.length ? (
            items.map((poll) => <PollCard key={poll.id} poll={poll} canManage={canManage} onChanged={refresh} />)
          ) : (
            <div className="ag-panel">
              <div className="ag-empty">
                <span className="ag-empty-icon"><CalendarCheck size={28} aria-hidden="true" /></span>
                <h3>Aucun sondage pour l'instant.</h3>
                <p>{canManage ? "Créez un sondage pour trouver une date de réunion." : "Un responsable peut en créer un."}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
