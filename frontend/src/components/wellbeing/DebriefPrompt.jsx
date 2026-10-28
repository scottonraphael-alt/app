import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { HeartHandshake } from "lucide-react";
import { Link } from "react-router-dom";
import { errorMessage, getDebrief, sendDebrief } from "./wellbeingApi";
import "../../Wellbeing.css";

const fmt = (iso) => new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

/** Proposé après la clôture d'un ticket avec crise élevée ou urgente : pause, message au coordinateur, ressources. */
export default function DebriefPrompt({ ticketId }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["debrief", ticketId], queryFn: () => getDebrief(ticketId), retry: false, staleTime: 60000 });
  const [pause, setPause] = useState(true);
  const [minutes, setMinutes] = useState(15);
  const [notify, setNotify] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => { setDismissed(false); }, [ticketId]);
  const data = query.data;
  if (!data?.eligible || dismissed) return null;
  if (data.done) {
    const until = data.choices?.break_until;
    return (
      <aside className="wb-debrief wb-debrief--done" aria-label="Débrief" data-testid="debrief-done">
        <HeartHandshake size={18} aria-hidden="true" />
        <span>Débrief enregistré.{until ? ` Pause jusqu’à ${fmt(until)}, prends ton temps.` : ""}</span>
      </aside>
    );
  }
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      await sendDebrief(ticketId, { take_break: pause, break_minutes: minutes, notify_coordinator: notify, message: notify && message.trim() ? message.trim() : null });
      toast.success(notify ? "Ton coordinateur a été prévenu." : "Débrief enregistré.");
      qc.invalidateQueries({ queryKey: ["debrief", ticketId] });
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <aside className="wb-debrief" aria-label="Débrief après un ticket lourd" data-testid="debrief-prompt">
      <div className="wb-debrief-head">
        <HeartHandshake size={20} aria-hidden="true" />
        <div>
          <strong>Ce ticket était lourd. Prends soin de toi.</strong>
          <p>Ce temps de débrief est facultatif et reste entre toi et ton équipe de coordination.</p>
        </div>
      </div>
      <form onSubmit={submit} className="wb-debrief-form">
        <label className="wb-check"><input type="checkbox" checked={pause} onChange={(e) => setPause(e.target.checked)} /> Je prends une pause de</label>
        <select className="wb-select" aria-label="Durée de la pause" value={minutes} disabled={!pause} onChange={(e) => setMinutes(Number(e.target.value))}>
          {[10, 15, 30, 45, 60].map((m) => <option key={m} value={m}>{m} min</option>)}
        </select>
        <label className="wb-check"><input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} /> Prévenir un coordinateur pour en parler</label>
        {notify && (
          <textarea className="wb-textarea" maxLength={400} rows={2} aria-label="Message au coordinateur (facultatif)"
            placeholder="Un mot pour le coordinateur (facultatif)" value={message} onChange={(e) => setMessage(e.target.value)} />
        )}
        <ul className="wb-resources">
          {(data.suggestions?.resources || []).map((r) => <li key={r.label}>{r.label}{r.phone && <> <a href={`tel:${r.phone.replace(/[^\d+]/g, "")}`}>{r.phone}</a></>}</li>)}
          <li><Link to="/staff/fiches-reflexes">Relire les fiches réflexes</Link></li>
        </ul>
        <div className="wb-row">
          <button type="submit" className="wb-btn wb-btn--primary" disabled={busy}>Enregistrer</button>
          <button type="button" className="wb-btn" onClick={() => setDismissed(true)}>Plus tard</button>
        </div>
      </form>
    </aside>
  );
}
