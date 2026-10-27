import "./history.css";

import { useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, History, Loader2, Undo2 } from "lucide-react";
import { toast } from "sonner";

import ConfirmDialog from "../ConfirmDialog";
import { casierKeys, errorMessage, errorStatus } from "../casierApi";
import { formatDate, plural } from "../formatters";
import { HISTORY_PAGE_SIZE, getCasierHistory, historyKeys, revertRevision } from "./historyApi";
import { ACTION_LABELS, ENTITY_LABELS, displayValue, fieldLabel } from "./historyLabels";

function retryServerErrors(failureCount, error) {
  const status = errorStatus(error);
  if (status && status < 500) return false;
  return failureCount < 2;
}

function Change({ change }) {
  return (
    <li className="ch-change">
      <span className="ch-field">{fieldLabel(change.field)}</span>
      <span className="ch-diff">
        <del className="ch-before">{displayValue(change.field, change.before)}</del>
        <ArrowRight size={14} aria-hidden="true" />
        <span className="ch-sr-only"> devient </span>
        <ins className="ch-after">{displayValue(change.field, change.after)}</ins>
      </span>
    </li>
  );
}

function Revision({ item, onRevert }) {
  const action = ACTION_LABELS[item.action] || item.action || "Modification";
  const entity = ENTITY_LABELS[item.entity] || "";
  const changes = Array.isArray(item.changes) ? item.changes : [];
  const reverted = Boolean(item.reverted_by);

  return (
    <li className={`ch-item${reverted ? " is-reverted" : ""}`}>
      <div className="ch-item-head">
        <p className="ch-item-title">
          <strong>{action}</strong>
          {entity && <span className="ch-chip">{entity}</span>}
          {item.action === "revert" && <span className="ch-chip ch-chip--info">Annulation</span>}
          {reverted && <span className="ch-chip ch-chip--muted">Annulée</span>}
          {item.stale && !reverted && <span className="ch-chip ch-chip--warn">Modifiée depuis</span>}
        </p>
        <p className="ch-meta">
          {item.actor_name || "Staff"} ·{" "}
          <time dateTime={item.at}>{formatDate(item.at)}</time>
          {reverted && item.reverted_at ? ` · annulée le ${formatDate(item.reverted_at)}` : ""}
        </p>
      </div>

      {changes.length > 0 ? (
        <ul className="ch-changes" aria-label={plural(changes.length, "changement", "changements")}>
          {changes.map((change, index) => (
            <Change key={`${change.field}-${index}`} change={change} />
          ))}
        </ul>
      ) : (
        <p className="ch-nochange">Aucun détail enregistré.</p>
      )}

      {item.revertible && (
        <div className="ch-actions">
          <button type="button" className="cz-button cz-button--compact" onClick={() => onRevert(item)}>
            <Undo2 size={15} aria-hidden="true" />
            Annuler cette modification
          </button>
        </div>
      )}
    </li>
  );
}

// Onglet « Modifications » du casier : révisions, diff champ par champ, annulation.
export default function HistoryPanel({ casierId }) {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState(null);
  const [pending, setPending] = useState(false);
  const [conflict, setConflict] = useState(null); // { message, canForce }
  const [failure, setFailure] = useState(null);

  const query = useInfiniteQuery({
    queryKey: historyKeys.all(casierId),
    queryFn: ({ pageParam, signal }) => getCasierHistory(casierId, { before: pageParam, signal }),
    initialPageParam: undefined,
    getNextPageParam: (last) =>
      Array.isArray(last) && last.length >= HISTORY_PAGE_SIZE ? last[last.length - 1].id : undefined,
    retry: retryServerErrors,
  });

  const items = (query.data?.pages || []).flat();

  const close = () => {
    if (pending) return;
    setTarget(null);
    setConflict(null);
    setFailure(null);
  };

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: historyKeys.all(casierId) });
    queryClient.invalidateQueries({ queryKey: casierKeys.detail(casierId) });
    queryClient.invalidateQueries({ queryKey: casierKeys.lists() });
  };

  const confirm = async () => {
    if (!target) return;
    const force = Boolean(conflict?.canForce);
    setPending(true);
    setFailure(null);
    try {
      await revertRevision(target.id, { force });
      toast.success("Modification annulée.");
      setTarget(null);
      setConflict(null);
      refreshAll();
    } catch (error) {
      const message = errorMessage(error);
      if (errorStatus(error) === 409) {
        // Seul un Responsable reçoit l'invitation à forcer (force=true dans le message).
        setConflict({ message, canForce: /force=true/.test(message) });
        refreshAll();
      } else {
        setConflict(null);
        setFailure(message);
      }
    } finally {
      setPending(false);
    }
  };

  if (query.isPending) {
    return (
      <div className="cz-card ch-state" role="status" aria-live="polite">
        <Loader2 size={18} className="cz-spin" aria-hidden="true" /> Chargement des modifications…
      </div>
    );
  }

  if (query.isError && !items.length) {
    return (
      <div className="cz-card cz-empty cz-empty--error" role="alert">
        <h3>Historique indisponible.</h3>
        <p>{errorMessage(query.error)}</p>
        <div className="cz-empty-actions">
          <button type="button" className="cz-button" onClick={() => query.refetch()}>
            Réessayer
          </button>
        </div>
      </div>
    );
  }

  if (!items.length) {
    return (
      <div className="cz-card cz-empty">
        <History size={24} aria-hidden="true" />
        <p>Aucune modification enregistrée pour ce casier.</p>
      </div>
    );
  }

  const dialogDescription = conflict
    ? null
    : target?.stale
      ? "Cet élément a changé depuis cette version : l'annulation pourrait être refusée. Les pièces jointes ne sont jamais touchées."
      : "L'élément retrouvera l'état qu'il avait avant cette modification. Les pièces jointes ne sont jamais touchées.";

  return (
    <section className="ch-panel" aria-label="Historique des modifications du casier">
      <ol className="ch-list">
        {items.map((item) => (
          <Revision key={item.id} item={item} onRevert={setTarget} />
        ))}
      </ol>

      {query.hasNextPage && (
        <div className="ch-more">
          <button
            type="button"
            className="cz-button"
            onClick={() => query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
          >
            {query.isFetchingNextPage && <Loader2 size={16} className="cz-spin" aria-hidden="true" />}
            Charger plus
          </button>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(target)}
        title={conflict?.canForce ? "Forcer l'annulation ?" : "Annuler cette modification ?"}
        eyebrow="Historique du casier"
        description={dialogDescription}
        confirmLabel={conflict?.canForce ? "Forcer l'annulation" : "Annuler la modification"}
        cancelLabel="Fermer"
        pending={pending}
        onConfirm={confirm}
        onCancel={close}
      >
        {conflict && (
          <p className="ch-alert" role="alert">
            {conflict.message}
          </p>
        )}
        {failure && (
          <p className="ch-alert" role="alert">
            {failure}
          </p>
        )}
      </ConfirmDialog>
    </section>
  );
}
