import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, Sparkles, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api, getErrorMessage } from "../../../api/client";
import PresenceAvatars from "./PresenceAvatars";
import SlaBadge from "./SlaBadge";
import CrisisBadge from "./CrisisBadge";
import { asList } from "./crisis";
import "./ai.css";

/** Ligne de signaux du ticket : SLA, présence, attribution assistée (responsables). */
export default function TicketSignals({ ticketId, viewers, canRoute, assigned, archived, crisisLevel, onAssigned }) {
  const [sla, setSla] = useState(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [assigning, setAssigning] = useState(false);

  const loadSla = useCallback(async (signal) => {
    try {
      const { data } = await api.get("/tickets/sla", { params: { status: "open" }, signal });
      const row = asList(data?.items).find((item) => item.ticket_id === ticketId);
      if (!signal?.aborted) setSla(row?.sla || null);
    } catch {
      if (!signal?.aborted) setSla(null);
    }
  }, [ticketId]);

  useEffect(() => {
    setSla(null);
    setOpen(false);
    setSuggestions([]);
    const controller = new AbortController();
    loadSla(controller.signal);
    const timer = window.setInterval(() => { if (document.visibilityState !== "hidden") loadSla(controller.signal); }, 60 * 1000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [loadSla]);

  const toggleSuggestions = async () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    setLoading(true);
    try {
      const { data } = await api.get(`/tickets/${ticketId}/routing/suggestions`);
      setSuggestions(asList(data?.suggestions));
    } catch (requestError) {
      setSuggestions([]);
      toast.error(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  const autoAssign = async () => {
    setAssigning(true);
    try {
      const { data } = await api.post(`/tickets/${ticketId}/routing/auto-assign`);
      toast.success(`Ticket attribué à ${data?.assigned?.name || "un helper"}.`);
      setOpen(false);
      onAssigned?.(data?.assigned);
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setAssigning(false);
    }
  };

  const showRouting = canRoute && !archived;
  return (
    <div className="tai-signals" data-testid="ticket-signals">
      <div className="tai-signals-row">
        <CrisisBadge level={crisisLevel} />
        <SlaBadge sla={sla} />
        <PresenceAvatars viewers={viewers} />
        {showRouting && (
          <button type="button" className="tai-btn" onClick={toggleSuggestions} aria-expanded={open} aria-controls="tai-routing" data-testid="routing-suggestions-button">
            <Sparkles size={14} aria-hidden="true" /> Suggestions d’attribution
          </button>
        )}
      </div>
      {showRouting && open && (
        <div className="tai-routing" id="tai-routing">
          {loading && <p role="status"><LoaderCircle size={14} className="tai-spin" aria-hidden="true" /> Calcul des suggestions…</p>}
          {!loading && suggestions.length === 0 && <p>Aucun helper disponible pour le moment.</p>}
          {!loading && suggestions.length > 0 && (
            <ol className="tai-suggestions">
              {suggestions.map((item, index) => (
                <li key={item.helper_id}>
                  <div className="tai-suggestion-head"><strong>{item.name}</strong><span className="tai-score">{item.score} pts</span>{index === 0 && <span className="tai-badge tai-sla-ok">Recommandé</span>}</div>
                  <ul>{asList(item.reasons).map((reason) => <li key={reason}>{reason}</li>)}</ul>
                </li>
              ))}
            </ol>
          )}
          {!assigned && !loading && suggestions.length > 0 && (
            <button type="button" className="tai-btn tai-btn-solid" onClick={autoAssign} disabled={assigning} data-testid="auto-assign-button">
              {assigning ? <LoaderCircle size={14} className="tai-spin" aria-hidden="true" /> : <Wand2 size={14} aria-hidden="true" />} Attribuer automatiquement
            </button>
          )}
          {assigned && <p className="tai-note">Ce ticket a déjà un interlocuteur : l’attribution automatique est désactivée.</p>}
        </div>
      )}
    </div>
  );
}
