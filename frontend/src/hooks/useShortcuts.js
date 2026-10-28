import { useEffect } from "react";

export const OPEN_HELP_EVENT = "iris-open-shortcuts";

// Raccourcis "g puis X" (navigation) et touches simples.
export const SHORTCUTS = [
  { keys: ["g", "a"], label: "Aller à l'accueil", path: "/" },
  { keys: ["g", "c"], label: "Aller au calendrier", path: "/staff/calendrier" },
  { keys: ["g", "t"], label: "Aller aux tickets", path: "/suivis" },
  { keys: ["g", "p"], label: "Aller à la passation", path: "/staff/passation" },
  { keys: ["n"], label: "Nouvelle transmission", path: "/staff/passation?nouveau=1" },
  { keys: ["Ctrl", "K"], label: "Ouvrir la palette de commandes" },
  { keys: ["?"], label: "Afficher cette aide" },
];

function isTyping(target) {
  if (!target || !target.tagName) return false;
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable === true;
}

export default function useShortcuts(navigate) {
  useEffect(() => {
    let pending = false;
    let timer;
    const reset = () => { pending = false; clearTimeout(timer); };
    const onKey = (event) => {
      if (event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target)) return;
      if (document.querySelector("[role='dialog'][aria-modal='true']")) return;
      const key = event.key;
      if (pending) {
        const hit = SHORTCUTS.find((s) => s.keys.length === 2 && s.keys[0] === "g" && s.keys[1] === key.toLowerCase());
        reset();
        if (hit) { event.preventDefault(); navigate(hit.path); }
        return;
      }
      if (key === "g") { pending = true; timer = setTimeout(reset, 1200); return; }
      if (key === "?") { event.preventDefault(); window.dispatchEvent(new Event(OPEN_HELP_EVENT)); return; }
      if (key === "n") { event.preventDefault(); navigate("/staff/passation?nouveau=1"); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); clearTimeout(timer); };
  }, [navigate]);
}
