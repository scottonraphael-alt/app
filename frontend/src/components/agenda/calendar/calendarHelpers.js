// Petites aides partagées par les composants de la page Calendrier.
import { useEffect, useMemo, useState } from "react";

import { isIsoDate, timeToMinutes } from "../dateUtils";

export function joinClasses(...values) {
  return values.filter(Boolean).join(" ");
}

// Requête média suivie en direct (false côté serveur ou sans matchMedia).
export function useMediaQuery(query) {
  const read = () => {
    try {
      return typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia(query).matches
        : false;
    } catch (error) {
      return false;
    }
  };
  const [matches, setMatches] = useState(read);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return undefined;
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    if (typeof list.addEventListener === "function") {
      list.addEventListener("change", update);
      return () => list.removeEventListener("change", update);
    }
    list.addListener(update);
    return () => list.removeListener(update);
  }, [query]);

  return matches;
}

// Ancre virtuelle d'un popover Radix (`Popover.Anchor virtualRef`) : l'élément cliqué tant qu'il est
// dans la page, sinon le centre de la fenêtre.
export function useVirtualAnchor(element) {
  return useMemo(
    () => ({
      current: {
        getBoundingClientRect() {
          if (element && element.isConnected) return element.getBoundingClientRect();
          const x = typeof window !== "undefined" ? window.innerWidth / 2 : 0;
          const y = typeof window !== "undefined" ? window.innerHeight / 3 : 0;
          return { x, y, top: y, left: x, right: x, bottom: y, width: 0, height: 0, toJSON() {} };
        },
      },
    }),
    [element],
  );
}

// Rend le focus à l'élément d'origine à la fermeture d'un popover ou d'un tiroir, sauf si une autre fenêtre
// ou un autre popover vient de prendre le focus (« Ajouter ce jour », « Plus d'options »).
export function restoreFocus(event, element) {
  event.preventDefault();
  if (typeof document === "undefined") return;
  const active = document.activeElement;
  const taken = active && active !== document.body && typeof active.closest === "function" && active.closest('[role="dialog"], .ag-popover');
  if (taken) return;
  if (element && element.isConnected && typeof element.focus === "function") element.focus({ preventScroll: true });
}

// Date proposée par défaut pour un ajout : aujourd'hui s'il est dans la période affichée, sinon la date d'ancrage.
export function defaultAddDate(range, anchor, today) {
  if (range && isIsoDate(today) && today >= range.start && today <= range.end) return today;
  return isIsoDate(anchor) ? anchor : today;
}

// Valeurs de champs « date » et « heure » : chaîne vide ↔ null pour l'API.
export function emptyToNull(value) {
  return value === "" || value === undefined ? null : value;
}

export function isEndTimeBeforeStart(startTime, endTime) {
  const start = timeToMinutes(startTime);
  const end = timeToMinutes(endTime);
  return start !== null && end !== null && end <= start;
}

// Compteur de caractères « 120 / 500 ».
export function counterText(value, max) {
  return `${(value || "").length} / ${max}`;
}
