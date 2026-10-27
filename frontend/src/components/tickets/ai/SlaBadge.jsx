import { Clock3 } from "lucide-react";
import "./ai.css";

export function slaText(sla) {
  if (!sla) return "";
  if (sla.first_response_at) return sla.breached ? "1re réponse tardive" : "1re réponse faite";
  if (sla.minutes_left === null || sla.minutes_left === undefined) return "";
  if (sla.breached) return `1re réponse dépassée de ${Math.abs(sla.minutes_left)} min`;
  return `1re réponse dans ${sla.minutes_left} min`;
}

export default function SlaBadge({ sla }) {
  const text = slaText(sla);
  if (!text) return null;
  const tone = sla.first_response_at ? (sla.breached ? "late" : "ok") : sla.breached ? "breached" : sla.minutes_left <= 10 ? "soon" : "ok";
  return <span className={`tai-badge tai-sla-${tone}`} data-testid="sla-badge"><Clock3 size={12} aria-hidden="true" /> {text}</span>;
}
