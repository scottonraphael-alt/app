import { useState } from "react";
import { Link } from "react-router-dom";
import * as Popover from "@radix-ui/react-popover";
import { Ban, CalendarSearch, ClipboardCopy, Ellipsis, List, Pencil, RotateCcw, Trash2 } from "lucide-react";

import "./meeting.css";

// Menu « … » de l'en-tête. Les entrées réservées aux responsables n'existent pas pour les autres.
export default function MeetingMenu({
  meetingId,
  meetingDate,
  isResponsable,
  locked,
  cancelled,
  onEdit,
  onCopyMarkdown,
  onCancel,
  onRestore,
  onDelete,
}) {
  const [open, setOpen] = useState(false);
  const run = (callback) => () => {
    setOpen(false);
    callback?.();
  };
  const calendarUrl = `/staff/calendrier?date=${encodeURIComponent(meetingDate || "")}&element=${encodeURIComponent(`meeting:${meetingId}`)}`;

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button type="button" className="ag-icon-button" aria-label="Autres actions" aria-haspopup="menu">
          <Ellipsis size={20} aria-hidden="true" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="ag-popover ag-popover--menu" align="end" sideOffset={6}>
          <div className="ag-menu" role="menu">
            <Link to="/staff/meetings" role="menuitem" className="ag-menu-item" onClick={() => setOpen(false)}>
              <List size={16} aria-hidden="true" />
              Toutes les réunions
            </Link>
            {isResponsable ? (
              <button type="button" role="menuitem" className="ag-menu-item" onClick={run(onEdit)} disabled={locked}>
                <Pencil size={16} aria-hidden="true" />
                Modifier les informations
              </button>
            ) : null}
            {meetingDate ? (
              <Link to={calendarUrl} role="menuitem" className="ag-menu-item" onClick={() => setOpen(false)}>
                <CalendarSearch size={16} aria-hidden="true" />
                Voir dans le calendrier
              </Link>
            ) : null}
            <button type="button" role="menuitem" className="ag-menu-item" onClick={run(onCopyMarkdown)}>
              <ClipboardCopy size={16} aria-hidden="true" />
              Copier en Markdown
            </button>
            {isResponsable ? (
              <>
                <div className="ag-menu-separator" />
                {cancelled ? (
                  <button type="button" role="menuitem" className="ag-menu-item" onClick={run(onRestore)} disabled={locked}>
                    <RotateCcw size={16} aria-hidden="true" />
                    Rétablir la réunion
                  </button>
                ) : (
                  <button type="button" role="menuitem" className="ag-menu-item" onClick={run(onCancel)} disabled={locked}>
                    <Ban size={16} aria-hidden="true" />
                    Annuler la réunion
                  </button>
                )}
                <button
                  type="button"
                  role="menuitem"
                  className="ag-menu-item ag-menu-item--danger"
                  onClick={run(onDelete)}
                  disabled={locked}
                  title={locked ? "Déverrouillez la réunion pour la supprimer." : undefined}
                >
                  <Trash2 size={16} aria-hidden="true" />
                  Supprimer
                </button>
              </>
            ) : null}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export { MeetingMenu };
