import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Plus } from "lucide-react";

import "@/Agenda.css";

import { ENTRY_TYPE_KEYS, typeMeta } from "../agendaConstants";
import { joinClasses } from "./calendarHelpers";
import "./agenda-calendar.css";

// Bouton « Ajouter » et son menu : Absence, Réunion (responsables), puis les types d'entrées.
// `floating` : bouton rond fixé en bas à droite (mobile).
export default function AddMenu({ canManage = false, onSelect, floating = false, className = "" }) {
  const [open, setOpen] = useState(false);
  const types = ["absence", ...(canManage ? ["reunion"] : []), ...ENTRY_TYPE_KEYS];

  const choose = (type) => {
    setOpen(false);
    onSelect(type);
  };

  const moveFocus = (event) => {
    const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
    if (!keys.includes(event.key)) return;
    const buttons = Array.from(event.currentTarget.querySelectorAll('[role="menuitem"]'));
    if (!buttons.length) return;
    event.preventDefault();
    const index = buttons.indexOf(document.activeElement);
    let next = 0;
    if (event.key === "ArrowDown") next = index < 0 ? 0 : (index + 1) % buttons.length;
    if (event.key === "ArrowUp") next = index <= 0 ? buttons.length - 1 : index - 1;
    if (event.key === "End") next = buttons.length - 1;
    buttons[next].focus();
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        {floating ? (
          <button
            type="button"
            className={joinClasses("ag-button ag-cal-fab", className)}
            aria-label="Ajouter"
            aria-haspopup="menu"
          >
            <Plus size={24} aria-hidden="true" />
          </button>
        ) : (
          <button type="button" className={joinClasses("ag-button", className)} aria-haspopup="menu">
            <Plus size={16} aria-hidden="true" />
            Ajouter
          </button>
        )}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="ag-popover ag-popover--menu"
          align="end"
          side={floating ? "top" : "bottom"}
          sideOffset={6}
          collisionPadding={12}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            const first = event.currentTarget?.querySelector?.('[role="menuitem"]');
            if (first) first.focus();
          }}
        >
          <div className="ag-menu" role="menu" aria-label="Ajouter au calendrier" onKeyDown={moveFocus}>
            {types.map((type, index) => {
              const meta = typeMeta(type);
              const Icon = meta.icon;
              return (
                <div key={type} role="none">
                  {index === 1 && canManage ? <div className="ag-menu-separator" role="separator" /> : null}
                  {index === 2 && canManage ? <div className="ag-menu-separator" role="separator" /> : null}
                  {index === 1 && !canManage ? <div className="ag-menu-separator" role="separator" /> : null}
                  <button type="button" role="menuitem" className="ag-menu-item" onClick={() => choose(type)}>
                    <Icon size={16} aria-hidden="true" />
                    {meta.label}
                  </button>
                </div>
              );
            })}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export { AddMenu };
