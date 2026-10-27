import { useCallback, useEffect, useState } from "react";

const KEY = "iris.theme";
const ORDER = ["light", "dark", "system"];

function readPref() {
  try {
    const value = window.localStorage.getItem(KEY);
    return ORDER.includes(value) ? value : "system";
  } catch {
    return "system";
  }
}

function systemDark() {
  try {
    return !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

export function resolveTheme(pref) {
  return pref === "dark" || (pref === "system" && systemDark()) ? "dark" : "light";
}

let switchTimer;
function applyTheme(resolved, animate) {
  const root = document.documentElement;
  if (animate) {
    root.classList.add("theme-switching");
    clearTimeout(switchTimer);
    switchTimer = setTimeout(() => root.classList.remove("theme-switching"), 200);
  }
  root.setAttribute("data-theme", resolved);
}

export default function useTheme() {
  const [preference, setPreference] = useState(readPref);
  const [resolved, setResolved] = useState(() => resolveTheme(readPref()));

  // Synchronise plusieurs instances du hook.
  useEffect(() => {
    const sync = () => {
      const pref = readPref();
      setPreference(pref);
      setResolved(resolveTheme(pref));
    };
    window.addEventListener("iris-theme-change", sync);
    return () => window.removeEventListener("iris-theme-change", sync);
  }, []);

  // Suit le système en mode "system".
  useEffect(() => {
    if (preference !== "system" || !window.matchMedia) return undefined;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const next = resolveTheme("system");
      setResolved(next);
      applyTheme(next, true);
      window.dispatchEvent(new Event("iris-theme-change"));
    };
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, [preference]);

  const setTheme = useCallback((pref) => {
    if (!ORDER.includes(pref)) return;
    try { window.localStorage.setItem(KEY, pref); } catch { /* ignore */ }
    const next = resolveTheme(pref);
    setPreference(pref);
    setResolved(next);
    applyTheme(next, true);
    window.dispatchEvent(new Event("iris-theme-change"));
  }, []);

  const cycleTheme = useCallback(() => {
    setTheme(ORDER[(ORDER.indexOf(readPref()) + 1) % ORDER.length]);
  }, [setTheme]);

  return { preference, resolved, setTheme, cycleTheme };
}
