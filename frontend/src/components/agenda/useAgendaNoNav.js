import { useEffect } from "react";

import "@/Agenda.css";

export const AGENDA_NO_NAV_CLASS = "agenda-no-nav";

// Compteur partagé : la classe ne part qu'au démontage du dernier composant qui l'a demandée
// (transition entre deux pages agenda, double montage du mode strict).
let mountedCount = 0;

// Masque la barre latérale de l'application tant que la page agenda est montée.
export default function useAgendaNoNav() {
  useEffect(() => {
    mountedCount += 1;
    document.body.classList.add(AGENDA_NO_NAV_CLASS);
    return () => {
      mountedCount = Math.max(0, mountedCount - 1);
      if (mountedCount === 0) {
        document.body.classList.remove(AGENDA_NO_NAV_CLASS);
      }
    };
  }, []);
}

export { useAgendaNoNav };
