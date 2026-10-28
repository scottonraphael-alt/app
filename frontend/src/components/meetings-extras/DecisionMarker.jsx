import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bookmark, X } from "lucide-react";

import "../../Agenda.css";
import "./meetings-extras.css";

import { agendaErrorMessage, shouldRetryAgendaQuery } from "../agenda/agendaErrors";
import { extrasKeys, fetchMeetingDecisions, listOf, markDecision, unmarkDecision } from "./meetingExtrasApi";

// Décisions marquées dans le compte-rendu : on sélectionne un passage puis « Marquer la sélection »,
// ou on saisit le texte. Elles alimentent le registre des décisions (/staff/decisions).
// `getSelection()` renvoie { text, blockId } du passage sélectionné dans l'éditeur (ou null).
export default function DecisionMarker({ meetingId, getSelection = null, canMark = true }) {
  const queryClient = useQueryClient();
  const key = extrasKeys.decisions(meetingId);
  const query = useQuery({
    queryKey: key,
    queryFn: () => fetchMeetingDecisions(meetingId),
    retry: shouldRetryAgendaQuery,
  });
  const [text, setText] = useState("");
  const items = listOf(query.data);
  const fail = (error) => toast.error(agendaErrorMessage(error));

  const mark = useMutation({
    mutationFn: (payload) => markDecision(meetingId, payload),
    onSuccess: () => {
      setText("");
      toast.success("Décision ajoutée au registre.");
      queryClient.invalidateQueries({ queryKey: key });
      queryClient.invalidateQueries({ queryKey: ["meeting-extras", "register"] });
    },
    onError: fail,
  });
  const unmark = useMutation({
    mutationFn: unmarkDecision,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: key });
      queryClient.invalidateQueries({ queryKey: ["meeting-extras", "register"] });
    },
    onError: fail,
  });

  const markSelection = () => {
    let selection = null;
    try {
      selection = getSelection ? getSelection() : null;
    } catch (error) {
      selection = null;
    }
    const picked = selection?.text?.trim();
    if (!picked) {
      toast.info("Sélectionnez d'abord un passage du compte-rendu, ou saisissez la décision ci-dessous.");
      return;
    }
    mark.mutate({ text: picked.slice(0, 500), block_id: selection.blockId || null });
  };

  return (
    <div className="ag-mx">
      {canMark ? (
        <>
          <div className="ag-mx-chooser-row">
            {getSelection ? (
              <button
                type="button"
                className="ag-button ag-button--secondary ag-button--small"
                onMouseDown={(event) => event.preventDefault()}
                onClick={markSelection}
                disabled={mark.isPending}
              >
                <Bookmark size={14} aria-hidden="true" />
                Marquer la sélection comme décision
              </button>
            ) : null}
          </div>
          <form
            className="ag-mx-add"
            onSubmit={(event) => {
              event.preventDefault();
              const clean = text.trim();
              if (clean && !mark.isPending) mark.mutate({ text: clean });
            }}
          >
            <input
              type="text"
              className="ag-input"
              value={text}
              maxLength={500}
              placeholder="Saisir une décision pour le registre"
              aria-label="Texte de la décision à enregistrer"
              onChange={(event) => setText(event.target.value)}
            />
            <button type="submit" className="ag-button ag-button--secondary ag-button--small" disabled={!text.trim() || mark.isPending}>
              Enregistrer
            </button>
          </form>
        </>
      ) : null}

      {query.isError ? (
        <p className="ag-mx-hint">{agendaErrorMessage(query.error, "Impossible de charger les décisions marquées.")}</p>
      ) : items.length ? (
        <>
          <p className="ag-mx-hint">Dans le registre des décisions :</p>
          <ul className="ag-mx-list">
            {items.map((item) => (
              <li key={item.id} className="ag-mx-row">
                <div className="ag-mx-row-main">
                  <span className="ag-mx-row-title">{item.text}</span>
                  {item.marked_by ? <span className="ag-mx-row-meta">Marquée par {item.marked_by}</span> : null}
                </div>
                {item.can_delete && canMark ? (
                  <button
                    type="button"
                    className="ag-icon-button ag-icon-button--small ag-icon-button--danger"
                    aria-label={`Retirer du registre : ${item.text}`}
                    disabled={unmark.isPending}
                    onClick={() => unmark.mutate(item.id)}
                  >
                    <X size={15} aria-hidden="true" />
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          <Link to="/staff/decisions" className="ag-mx-link">
            Voir le registre des décisions
          </Link>
        </>
      ) : (
        <p className="ag-mx-hint">
          Aucune décision marquée pour l'instant. <Link to="/staff/decisions" className="ag-mx-link">Voir le registre</Link>
        </p>
      )}
    </div>
  );
}
