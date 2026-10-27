import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus } from "lucide-react";

import { MOBILE_MAX_DOTS, MONTH_MAX_LANES, WEEKDAY_LABELS } from "../agendaConstants";
import { typeClass } from "../TypeBadge";
import {
  buildMonthWeeks,
  dayCellAriaLabel,
  dayForKey,
  describeDay,
  dotsForDay,
  itemsByDay,
  layoutLanes,
} from "../calendarModel";
import { formatDayMedium, formatMonthTitle, isSameMonthIso, orderDayRange, startOfMonthIso } from "../dateUtils";
import CalendarBar from "./CalendarBar";
import { joinClasses } from "./calendarHelpers";
import "./agenda-calendar.css";

const WEEKDAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];

// Vue Mois : grille de semaines, barres multi-jours en couloirs, « +N », ajout rapide (bouton, clic, glisser).
export default function MonthView({
  anchor,
  today,
  items,
  mobile = false,
  onOpenItem,
  onOpenDay,
  onQuickAdd,
  onNavigateDate,
}) {
  const weeks = useMemo(() => buildMonthWeeks(anchor), [anchor]);
  const allDays = useMemo(() => weeks.flat(), [weeks]);
  const byDay = useMemo(() => itemsByDay(items, allDays), [items, allDays]);
  const layouts = useMemo(
    () => (mobile ? [] : weeks.map((week) => layoutLanes(week, items, MONTH_MAX_LANES))),
    [items, mobile, weeks],
  );

  const defaultFocus = isSameMonthIso(today, anchor) ? today : startOfMonthIso(anchor);
  const [focusedDay, setFocusedDay] = useState(null);
  const activeDay = focusedDay && allDays.includes(focusedDay) ? focusedDay : defaultFocus;
  const cellRefs = useRef(new Map());
  const focusRequest = useRef(null);

  useEffect(() => {
    if (!focusRequest.current) return;
    const node = cellRefs.current.get(focusRequest.current);
    if (node) {
      node.focus();
      focusRequest.current = null;
    }
  });

  // Sélection d'une plage par glisser (souris ou stylet).
  const dragRef = useRef(null);
  const handledByPointer = useRef(false);
  const [drag, setDrag] = useState(null);

  const finishDrag = useCallback(() => {
    const current = dragRef.current;
    dragRef.current = null;
    setDrag(null);
    if (!current) return;
    handledByPointer.current = true;
    const range = orderDayRange(current.start, current.current);
    if (!range) return;
    onQuickAdd({
      start: range.start,
      end: range.end,
      fromRange: range.start !== range.end,
      anchorEl: cellRefs.current.get(current.current) || null,
    });
  }, [onQuickAdd]);

  const cancelDrag = useCallback(() => {
    dragRef.current = null;
    setDrag(null);
  }, []);

  useEffect(() => {
    if (!drag) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") cancelDrag();
    };
    window.addEventListener("pointerup", finishDrag);
    window.addEventListener("pointercancel", cancelDrag);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerup", finishDrag);
      window.removeEventListener("pointercancel", cancelDrag);
      window.removeEventListener("keydown", onKey);
    };
  }, [cancelDrag, drag, finishDrag]);

  const selection = drag ? orderDayRange(drag.start, drag.current) : null;

  const handlePointerDown = (event, day) => {
    handledByPointer.current = false;
    if (mobile || event.button !== 0 || event.pointerType === "touch") return;
    if (event.target.closest("button")) return;
    event.preventDefault();
    dragRef.current = { start: day, current: day };
    setDrag({ start: day, current: day });
  };

  const handlePointerEnter = (day) => {
    if (!dragRef.current || dragRef.current.current === day) return;
    dragRef.current = { ...dragRef.current, current: day };
    setDrag({ ...dragRef.current });
  };

  const handleClick = (event, day) => {
    if (handledByPointer.current) {
      handledByPointer.current = false;
      return;
    }
    if (event.target.closest("button")) return;
    if (mobile) onOpenDay(day, event.currentTarget);
    else onQuickAdd({ start: day, end: day, fromRange: false, anchorEl: event.currentTarget });
  };

  const handleKeyDown = (event, day) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpenDay(day, event.currentTarget);
      return;
    }
    const target = dayForKey(day, event.key);
    if (!target) return;
    event.preventDefault();
    focusRequest.current = target;
    setFocusedDay(target);
    if (!allDays.includes(target) || (event.key.startsWith("Page") && !isSameMonthIso(target, anchor))) {
      onNavigateDate(target);
    }
  };

  const setCellRef = (day) => (node) => {
    if (node) cellRefs.current.set(day, node);
    else cellRefs.current.delete(day);
  };

  return (
    <div
      className={joinClasses("ag-cal-month", mobile ? "is-mobile" : "", drag ? "is-dragging" : "")}
      role="grid"
      aria-label={formatMonthTitle(anchor)}
      aria-readonly="true"
    >
      <div className="ag-cal-weekdays" role="row">
        {WEEKDAY_LABELS.map((label, index) => (
          <div key={label} role="columnheader" className="ag-cal-weekday" aria-label={WEEKDAY_NAMES[index]}>
            {mobile ? label.charAt(0) : label}
          </div>
        ))}
      </div>
      {weeks.map((week, weekIndex) => {
        const layout = layouts[weekIndex];
        const laneCount = layout ? layout.lanes.length : 0;
        const segmentsByCol = new Map();
        if (layout) {
          for (const lane of layout.lanes) {
            for (const segment of lane) {
              if (!segmentsByCol.has(segment.colStart)) segmentsByCol.set(segment.colStart, []);
              segmentsByCol.get(segment.colStart).push(segment);
            }
          }
        }
        return (
          <div key={week[0]} className="ag-cal-week" role="row" style={{ "--ag-lanes": laneCount }}>
            {week.map((day, dayIndex) => {
              const info = describeDay(day, { anchor, today });
              const dayItems = byDay.get(day) || [];
              const hidden = layout ? layout.hiddenByDay.get(day) || [] : [];
              const segments = segmentsByCol.get(dayIndex + 1) || [];
              const isActive = day === activeDay;
              const selected = selection && day >= selection.start && day <= selection.end;
              const dots = mobile ? dotsForDay(items, day, MOBILE_MAX_DOTS) : null;
              return (
                <div
                  key={day}
                  ref={setCellRef(day)}
                  role="gridcell"
                  tabIndex={isActive ? 0 : -1}
                  aria-label={dayCellAriaLabel(day, dayItems.length)}
                  aria-selected={selected ? "true" : undefined}
                  aria-current={info.isToday ? "date" : undefined}
                  className={joinClasses(
                    "ag-cal-day",
                    info.inMonth ? "" : "is-outside",
                    info.isPast ? "is-past" : "",
                    info.isWeekend ? "is-weekend" : "",
                    info.isToday ? "is-today" : "",
                    selected ? "is-selecting" : "",
                  )}
                  onFocus={(event) => {
                    if (event.target === event.currentTarget && focusedDay !== day) setFocusedDay(day);
                  }}
                  onKeyDown={(event) => handleKeyDown(event, day)}
                  onPointerDown={(event) => handlePointerDown(event, day)}
                  onPointerEnter={() => handlePointerEnter(day)}
                  onClick={(event) => handleClick(event, day)}
                >
                  <div className="ag-cal-day-head">
                    <span className="ag-cal-day-number" aria-hidden="true">
                      {info.dayNumber}
                    </span>
                    {info.isToday ? (
                      <span className="ag-cal-today-label" aria-hidden="true">
                        Aujourd'hui
                      </span>
                    ) : null}
                    {!mobile ? (
                      <button
                        type="button"
                        className="ag-cal-day-add"
                        aria-label={`Ajouter le ${formatDayMedium(day)}`}
                        tabIndex={isActive ? 0 : -1}
                        onClick={(event) => {
                          event.stopPropagation();
                          onQuickAdd({ start: day, end: day, fromRange: false, anchorEl: event.currentTarget });
                        }}
                      >
                        <Plus size={14} aria-hidden="true" />
                      </button>
                    ) : null}
                  </div>
                  {mobile ? (
                    dots.total ? (
                      <div className="ag-cal-dots" aria-hidden="true">
                        {dots.dots.map((dot) => (
                          <span
                            key={dot.key}
                            className={joinClasses("ag-cal-dot", typeClass(dot.type), dot.cancelled ? "is-cancelled" : "")}
                          />
                        ))}
                        {dots.extra ? <span className="ag-cal-dot-more">+</span> : null}
                      </div>
                    ) : null
                  ) : (
                    <>
                      <div className="ag-cal-lanes">
                        {segments.map((segment) => (
                          <CalendarBar
                            key={segment.key}
                            segment={segment}
                            today={today}
                            onOpen={onOpenItem}
                            className="ag-cal-bar--month"
                            style={{ "--ag-span": segment.colSpan, "--ag-lane": segment.lane }}
                          />
                        ))}
                      </div>
                      {hidden.length ? (
                        <button
                          type="button"
                          className="ag-cal-more"
                          aria-label={`${hidden.length} autre${hidden.length > 1 ? "s" : ""} élément${
                            hidden.length > 1 ? "s" : ""
                          } le ${formatDayMedium(day)}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenDay(day, event.currentTarget);
                          }}
                        >
                          +{hidden.length}
                        </button>
                      ) : null}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

export { MonthView };
