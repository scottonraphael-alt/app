import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { OPEN_HELP_EVENT, SHORTCUTS } from "../../hooks/useShortcuts";
import "./ux.css";

export default function ShortcutsHelp() {
  const [open, setOpen] = useState(false);
  const closeRef = useRef(null);
  const returnFocus = useRef(null);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener(OPEN_HELP_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_HELP_EVENT, onOpen);
  }, []);

  useEffect(() => {
    if (open) {
      returnFocus.current = document.activeElement;
      closeRef.current?.focus();
    } else if (returnFocus.current?.focus) returnFocus.current.focus();
  }, [open]);

  if (!open) return null;
  const close = () => setOpen(false);
  return (
    <div className="ux-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div
        className="ux-dialog" role="dialog" aria-modal="true" aria-labelledby="ux-help-title"
        onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); close(); } if (e.key === "Tab") { e.preventDefault(); closeRef.current?.focus(); } }}
      >
        <div className="ux-dialog-head">
          <h2 id="ux-help-title">Raccourcis clavier</h2>
          <button type="button" ref={closeRef} className="ux-icon-btn" onClick={close} aria-label="Fermer"><X size={16} aria-hidden="true" /></button>
        </div>
        <ul className="ux-shortcuts">
          {SHORTCUTS.map((s) => (
            <li key={s.label}>
              <span>{s.label}</span>
              <span className="ux-keys">
                {s.keys.map((k, i) => (<span key={k + i}>{i > 0 && s.keys[0] === "g" && <em> puis </em>}{i > 0 && s.keys[0] !== "g" && <em> + </em>}<kbd>{k}</kbd></span>))}
              </span>
            </li>
          ))}
        </ul>
        <p className="ux-note">Les raccourcis sont désactivés pendant la saisie de texte.</p>
      </div>
    </div>
  );
}
