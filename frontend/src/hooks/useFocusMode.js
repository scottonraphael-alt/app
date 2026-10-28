import { useCallback, useEffect, useState } from "react";

const KEY = "iris.focusUntil";
const EVENT = "iris-focus-change";
export const FOCUS_DURATIONS = [15, 30, 60, 120];
// Types de notifications qui passent toujours, même en mode concentration.
export const URGENT_TYPES = ["ticket_crisis", "handoff_urgent"];

function readUntil() {
  try {
    const value = Number(window.localStorage.getItem(KEY));
    return Number.isFinite(value) && value > Date.now() ? value : 0;
  } catch {
    return 0;
  }
}

function apply(until) {
  const root = document.documentElement;
  if (until) root.setAttribute("data-focus", "on");
  else { root.removeAttribute("data-focus"); root.removeAttribute("data-focus-urgent"); }
}

export function isFocusActive() {
  return readUntil() > 0;
}

// Un son/badge ne doit être émis que hors concentration, ou si la notification est urgente.
export function shouldNotify(type) {
  return !isFocusActive() || URGENT_TYPES.includes(type);
}

export default function useFocusMode() {
  const [until, setUntil] = useState(readUntil);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    apply(until);
    if (!until) return undefined;
    const timer = setInterval(() => {
      const current = readUntil();
      setNow(Date.now());
      if (!current) { setUntil(0); apply(0); }
    }, 1000);
    return () => clearInterval(timer);
  }, [until]);

  useEffect(() => {
    const sync = () => setUntil(readUntil());
    window.addEventListener(EVENT, sync);
    return () => window.removeEventListener(EVENT, sync);
  }, []);

  const start = useCallback((minutes) => {
    const next = Date.now() + minutes * 60000;
    try { window.localStorage.setItem(KEY, String(next)); } catch { /* ignore */ }
    setUntil(next);
    window.dispatchEvent(new Event(EVENT));
  }, []);

  const stop = useCallback(() => {
    try { window.localStorage.removeItem(KEY); } catch { /* ignore */ }
    setUntil(0);
    apply(0);
    window.dispatchEvent(new Event(EVENT));
  }, []);

  const remainingMs = until ? Math.max(0, until - now) : 0;
  return { active: until > 0, until, remainingMs, start, stop };
}
