import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";

import "../../Agenda.css";
import "./meetings-extras.css";

import AgendaDialog from "../agenda/AgendaDialog";
import { agendaErrorMessage, shouldRetryAgendaQuery } from "../agenda/agendaErrors";
import { createTemplate, deleteTemplate, extrasKeys, fetchTemplates, listOf } from "./meetingExtrasApi";

// Gestion des modèles : liste, suppression, et enregistrement du compte-rendu ouvert (`fromMeetingId`) comme modèle.
export default function TemplatesDialog({ open, onOpenChange, fromMeetingId = null }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: extrasKeys.templates(),
    queryFn: fetchTemplates,
    enabled: open,
    retry: shouldRetryAgendaQuery,
  });
  const [name, setName] = useState("");
  const templates = listOf(query.data);
  const refresh = () => queryClient.invalidateQueries({ queryKey: extrasKeys.templates() });
  const fail = (error) => toast.error(agendaErrorMessage(error));

  const create = useMutation({
    mutationFn: () => createTemplate({ name: name.trim(), from_meeting_id: fromMeetingId }),
    onSuccess: () => {
      setName("");
      toast.success("Modèle enregistré.");
      refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: deleteTemplate,
    onSuccess: () => {
      toast.success("Modèle supprimé.");
      refresh();
    },
    onError: fail,
  });

  if (!open) return null;

  return (
    <AgendaDialog
      open
      onOpenChange={onOpenChange}
      title="Modèles de compte-rendu"
      eyebrow="Réunions"
      description="Les modèles proposent un texte de départ et un ordre du jour avec durées. Les modèles par défaut ne se suppriment pas."
      size="md"
      footer={
        <div className="ag-dialog-footer-end">
          <button type="button" className="ag-button ag-button--secondary" onClick={() => onOpenChange(false)}>
            Fermer
          </button>
        </div>
      }
    >
      <div className="ag-mx">
        {query.isPending ? (
          <span className="ag-skeleton" style={{ height: 120 }} aria-busy="true" />
        ) : query.isError ? (
          <div className="ag-error" role="alert">
            <span className="ag-error-text">{agendaErrorMessage(query.error, "Impossible de charger les modèles.")}</span>
            <button type="button" className="ag-error-retry" onClick={() => query.refetch()}>
              Réessayer
            </button>
          </div>
        ) : (
          <ul className="ag-mx-list">
            {templates.map((template) => (
              <li key={template.id} className="ag-mx-row">
                <div className="ag-mx-row-main">
                  <span className="ag-mx-row-title">{template.name}</span>
                  <span className="ag-mx-row-meta">
                    {template.builtin ? "Proposé par défaut" : `Par ${template.created_by?.name || "un membre"}`}
                    {template.agenda_items.length
                      ? ` · ${template.agenda_items.length} point${template.agenda_items.length > 1 ? "s" : ""} (${template.agenda_items.reduce((sum, i) => sum + (Number(i.duration_min) || 0), 0)} min)`
                      : ""}
                  </span>
                </div>
                {template.can_delete ? (
                  <button
                    type="button"
                    className="ag-icon-button ag-icon-button--small ag-icon-button--danger"
                    aria-label={`Supprimer le modèle « ${template.name} »`}
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(template.id)}
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {fromMeetingId ? (
          <form
            className="ag-mx-add"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim() && !create.isPending) create.mutate();
            }}
          >
            <input
              type="text"
              className="ag-input"
              value={name}
              maxLength={80}
              placeholder="Nom du nouveau modèle"
              aria-label="Nom du nouveau modèle"
              onChange={(event) => setName(event.target.value)}
            />
            <button type="submit" className="ag-button ag-button--small" disabled={!name.trim() || create.isPending}>
              Enregistrer cette réunion comme modèle
            </button>
          </form>
        ) : null}
      </div>
    </AgendaDialog>
  );
}
