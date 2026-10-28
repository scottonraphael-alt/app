import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileStack, Settings2 } from "lucide-react";

import "../../Agenda.css";
import "./meetings-extras.css";

import { agendaErrorMessage, shouldRetryAgendaQuery } from "../agenda/agendaErrors";
import { extrasKeys, fetchTemplates, listOf } from "./meetingExtrasApi";
import TemplatesDialog from "./TemplatesDialog";

// Bandeau d'un compte-rendu encore vide : choisir un modèle (texte et ordre du jour), ou gérer les modèles.
// `onApply(templateId)` applique le modèle (le parent enregistre d'abord, puis recharge le document).
export default function TemplateChooser({ meetingId, onApply }) {
  const query = useQuery({
    queryKey: extrasKeys.templates(),
    queryFn: fetchTemplates,
    retry: shouldRetryAgendaQuery,
  });
  const templates = listOf(query.data);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);

  const apply = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      await onApply(selected);
      toast.success("Modèle appliqué.");
    } catch (error) {
      toast.error(agendaErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ag-callout ag-callout--info ag-mx-chooser" role="region" aria-label="Modèles de compte-rendu">
      <FileStack size={17} aria-hidden="true" />
      <div className="ag-mx-chooser-body">
        <p>Compte-rendu vide : partez d'un modèle pour gagner du temps, ou rédigez directement.</p>
        {query.isError ? (
          <p className="ag-mx-hint">{agendaErrorMessage(query.error, "Impossible de charger les modèles.")}</p>
        ) : (
          <div className="ag-mx-chooser-row">
            <label className="ag-sr-only" htmlFor={`ag-mx-template-${meetingId}`}>
              Modèle de compte-rendu
            </label>
            <select
              id={`ag-mx-template-${meetingId}`}
              className="ag-input ag-mx-select"
              value={selected}
              disabled={query.isPending || busy}
              onChange={(event) => setSelected(event.target.value)}
            >
              <option value="">{query.isPending ? "Chargement…" : "Choisir un modèle"}</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                  {template.builtin ? " (proposé par défaut)" : ""}
                </option>
              ))}
            </select>
            <button type="button" className="ag-button ag-button--small" disabled={!selected || busy} onClick={apply}>
              {busy ? "Application…" : "Utiliser ce modèle"}
            </button>
            <button
              type="button"
              className="ag-button ag-button--secondary ag-button--small"
              onClick={() => setManageOpen(true)}
            >
              <Settings2 size={14} aria-hidden="true" />
              Gérer les modèles
            </button>
          </div>
        )}
      </div>
      <TemplatesDialog open={manageOpen} onOpenChange={setManageOpen} />
    </div>
  );
}
