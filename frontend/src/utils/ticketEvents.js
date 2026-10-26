import { api } from "../api/client";

export function ticketEvent(kind, ticketId = null, value = null) {
  // Les interactions de l'interface sont distinguées des actions métier vérifiées côté serveur.
  api.post("/tickets/events", { kind, ticket_id: ticketId, value: value == null ? null : String(value).slice(0, 100) }).catch(() => undefined);
}
export const ATTENTION_LABELS = { unassigned: "Sans interlocuteur", inactive: "Sans suivi depuis 7 jours", sync_error: "Synchronisation en échec", summary_error: "Synthèse en échec" };
