import { CircleAlert, Lock } from "lucide-react";

import "./meetings.css";

import { agendaErrorMessage } from "../agendaErrors";

// Bandeau d'erreur d'une carte, avec « Réessayer ».
export function PanelError({ message, error = null, onRetry = null }) {
  const text = error ? agendaErrorMessage(error, message) : message;
  return (
    <div className="ag-error" role="alert">
      <span className="ag-error-text">
        <CircleAlert size={15} aria-hidden="true" />
        {text && text !== message ? `${message} ${text}` : message}
      </span>
      {onRetry ? (
        <button type="button" className="ag-error-retry" onClick={() => onRetry()}>
          Réessayer
        </button>
      ) : null}
    </div>
  );
}

// Lignes grises pendant le chargement (décoratives : la carte porte aria-busy).
export function PanelSkeleton({ rows = 3, height = 44 }) {
  return (
    <div className="ag-skeleton-stack" aria-hidden="true">
      <span className="ag-skeleton ag-skeleton-line" style={{ width: "45%" }} />
      {Array.from({ length: rows }, (_, index) => (
        <span key={index} className="ag-skeleton" style={{ height }} />
      ))}
    </div>
  );
}

// Page refusée (403) : rôle Staff manquant.
export function MeetingsForbidden() {
  return (
    <div className="ag-panel">
      <div className="ag-empty">
        <span className="ag-empty-icon">
          <Lock size={28} aria-hidden="true" />
        </span>
        <h3>Cette page est réservée au staff.</h3>
        <p>Le rôle Discord Staff est nécessaire pour voir les réunions.</p>
      </div>
    </div>
  );
}
