import { useMemo } from "react";
import { MapPin, Plus } from "lucide-react";

import { WEEK_MAX_LANES } from "../agendaConstants";
import { TypeIcon, typeClass } from "../TypeBadge";
import {
  buildWeek,
  describeDay,
  isMultiDay,
  itemAriaLabel,
  itemsOnDay,
  layoutLanes,
  splitWeekItems,
  timedItemsByDay,
} from "../calendarModel";
import { formatDayMedium, formatDayTitle, formatTimeRange } from "../dateUtils";
import CalendarBar from "./CalendarBar";
import { joinClasses } from "./calendarHelpers";
import "./agenda-calendar.css";

function WeekItemCard({ item, today, onOpen }) {
  const label = itemAriaLabel(item);
  return (
    <button
      type="button"
      className={joinClasses(
        "ag-week-item",
        typeClass(item.type),
        item.cancelled ? "is-cancelled" : "",
        today && item.displayEnd < today ? "is-past" : "",
      )}
      aria-label={label}
      title={label}
      onClick={() => onOpen(item)}
    >
      <strong className="ag-week-item-time">{formatTimeRange(item.startTime, item.endTime) || "Journée"}</strong>
      <span className="ag-week-item-title">
        <TypeIcon type={item.type} size={12} />
        {item.title}
      </span>
      {item.location ? (
        <span className="ag-week-item-meta">
          <MapPin size={12} aria-hidden="true" />
          {item.location}
        </span>
      ) : null}
    </button>
  );
}

function DayHeader({ info, onQuickAdd, stacked }) {
  return (
    <div className={joinClasses("ag-week-head", info.isToday ? "is-today" : "")}>
      <span className="ag-week-head-label">
        {stacked ? (
          formatDayTitle(info.iso)
        ) : (
          <>
            <span className="ag-week-head-weekday">{info.weekday}</span>
            <span className="ag-week-head-number">{info.dayNumber}</span>
          </>
        )}
        {info.isToday ? <span className="ag-cal-today-label">Aujourd'hui</span> : null}
      </span>
      <button
        type="button"
        className="ag-icon-button ag-icon-button--small ag-week-add"
        aria-label={`Ajouter le ${formatDayMedium(info.iso)}`}
        onClick={(event) => onQuickAdd({ start: info.iso, end: info.iso, fromRange: false, anchorEl: event.currentTarget })}
      >
        <Plus size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

// Vue Semaine : en-tête des jours, bande « Journée » (barres multi-jours) puis cartes des éléments horaires.
// Sous 900px (`stacked`), les jours sont empilés.
export default function WeekView({ anchor, today, items, stacked = false, onOpenItem, onOpenDay, onQuickAdd }) {
  const days = useMemo(() => buildWeek(anchor), [anchor]);
  const { bars } = useMemo(() => splitWeekItems(items), [items]);
  const layout = useMemo(() => layoutLanes(days, bars, WEEK_MAX_LANES), [bars, days]);
  const timedByDay = useMemo(() => timedItemsByDay(items, days), [days, items]);
  const infos = days.map((day) => describeDay(day, { today }));

  if (stacked) {
    return (
      <div className="ag-week ag-week--stacked">
        {infos.map((info) => {
          const allDay = itemsOnDay(bars, info.iso);
          const timed = timedByDay.get(info.iso) || [];
          return (
            <section
              key={info.iso}
              className={joinClasses("ag-week-day", info.isToday ? "is-today" : "", info.isPast ? "is-past" : "")}
              aria-label={formatDayTitle(info.iso, { withYear: true })}
            >
              <DayHeader info={info} onQuickAdd={onQuickAdd} stacked />
              {allDay.length || timed.length ? (
                <div className="ag-week-stack">
                  {allDay.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      className={joinClasses(
                        "ag-week-allday",
                        typeClass(item.type),
                        item.cancelled ? "is-cancelled" : "",
                        isMultiDay(item) ? "is-multi" : "",
                      )}
                      aria-label={itemAriaLabel(item)}
                      onClick={() => onOpenItem(item)}
                    >
                      <TypeIcon type={item.type} size={12} />
                      <span>{item.title}</span>
                    </button>
                  ))}
                  {timed.map((item) => (
                    <WeekItemCard key={item.key} item={item} today={today} onOpen={onOpenItem} />
                  ))}
                </div>
              ) : (
                <p className="ag-week-empty">Rien de prévu.</p>
              )}
            </section>
          );
        })}
      </div>
    );
  }

  const laneCount = Math.max(1, layout.lanes.length);
  return (
    <div className="ag-week" style={{ "--ag-lanes": laneCount }}>
      <div className="ag-week-grid ag-week-heads">
        {infos.map((info) => (
          <DayHeader key={info.iso} info={info} onQuickAdd={onQuickAdd} />
        ))}
      </div>
      <div className="ag-week-band">
        <span className="ag-week-band-label">Journée</span>
        <div className="ag-week-grid ag-week-band-bg" aria-hidden="true">
          {infos.map((info) => (
            <span key={info.iso} className={joinClasses("ag-week-band-cell", info.isToday ? "is-today" : "")} />
          ))}
        </div>
        <div className="ag-week-grid ag-week-band-grid">
          {layout.lanes.map((lane) =>
            lane.map((segment) => (
              <CalendarBar
                key={segment.key}
                segment={segment}
                today={today}
                onOpen={onOpenItem}
                className="ag-cal-bar--week"
                style={{ gridColumn: `${segment.colStart} / span ${segment.colSpan}`, gridRow: segment.lane + 1 }}
              />
            )),
          )}
          {infos.map((info, index) => {
            const hidden = layout.hiddenByDay.get(info.iso) || [];
            if (!hidden.length) return null;
            return (
              <button
                key={`more-${info.iso}`}
                type="button"
                className="ag-cal-more ag-week-more"
                style={{ gridColumn: index + 1, gridRow: laneCount + 1 }}
                aria-label={`${hidden.length} autre${hidden.length > 1 ? "s" : ""} élément${
                  hidden.length > 1 ? "s" : ""
                } le ${formatDayMedium(info.iso)}`}
                onClick={(event) => onOpenDay(info.iso, event.currentTarget)}
              >
                +{hidden.length}
              </button>
            );
          })}
        </div>
      </div>
      <div className="ag-week-grid ag-week-columns">
        {infos.map((info) => {
          const timed = timedByDay.get(info.iso) || [];
          return (
            <div
              key={info.iso}
              className={joinClasses("ag-week-column", info.isToday ? "is-today" : "", info.isPast ? "is-past" : "")}
              aria-label={formatDayTitle(info.iso)}
              role="group"
            >
              {timed.map((item) => (
                <WeekItemCard key={item.key} item={item} today={today} onOpen={onOpenItem} />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { WeekView };
