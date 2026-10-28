import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, ArrowRightToLine, Plus, X } from "lucide-react";

import "../../Agenda.css";
import "./meetings-extras.css";

import { agendaErrorMessage, shouldRetryAgendaQuery } from "../agenda/agendaErrors";
import {
  addProposal,
  deleteProposal,
  editProposal,
  extrasKeys,
  fetchProposals,
  listOf,
  reorderProposals,
} from "./meetingExtrasApi";

const DEFAULT_MINUTES = 5;

function clampMinutes(value) {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return DEFAULT_MINUTES;
  return Math.min(240, Math.max(1, n));
}

// Points proposés par chacun avant la réunion : durée estimée, ordre fixé par l'organisateur.
// `onImport` (organisateur) copie les points dans l'ordre du jour du compte-rendu.
export default function ProposalsPanel({ meetingId, onImport = null }) {
  const queryClient = useQueryClient();
  const key = extrasKeys.proposals(meetingId);
  const query = useQuery({
    queryKey: key,
    queryFn: () => fetchProposals(meetingId),
    retry: shouldRetryAgendaQuery,
  });
  const [title, setTitle] = useState("");
  const [minutes, setMinutes] = useState(DEFAULT_MINUTES);
  const [importing, setImporting] = useState(false);

  const items = listOf(query.data);
  const open = query.data?.open !== false;
  const canReorder = Boolean(query.data?.can_reorder);
  const total = Number(query.data?.total_minutes) || 0;

  const refresh = (data) => queryClient.setQueryData(key, data);
  const fail = (error) => toast.error(agendaErrorMessage(error));

  const add = useMutation({
    mutationFn: (payload) => addProposal(meetingId, payload),
    onSuccess: () => {
      setTitle("");
      setMinutes(DEFAULT_MINUTES);
      queryClient.invalidateQueries({ queryKey: key });
    },
    onError: fail,
  });
  const edit = useMutation({
    mutationFn: ({ id, patch }) => editProposal(meetingId, id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id) => deleteProposal(meetingId, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
    onError: fail,
  });
  const reorder = useMutation({
    mutationFn: (ids) => reorderProposals(meetingId, ids),
    onSuccess: refresh,
    onError: fail,
  });

  const move = (index, delta) => {
    const target = index + delta;
    if (target < 0 || target >= items.length || reorder.isPending) return;
    const ids = items.map((item) => item.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];
    reorder.mutate(ids);
  };

  const submit = (event) => {
    event.preventDefault();
    const clean = title.trim();
    if (!clean || add.isPending) return;
    add.mutate({ title: clean, duration_min: clampMinutes(minutes) });
  };

  const runImport = async () => {
    if (!onImport || importing) return;
    setImporting(true);
    try {
      await onImport();
    } catch (error) {
      toast.error(agendaErrorMessage(error));
    } finally {
      setImporting(false);
    }
  };

  if (query.isPending) {
    return (
      <div className="ag-skeleton-stack" aria-busy="true" aria-label="Chargement des points proposés">
        <span className="ag-skeleton" style={{ height: 44 }} />
        <span className="ag-skeleton" style={{ height: 44 }} />
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="ag-error" role="alert">
        <span className="ag-error-text">{agendaErrorMessage(query.error, "Impossible de charger les points proposés.")}</span>
        <button type="button" className="ag-error-retry" onClick={() => query.refetch()}>
          Réessayer
        </button>
      </div>
    );
  }

  return (
    <div className="ag-mx">
      {items.length ? (
        <>
          <p className="ag-mx-hint" aria-live="polite">
            {items.length} point{items.length > 1 ? "s" : ""} proposé{items.length > 1 ? "s" : ""} · {total} min au total
          </p>
          <ol className="ag-mx-list">
            {items.map((item, index) => (
              <li key={item.id} className="ag-mx-row">
                <span className="ag-mx-rank" aria-hidden="true">
                  {index + 1}
                </span>
                <div className="ag-mx-row-main">
                  <span className="ag-mx-row-title">{item.title}</span>
                  <span className="ag-mx-row-meta">Proposé par {item.proposer?.name || "un membre"}</span>
                </div>
                {item.can_edit && open ? (
                  <label className="ag-mx-duration">
                    <span className="ag-sr-only">Durée estimée de « {item.title} » en minutes</span>
                    <input
                      type="number"
                      className="ag-input ag-mx-minutes"
                      min={1}
                      max={240}
                      defaultValue={item.duration_min}
                      key={`${item.id}-${item.duration_min}`}
                      onBlur={(event) => {
                        const next = clampMinutes(event.target.value);
                        event.target.value = next;
                        if (next !== item.duration_min) edit.mutate({ id: item.id, patch: { duration_min: next } });
                      }}
                    />
                    <span aria-hidden="true">min</span>
                  </label>
                ) : (
                  <span className="ag-mx-chip">{item.duration_min} min</span>
                )}
                <span className="ag-meeting-row-tools">
                  {canReorder && open ? (
                    <>
                      <button
                        type="button"
                        className="ag-icon-button ag-icon-button--small"
                        aria-label={`Monter « ${item.title} »`}
                        disabled={index === 0 || reorder.isPending}
                        onClick={() => move(index, -1)}
                      >
                        <ArrowUp size={15} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="ag-icon-button ag-icon-button--small"
                        aria-label={`Descendre « ${item.title} »`}
                        disabled={index === items.length - 1 || reorder.isPending}
                        onClick={() => move(index, 1)}
                      >
                        <ArrowDown size={15} aria-hidden="true" />
                      </button>
                    </>
                  ) : null}
                  {item.can_edit && open ? (
                    <button
                      type="button"
                      className="ag-icon-button ag-icon-button--small ag-icon-button--danger"
                      aria-label={`Retirer « ${item.title} »`}
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(item.id)}
                    >
                      <X size={15} aria-hidden="true" />
                    </button>
                  ) : null}
                </span>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <p className="ag-meeting-empty">Personne n'a encore proposé de point pour cette réunion.</p>
      )}

      {open ? (
        <form className="ag-mx-add" onSubmit={submit}>
          <input
            type="text"
            className="ag-input"
            value={title}
            maxLength={200}
            placeholder="Proposer un point à aborder"
            aria-label="Titre du point proposé"
            onChange={(event) => setTitle(event.target.value)}
          />
          <label className="ag-mx-duration">
            <span className="ag-sr-only">Durée estimée en minutes</span>
            <input
              type="number"
              className="ag-input ag-mx-minutes"
              min={1}
              max={240}
              value={minutes}
              onChange={(event) => setMinutes(event.target.value)}
            />
            <span aria-hidden="true">min</span>
          </label>
          <button type="submit" className="ag-button ag-button--secondary ag-button--small" disabled={!title.trim() || add.isPending}>
            <Plus size={14} aria-hidden="true" />
            Proposer
          </button>
        </form>
      ) : (
        <p className="ag-mx-hint">Cette réunion est fermée : les propositions ne sont plus modifiables.</p>
      )}

      {canReorder && onImport && items.length > 0 && open ? (
        <button
          type="button"
          className="ag-button ag-button--small ag-mx-import"
          onClick={runImport}
          disabled={importing}
        >
          <ArrowRightToLine size={14} aria-hidden="true" />
          {importing ? "Ajout en cours…" : "Ajouter à l'ordre du jour"}
        </button>
      ) : null}
    </div>
  );
}
