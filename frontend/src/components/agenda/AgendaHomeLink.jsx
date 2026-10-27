import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import "@/Agenda.css";

// Lien « Accueil → » : toujours le premier élément de .ag-header-actions (copie de .tl-home / .tar-home).
export default function AgendaHomeLink({ compact = false, className = "" }) {
  const classes = ["ag-home", compact ? "ag-home--compact" : "", className].filter(Boolean).join(" ");
  return (
    <Link to="/" className={classes}>
      Accueil
      <ArrowRight size={compact ? 16 : 18} aria-hidden="true" />
    </Link>
  );
}

export { AgendaHomeLink };
