import { useEffect, useState } from "react";
import { BellRing, ExternalLink, LoaderCircle, Send } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { api, getErrorMessage } from "../api/client";

// Bloc temporaire : peut être retiré sans désactiver le rappel du dimanche côté serveur.
export default function TicketReminderTestPanel() {
  const [cooldown, setCooldown] = useState(false);
  const test = useMutation({
    mutationFn: async () => (await api.post("/admin/ticket-reminders/test")).data,
    onSuccess: () => setCooldown(true),
  });
  useEffect(() => {
    if (!cooldown) return undefined;
    const timeout = window.setTimeout(() => setCooldown(false), 60_000);
    return () => window.clearTimeout(timeout);
  }, [cooldown]);

  return <section className="ta-reminder-panel" aria-labelledby="ticket-reminder-title">
    <div className="ta-reminder-copy"><span className="ta-reminder-icon"><BellRing size={21} /></span><div>
      <h2 id="ticket-reminder-title">Rappel de suivi Discord <span>Test temporaire</span></h2>
      <p>Dimanche à 12 h, heure de Paris · Dossiers sans mise à jour manuelle depuis 7 jours.</p>
      <p className="ta-reminder-notice">Le test envoie un vrai message V2 dans le salon prévu et mentionne uniquement les helpers concernés.</p>
    </div></div>
    <button className="ta-secondary-button" type="button" disabled={test.isPending || cooldown} onClick={() => test.mutate()} data-testid="test-ticket-reminder-button">
      {test.isPending ? <LoaderCircle size={16} className="ta-spin" /> : <Send size={16} />}
      {test.isPending ? "Envoi en cours…" : cooldown ? "Test envoyé · Patientez 1 min" : "Envoyer un test Discord"}
    </button>
    {test.isError && <p className="ta-reminder-result ta-reminder-error" role="alert">{getErrorMessage(test.error)}</p>}
    {test.isSuccess && <div className="ta-reminder-result" role="status">
      <p>Test envoyé : {test.data.ticket_count} dossier(s), {test.data.helper_count} helper(s) concerné(s).{test.data.ticket_count === 0 && " Aucun helper mentionné."}</p>
      {test.data.message_urls.map((url, index) => <a href={url} target="_blank" rel="noreferrer" key={url}>Voir le message{test.data.message_urls.length > 1 ? ` ${index + 1}` : ""} <ExternalLink size={12} /></a>)}
    </div>}
  </section>;
}
