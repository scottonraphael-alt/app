import { useEffect, useState } from "react";

const MAX_BULK = 50;

/** Niveaux de crise (file d'attente) et présence des tickets affichés. API chargée à la demande. */
export default function useTicketListSignals(ticketIds) {
  const [crisis, setCrisis] = useState({});
  const [presence, setPresence] = useState({});
  const key = ticketIds.slice(0, MAX_BULK).join(",");

  useEffect(() => {
    let active = true;
    const run = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const { api } = await import("../../../api/client");
        const { data } = await api.get("/tickets/crisis-queue");
        if (active && Array.isArray(data?.items)) {
          setCrisis(Object.fromEntries(data.items.map((item) => [item.ticket_id, { level: item.level, acknowledged: Boolean(item.acknowledged_at) }])));
        }
      } catch {
        // Signal facultatif.
      }
    };
    run();
    const timer = window.setInterval(run, 60 * 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!key) return undefined;
    let active = true;
    const run = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const { api } = await import("../../../api/client");
        const { data } = await api.get("/presence/bulk", { params: { resources: key.split(",").map((id) => `ticket:${id}`).join(",") } });
        if (active && data?.resources) {
          setPresence(Object.fromEntries(Object.entries(data.resources).map(([resource, viewers]) => [resource.replace(/^ticket:/, ""), Array.isArray(viewers) ? viewers : []])));
        }
      } catch {
        // Signal facultatif.
      }
    };
    run();
    const timer = window.setInterval(run, 30 * 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [key]);

  return { crisis, presence };
}
