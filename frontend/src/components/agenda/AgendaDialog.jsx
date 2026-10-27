import { createContext, useCallback, useContext, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import "@/Agenda.css";

// Nœud de la fenêtre ouverte : les popovers qui s'y ouvrent s'y rendent (sinon le verrou de
// défilement de la fenêtre bloquerait la molette dans leurs listes).
const AgendaPortalContext = createContext(null);

// Conteneur à passer à `Popover.Portal container={…}` : la fenêtre englobante, ou undefined (document.body).
export function useAgendaPortalContainer() {
  return useContext(AgendaPortalContext) || undefined;
}

// Un clic sur la barre de défilement du voile ne doit pas fermer la fenêtre.
function isScrollbarPointer(event) {
  const original = event?.detail?.originalEvent;
  const target = original?.target;
  if (!original || !target || typeof target.clientWidth !== "number") return false;
  return original.offsetX > target.clientWidth || original.offsetY > target.clientHeight;
}

function joinClasses(...values) {
  return values.filter(Boolean).join(" ");
}

// Fenêtre Radix de l'agenda : titre et description obligatoires, bouton « Fermer », piège du focus.
// `side="right"` donne le tiroir (.ag-drawer). Avec `onSubmit`, le corps et le pied forment un <form>.
export default function AgendaDialog({
  open,
  onOpenChange,
  trigger = null,
  title,
  description = null,
  descriptionHidden = false,
  eyebrow = null,
  headerExtra = null,
  side = "center",
  size = "md",
  footer = null,
  note = null,
  onSubmit = null,
  dismissible = true,
  busy = false,
  className = "",
  bodyClassName = "",
  closeLabel = "Fermer",
  onOpenAutoFocus,
  onCloseAutoFocus,
  children,
}) {
  const [contentNode, setContentNode] = useState(null);
  const isDrawer = side === "right";

  const handleOpenChange = useCallback(
    (next) => {
      if (!next && !dismissible) return;
      if (onOpenChange) onOpenChange(next);
    },
    [dismissible, onOpenChange],
  );

  const preventIfLocked = useCallback(
    (event) => {
      if (!dismissible) event.preventDefault();
    },
    [dismissible],
  );

  const handlePointerDownOutside = useCallback(
    (event) => {
      if (!dismissible || isScrollbarPointer(event)) event.preventDefault();
    },
    [dismissible],
  );

  const handleSubmit = useCallback(
    (event) => {
      event.preventDefault();
      if (onSubmit) onSubmit(event);
    },
    [onSubmit],
  );

  const body = <div className={joinClasses("ag-dialog-body", bodyClassName)}>{children}</div>;
  const footerNode = footer ? <div className="ag-dialog-footer">{footer}</div> : null;
  const hasDescription = description !== null && description !== undefined && description !== "";

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      {trigger ? <Dialog.Trigger asChild>{trigger}</Dialog.Trigger> : null}
      <Dialog.Portal>
        <Dialog.Overlay className={joinClasses("ag-dialog-overlay", isDrawer ? "ag-dialog-overlay--right" : "")}>
          <Dialog.Content
            ref={setContentNode}
            className={joinClasses(
              "ag-dialog",
              isDrawer ? "ag-drawer" : "",
              !isDrawer && size === "sm" ? "ag-dialog--sm" : "",
              !isDrawer && size === "lg" ? "ag-dialog--lg" : "",
              className,
            )}
            aria-busy={busy ? "true" : undefined}
            {...(hasDescription ? {} : { "aria-describedby": undefined })}
            onEscapeKeyDown={preventIfLocked}
            onPointerDownOutside={handlePointerDownOutside}
            onInteractOutside={preventIfLocked}
            onOpenAutoFocus={onOpenAutoFocus}
            onCloseAutoFocus={onCloseAutoFocus}
          >
            <AgendaPortalContext.Provider value={contentNode}>
              <header className="ag-dialog-header">
                <div className="ag-dialog-heading">
                  {eyebrow ? <p className="ag-eyebrow">{eyebrow}</p> : null}
                  {headerExtra ? <div className="ag-dialog-heading-extra">{headerExtra}</div> : null}
                  <Dialog.Title className="ag-dialog-title">{title}</Dialog.Title>
                  {hasDescription ? (
                    <Dialog.Description className={descriptionHidden ? "ag-sr-only" : "ag-dialog-description"}>
                      {description}
                    </Dialog.Description>
                  ) : null}
                </div>
                <Dialog.Close asChild>
                  <button
                    type="button"
                    className="ag-icon-button ag-dialog-close"
                    aria-label={closeLabel}
                    disabled={!dismissible}
                  >
                    <X size={18} aria-hidden="true" />
                  </button>
                </Dialog.Close>
              </header>
              {onSubmit ? (
                <form className="ag-dialog-form" onSubmit={handleSubmit} noValidate>
                  {body}
                  {footerNode}
                </form>
              ) : (
                <>
                  {body}
                  {footerNode}
                </>
              )}
              {note ? <p className="ag-dialog-note">{note}</p> : null}
            </AgendaPortalContext.Provider>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export { AgendaDialog };
