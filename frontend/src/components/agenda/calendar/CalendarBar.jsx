import { ArrowRight, ChevronLeft, ChevronRight } from "lucide-react";

import HelperAvatar from "../HelperAvatar";
import { TypeIcon, typeClass } from "../TypeBadge";
import { barTimeLabel, itemAriaLabel } from "../calendarModel";
import { joinClasses } from "./calendarHelpers";
import { dragSource } from "./dragDrop";
import "./agenda-calendar.css";

// Barre d'un élément dans la vue Mois ou dans la bande « Journée » de la vue Semaine.
// `segment` vient de layoutLanes : { item, lane, colStart, colSpan, continuesBefore, continuesAfter, tailOffset }.
export default function CalendarBar({ segment, onOpen, today, className = "", style, tabIndex, fromDay = null, dragEnabled = false }) {
  const { item, colSpan, continuesBefore, continuesAfter, tailOffset } = segment;
  const time = barTimeLabel(item);
  const hasTail = tailOffset !== null && tailOffset !== undefined;
  const tailStart = hasTail ? `${(tailOffset / colSpan) * 100}%` : null;
  const label = itemAriaLabel(item);
  const person = item.kind === "absence" ? item.people[0] : null;

  return (
    <button
      type="button"
      className={joinClasses(
        "ag-cal-bar",
        typeClass(item.type),
        continuesBefore ? "is-continued-before" : "",
        continuesAfter ? "is-continued-after" : "",
        hasTail ? "has-tail" : "",
        hasTail && tailOffset === 0 ? "is-all-tail" : "",
        item.cancelled ? "is-cancelled" : "",
        today && item.displayEnd < today ? "is-past" : "",
        item.mine ? "is-mine" : "",
        className,
      )}
      style={{ ...style, ...(tailStart ? { "--ag-tail-start": tailStart } : null) }}
      aria-label={label}
      title={label}
      tabIndex={tabIndex}
      {...dragSource(item, fromDay, dragEnabled && Boolean(fromDay))}
      onClick={(event) => {
        event.stopPropagation();
        onOpen(item);
      }}
      onPointerDown={(event) => event.stopPropagation()}
    >
      {continuesBefore ? <ChevronLeft className="ag-cal-bar-chevron" size={12} aria-hidden="true" /> : null}
      {person ? (
        <HelperAvatar person={person} size={18} decorative className="ag-cal-bar-avatar" />
      ) : (
        <TypeIcon type={item.type} size={12} className="ag-cal-bar-icon" />
      )}
      {time ? <span className="ag-cal-bar-time">{time}</span> : null}
      <span className="ag-cal-bar-title">{item.title}</span>
      {hasTail ? <ArrowRight className="ag-cal-bar-open" size={12} aria-hidden="true" /> : null}
      {continuesAfter && !hasTail ? <ChevronRight className="ag-cal-bar-chevron" size={12} aria-hidden="true" /> : null}
    </button>
  );
}

export { CalendarBar };
