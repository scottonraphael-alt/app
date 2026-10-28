import { useCallback, useEffect, useState } from "react";

const KEY = "iris.display";
const EVENT = "iris-display-change";
export const DENSITIES = ["confort", "compact"];
export const SCALE_MIN = 90;
export const SCALE_MAX = 120;
const DEFAULTS = { density: "confort", scale: 100 };

export function normalizePrefs(raw) {
  const density = DENSITIES.includes(raw?.density) ? raw.density : DEFAULTS.density;
  const n = Math.round(Number(raw?.scale));
  const scale = Number.isFinite(n) ? Math.min(SCALE_MAX, Math.max(SCALE_MIN, n)) : DEFAULTS.scale;
  return { density, scale };
}

function read() {
  try {
    return normalizePrefs(JSON.parse(window.localStorage.getItem(KEY) || "{}"));
  } catch {
    return { ...DEFAULTS };
  }
}

export function applyDisplay(prefs) {
  const root = document.documentElement;
  root.setAttribute("data-density", prefs.density);
  root.setAttribute("data-text-scale", String(prefs.scale));
  root.style.fontSize = `${prefs.scale}%`;
}

export default function useDisplayPrefs() {
  const [prefs, setPrefs] = useState(read);

  useEffect(() => { applyDisplay(prefs); }, [prefs]);
  useEffect(() => {
    const sync = () => setPrefs(read());
    window.addEventListener(EVENT, sync);
    return () => window.removeEventListener(EVENT, sync);
  }, []);

  const update = useCallback((patch) => {
    const next = normalizePrefs({ ...read(), ...patch });
    try { window.localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* ignore */ }
    setPrefs(next);
    window.dispatchEvent(new Event(EVENT));
  }, []);

  const reset = useCallback(() => update(DEFAULTS), [update]);
  return { prefs, update, reset };
}
