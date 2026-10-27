import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, Phone, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { api, getErrorMessage } from "../../../api/client";
import { CRISIS_LABELS, asList, isCrisis } from "./crisis";
import "./ai.css";

const telHref = (phone) => `tel:${String(phone).replace(/[^\d+]/g, "")}`;
const formatTime = (value) => (value ? new Date(value).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");

export default function CrisisBanner({ ticketId, refreshKey, helperNames = {} }) {
  const [crisis, setCrisis] = useState(null);
  const [acking, setAcking] = useState(false);

  const load = useCallback(async (signal) => {
    try {
      const { data } = await api.get(`/tickets/${ticketId}/crisis`, { signal });
      if (!signal?.aborted) setCrisis(data && typeof data.level === "string" ? data : null);
    } catch {
      if (!signal?.aborted) setCrisis(null);
    }
  }, [ticketId]);

  useEffect(() => {
    setCrisis(null);
    const controller = new AbortController();
    load(controller.signal);
    const timer = window.setInterval(() => { if (document.visibilityState !== "hidden") load(controller.signal); }, 60 * 1000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [load, refreshKey]);

  const ack = async () => {
    setAcking(true);
    try {
      const { data } = await api.post(`/tickets/${ticketId}/crisis/ack`, {});
      setCrisis(data);
      toast.success("Prise en charge enregistrée.");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setAcking(false);
    }
  };

  if (!crisis || !isCrisis(crisis.level)) return null;
  const guidance = crisis.guidance || {};
  const acknowledged = Boolean(crisis.acknowledged_at);
  const reasons = asList(crisis.reasons);
  return (
    <section className={`tai-crisis tai-level-${crisis.level}`} aria-label={`Alerte de crise : ${CRISIS_LABELS[crisis.level]}`} data-testid="crisis-banner">
      <div className="tai-crisis-head">
        <ShieldAlert size={22} aria-hidden="true" />
        <div className="tai-crisis-title">
          <strong role="status">{CRISIS_LABELS[crisis.level]}</strong>
          <span>
            {reasons.length ? reasons.join(" · ") : "Signaux de détresse détectés dans la conversation."}
          </span>
        </div>
        {acknowledged
          ? <span className="tai-crisis-ack" data-testid="crisis-acknowledged">
              Pris en charge{helperNames[crisis.acknowledged_by] ? ` par ${helperNames[crisis.acknowledged_by]}` : ""} · {formatTime(crisis.acknowledged_at)}
            </span>
          : <button type="button" className="tai-btn tai-btn-solid" onClick={ack} disabled={acking} data-testid="crisis-ack-button">
              {acking && <LoaderCircle size={14} className="tai-spin" aria-hidden="true" />} J’ai pris en charge
            </button>}
      </div>
      <details className="tai-crisis-guide">
        <summary>{guidance.title || "Marche à suivre"}</summary>
        {asList(guidance.steps).length > 0 && <ol>{asList(guidance.steps).map((step) => <li key={step}>{step}</li>)}</ol>}
        {asList(guidance.resources).length > 0 && (
          <ul className="tai-phones" aria-label="Numéros utiles">
            {asList(guidance.resources).map((item) => (
              <li key={item.phone}>
                <a href={telHref(item.phone)} className="tai-btn"><Phone size={14} aria-hidden="true" /> {item.phone}</a>
                <span>{item.label}</span>
              </li>
            ))}
          </ul>
        )}
        {guidance.reminder && <p className="tai-note">{guidance.reminder}</p>}
      </details>
    </section>
  );
}
