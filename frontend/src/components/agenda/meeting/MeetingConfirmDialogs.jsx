import { useState } from "react";
import { CircleAlert } from "lucide-react";

import "./meeting.css";

import AgendaDialog from "../AgendaDialog";
import { TEXT_LIMITS } from "../agendaConstants";
import { agendaErrorMessage } from "../agendaErrors";

function ErrorLine({ message }) {
  if (!message) return null;
  return (
    <div className="ag-error" role="alert">
      <span className="ag-error-text">
        <CircleAlert size={15} aria-hidden="true" />
        {message}
      </span>
    </div>
  );
}

// Annulation d'une réunion (motif facultatif, visible dans le bandeau et dans le calendrier).
export function CancelMeetingDialog({ open, onOpenChange, onConfirm }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await onConfirm(reason.trim());
      onOpenChange(false);
    } catch (failure) {
      setError(agendaErrorMessage(failure));
      setBusy(false);
    }
  };

  return (
    <AgendaDialog
      open
      onOpenChange={onOpenChange}
      title="Annuler la réunion"
      eyebrow="Réunion staff"
      description="La réunion reste dans la liste, marquée comme annulée, et ses rappels Discord sont retirés."
      size="sm"
      onSubmit={submit}
      dismissible={!busy}
      busy={busy}
      footer={
        <div className="ag-dialog-footer-end">
          <button type="button" className="ag-button ag-button--secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Garder la réunion
          </button>
          <button type="submit" className="ag-button ag-button--danger" disabled={busy}>
            {busy ? "Annulation…" : "Annuler la réunion"}
          </button>
        </div>
      }
    >
      <div className="ag-form">
        <ErrorLine message={error} />
        <div className="ag-field">
          <label className="ag-label" htmlFor="ag-meeting-cancel-reason">
            Motif <span className="ag-label-optional">(facultatif)</span>
          </label>
          <textarea
            id="ag-meeting-cancel-reason"
            className="ag-textarea"
            rows={3}
            value={reason}
            maxLength={TEXT_LIMITS.cancelReason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Ex. : manque de disponibilités cette semaine"
          />
          <span className={`ag-counter${reason.length >= TEXT_LIMITS.cancelReason ? " is-over" : ""}`}>
            {reason.length} / {TEXT_LIMITS.cancelReason}
          </span>
        </div>
      </div>
    </AgendaDialog>
  );
}

// Suppression définitive : confirmation explicite.
export function DeleteMeetingDialog({ open, onOpenChange, title, onConfirm }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await onConfirm();
    } catch (failure) {
      setError(agendaErrorMessage(failure));
      setBusy(false);
    }
  };

  return (
    <AgendaDialog
      open
      onOpenChange={onOpenChange}
      title="Supprimer la réunion"
      eyebrow="Action définitive"
      description={`« ${title || "Cette réunion"} » sera supprimée avec son compte-rendu, ses décisions et ses actions. Cette action est irréversible.`}
      size="sm"
      onSubmit={submit}
      dismissible={!busy}
      busy={busy}
      footer={
        <div className="ag-dialog-footer-end">
          <button type="button" className="ag-button ag-button--secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Annuler
          </button>
          <button type="submit" className="ag-button ag-button--danger" disabled={busy}>
            {busy ? "Suppression…" : "Supprimer définitivement"}
          </button>
        </div>
      }
    >
      <div className="ag-form">
        <ErrorLine message={error} />
      </div>
    </AgendaDialog>
  );
}
