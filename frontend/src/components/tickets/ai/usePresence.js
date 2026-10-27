import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../api/client";

const INTERVAL = 20 * 1000;
const TYPING_HOLD = 6 * 1000;

/** Heartbeat toutes les 20 s sur le ticket ouvert + lecture des autres personnes présentes. */
export default function usePresence(ticketId) {
  const [viewers, setViewers] = useState([]);
  const typingUntil = useRef(0);
  const resource = `ticket:${ticketId}`;

  const beat = useCallback(async () => {
    if (document.visibilityState === "hidden") return;
    try {
      await api.post("/presence/heartbeat", { resource, typing: Date.now() < typingUntil.current });
      const { data } = await api.get("/presence", { params: { resource } });
      setViewers(Array.isArray(data?.viewers) ? data.viewers : []);
    } catch {
      // La présence est un confort : on ignore les erreurs ponctuelles.
    }
  }, [resource]);

  useEffect(() => {
    setViewers([]);
    typingUntil.current = 0;
    beat();
    const timer = window.setInterval(beat, INTERVAL);
    return () => {
      window.clearInterval(timer);
      try {
        const left = api.delete("/presence", { data: { resource } });
        left?.catch?.(() => undefined);
      } catch {
        // ignoré
      }
    };
  }, [beat, resource]);

  const notifyTyping = useCallback(() => {
    const wasTyping = Date.now() < typingUntil.current;
    typingUntil.current = Date.now() + TYPING_HOLD;
    if (!wasTyping) beat();
  }, [beat]);

  return { viewers, notifyTyping };
}
