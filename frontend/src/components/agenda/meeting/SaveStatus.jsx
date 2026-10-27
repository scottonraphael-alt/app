import { LoaderCircle } from "lucide-react";

import "./meeting.css";

import { formatInstantTime } from "../dateUtils";

// État de l'enregistrement automatique : un point de couleur et un texte (annoncé poliment aux lecteurs d'écran).
export function describeSaveStatus({ status, online, savedAt, message, retryIn, hasUnsaved }) {
  if (!online && (hasUnsaved || status === "error" || status === "pending" || status === "saving")) {
    return { key: "offline", label: "Hors ligne", detail: "Les modifications partiront au retour de la connexion." };
  }
  switch (status) {
    case "pending":
      return { key: "pending", label: "Modifications en attente…" };
    case "saving":
      return { key: "saving", label: "Enregistrement…" };
    case "error":
      return {
        key: "error",
        label: retryIn
          ? `Échec de l'enregistrement — nouvel essai dans ${retryIn} s`
          : "Échec de l'enregistrement",
        detail: message || "",
      };
    case "conflict":
      return { key: "conflict", label: "Conflit" };
    case "locked":
      return { key: "locked", label: "Verrouillé", detail: "Vos dernières modifications n'ont pas été enregistrées." };
    default: {
      const time = savedAt ? formatInstantTime(new Date(savedAt).toISOString()) : "";
      return { key: "saved", label: "Enregistré", title: time ? `Enregistré à ${time}` : undefined };
    }
  }
}

export default function SaveStatus({
  status,
  online = true,
  savedAt = 0,
  message = "",
  retryIn = 0,
  hasUnsaved = false,
  onRetry,
  className = "",
}) {
  const info = describeSaveStatus({ status, online, savedAt, message, retryIn, hasUnsaved });
  const canRetry = info.key === "error" && typeof onRetry === "function";
  return (
    <span className={`ag-save-status is-${info.key} ${className}`.trim()}>
      <span className="ag-save-live" role="status" aria-live="polite" title={info.title}>
        {info.key === "saving" ? (
          <LoaderCircle size={13} className="ag-save-spin" aria-hidden="true" />
        ) : (
          <span className="ag-save-dot" aria-hidden="true" />
        )}
        <span>{info.label}</span>
        {info.detail ? <span className="ag-save-detail">{info.detail}</span> : null}
      </span>
      {canRetry ? (
        <button type="button" className="ag-link-button" onClick={onRetry}>
          Réessayer maintenant
        </button>
      ) : null}
    </span>
  );
}

export { SaveStatus };
