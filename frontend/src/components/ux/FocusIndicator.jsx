import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { BellOff } from "lucide-react";

import { api } from "../../api/client";
import useFocusMode, { URGENT_TYPES } from "../../hooks/useFocusMode";
import "./ux.css";

function format(ms) {
  const total = Math.ceil(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// Indicateur visible + pilotage des badges : les crises (non lues) lèvent le filtre.
export default function FocusIndicator() {
  const { active, remainingMs, stop } = useFocusMode();
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: async () => (await api.get("/notifications")).data,
    enabled: active, refetchInterval: 60000, retry: false,
  });
  const urgent = active && (data?.items || []).some((n) => !n.read_at && URGENT_TYPES.includes(n.type));

  useEffect(() => {
    const root = document.documentElement;
    if (urgent) root.setAttribute("data-focus-urgent", "1");
    else root.removeAttribute("data-focus-urgent");
  }, [urgent]);

  if (!active) return null;
  return (
    <div className="ux-focus" role="status" aria-live="polite" data-testid="focus-indicator">
      <BellOff size={14} aria-hidden="true" />
      <span>Concentration {format(remainingMs)}{urgent ? " · urgence en attente" : ""}</span>
      <button type="button" onClick={stop}>Arrêter</button>
    </div>
  );
}
