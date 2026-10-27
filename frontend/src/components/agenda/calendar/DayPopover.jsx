import { useMemo } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Popover from "@radix-ui/react-popover";
import { ChevronRight, Plus, X } from "lucide-react";

import "@/Agenda.css";

import { TypeIcon, typeClass } from "../TypeBadge";
import { formatItemRange, itemAriaLabel, itemsOnDay } from "../calendarModel";
import { formatDayTitle, formatTimeRange } from "../dateUtils";
import { joinClasses, restoreFocus, useVirtualAnchor } from "./calendarHelpers";
import "./agenda-calendar.css";

function DayContent({ day, items, today, onOpenItem, onAddDay, onClose, TitleTag }) {
  const dayItems = useMemo(() => itemsOnDay(items, day), [day, items]);
  const title = formatDayTitle(day, { withYear: Boolean(today) && day.slice(0, 4) !== today.slice(0, 4) });
  return (
    <>
      <div className="ag-daypop-head">
        <TitleTag className="ag-daypop-title">{title}</TitleTag>
        <button type="button" className="ag-icon-button ag-icon-button--small" aria-label="Fermer" onClick={onClose}>
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      {dayItems.length ? (
        <ul className="ag-daypop-list">
          {dayItems.map((item) => {
            const range = formatItemRange(item, today);
            return (
              <li key={item.key}>
                <button
                  type="button"
                  className={joinClasses("ag-daypop-item", typeClass(item.type), item.cancelled ? "is-cancelled" : "")}
                  aria-label={itemAriaLabel(item)}
                  onClick={() => onOpenItem(item)}
                >
                  <span className="ag-daypop-icon">
                    <TypeIcon type={item.type} size={14} />
                  </span>
                  <span className="ag-daypop-text">
                    <strong className={item.cancelled ? "ag-strike" : undefined}>{item.title}</strong>
                    <small>
                      {[item.allDay ? "Journée" : formatTimeRange(item.startTime, item.endTime), range, item.label]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                  </span>
                  <ChevronRight size={15} aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="ag-daypop-empty">Rien de prévu ce jour-là.</p>
      )}
      <div className="ag-daypop-foot">
        <button type="button" className="ag-button ag-button--small" onClick={() => onAddDay(day)}>
          <Plus size={14} aria-hidden="true" />
          Ajouter ce jour
        </button>
      </div>
    </>
  );
}

// Liste des éléments d'un jour (« +N », Entrée sur une cellule, toucher une cellule sur mobile).
// `sheet` : panneau plein largeur en bas de l'écran (mobile) au lieu d'un popover ancré.
export default function DayPopover({ open, onOpenChange, day, anchorEl, items, today, sheet = false, onOpenItem, onAddDay }) {
  const virtualRef = useVirtualAnchor(anchorEl);
  const close = () => onOpenChange(false);

  if (!day) return null;

  if (sheet) {
    return (
      <Dialog.Root open={open} onOpenChange={onOpenChange}>
        <Dialog.Portal>
          <Dialog.Overlay className="ag-dialog-overlay ag-daypop-overlay" />
          <Dialog.Content
            className="ag-popover ag-daypop ag-daypop--sheet"
            aria-describedby={undefined}
            onCloseAutoFocus={(event) => restoreFocus(event, anchorEl)}
          >
            <DayContent
              day={day}
              items={items}
              today={today}
              onOpenItem={onOpenItem}
              onAddDay={onAddDay}
              onClose={close}
              TitleTag={Dialog.Title}
            />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    );
  }

  return (
    <Popover.Root open={open} onOpenChange={onOpenChange}>
      <Popover.Anchor virtualRef={virtualRef} />
      <Popover.Portal>
        <Popover.Content
          className="ag-popover ag-daypop"
          side="bottom"
          align="start"
          sideOffset={6}
          collisionPadding={12}
          aria-label={`Éléments du ${formatDayTitle(day)}`}
          onCloseAutoFocus={(event) => restoreFocus(event, anchorEl)}
        >
          <DayContent
            day={day}
            items={items}
            today={today}
            onOpenItem={onOpenItem}
            onAddDay={onAddDay}
            onClose={close}
            TitleTag="h2"
          />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export { DayPopover };
