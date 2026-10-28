import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Download, Loader2, Tag, UserCheck, X } from "lucide-react";

import { bulkExport, bulkFollowUp, bulkKeys, bulkTag, fetchAssignees } from "./casierBulkApi";
import { errorMessage } from "./casierApi";
import { plural } from "./formatters";

// Barre d'actions groupées : étiquette, suivi, export CSV. `ids` = casiers cochés.
export default function CasierBulkBar({ ids, onClear, onClose, totalVisible, onSelectAll }) {
  const queryClient = useQueryClient();
  const tagId = useId();
  const assigneeId = useId();
  const dueId = useId();
  const [tag, setTag] = useState("");
  const [assignee, setAssignee] = useState("");
  const [due, setDue] = useState("");
  const [note, setNote] = useState("");
  const count = ids.length;

  const assignees = useQuery({ queryKey: bulkKeys.assignees(), queryFn: fetchAssignees, staleTime: 300_000 });
  const done = (label) => (result) => {
    const skipped = result?.skipped ? ` (${result.skipped} déjà à jour)` : "";
    toast.success(`${label} : ${plural(result?.updated ?? 0, "casier", "casiers")}${skipped}.`);
    queryClient.invalidateQueries({ queryKey: bulkKeys.meta() });
  };

  const tagMutation = useMutation({
    mutationFn: () => bulkTag(ids, tag.trim()),
    onSuccess: (result) => { done("Étiquette ajoutée")(result); setTag(""); },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const followMutation = useMutation({
    mutationFn: () => bulkFollowUp(ids, { assigneeId: assignee, note, dueDate: due }),
    onSuccess: (result) => { done(assignee ? "Suivi assigné" : "Suivi retiré")(result); setNote(""); },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const exportMutation = useMutation({
    mutationFn: () => bulkExport(ids),
    onSuccess: () => toast.success("Export CSV téléchargé."),
    onError: (error) => toast.error(errorMessage(error)),
  });
  const busy = tagMutation.isPending || followMutation.isPending || exportMutation.isPending;

  return (
    <section className="cz-bulk" aria-label="Actions groupées">
      <div className="cz-bulk-head">
        <p className="cz-bulk-count" role="status" aria-live="polite">
          {count === 0 ? "Cochez des casiers pour agir en lot." : plural(count, "casier sélectionné", "casiers sélectionnés")}
        </p>
        <div className="cz-bulk-head-actions">
          <button type="button" className="cz-button cz-button--compact" onClick={onSelectAll} disabled={!totalVisible}>
            Tout sélectionner ({Math.min(totalVisible || 0, 100)})
          </button>
          <button type="button" className="cz-button cz-button--compact" onClick={onClear} disabled={count === 0}>
            Vider
          </button>
          <button type="button" className="cz-icon-button" onClick={onClose} aria-label="Quitter la sélection">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="cz-bulk-grid">
        <form
          className="cz-bulk-form"
          onSubmit={(event) => { event.preventDefault(); if (tag.trim() && count) tagMutation.mutate(); }}
        >
          <label htmlFor={tagId} className="cz-label">Ajouter une étiquette</label>
          <div className="cz-bulk-row">
            <input id={tagId} className="cz-input" value={tag} maxLength={24} onChange={(e) => setTag(e.target.value)} placeholder="ex. à surveiller" />
            <button type="submit" className="cz-button cz-button--compact cz-button--primary" disabled={busy || !count || !tag.trim()}>
              {tagMutation.isPending ? <Loader2 size={15} className="cz-spin" aria-hidden="true" /> : <Tag size={15} aria-hidden="true" />}
              Ajouter
            </button>
          </div>
        </form>

        <form
          className="cz-bulk-form"
          onSubmit={(event) => { event.preventDefault(); if (count) followMutation.mutate(); }}
        >
          <label htmlFor={assigneeId} className="cz-label">Assigner un suivi</label>
          <div className="cz-bulk-row">
            <select id={assigneeId} className="cz-input" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              <option value="">Retirer le suivi</option>
              {(assignees.data || []).map((person) => (
                <option key={person.id} value={person.id}>{person.name}</option>
              ))}
            </select>
            <label htmlFor={dueId} className="cz-sr-only">Échéance</label>
            <input id={dueId} type="date" className="cz-input" value={due} onChange={(e) => setDue(e.target.value)} disabled={!assignee} />
          </div>
          <div className="cz-bulk-row">
            <input
              className="cz-input"
              aria-label="Consigne de suivi"
              value={note}
              maxLength={300}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Consigne (facultatif)"
              disabled={!assignee}
            />
            <button type="submit" className="cz-button cz-button--compact cz-button--primary" disabled={busy || !count}>
              {followMutation.isPending ? <Loader2 size={15} className="cz-spin" aria-hidden="true" /> : <UserCheck size={15} aria-hidden="true" />}
              Appliquer
            </button>
          </div>
        </form>

        <div className="cz-bulk-form">
          <span className="cz-label">Exporter</span>
          <button type="button" className="cz-button cz-button--compact" disabled={busy || !count} onClick={() => exportMutation.mutate()}>
            {exportMutation.isPending ? <Loader2 size={15} className="cz-spin" aria-hidden="true" /> : <Download size={15} aria-hidden="true" />}
            Télécharger en CSV
          </button>
        </div>
      </div>
    </section>
  );
}
