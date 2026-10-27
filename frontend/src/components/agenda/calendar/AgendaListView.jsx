import { Fragment, useMemo } from "react";
import { CalendarDays, ChevronRight, MapPin, Plus, Users } from "lucide-react";

import { peopleSummary } from "../HelperAvatar";
import TypeBadge from "../TypeBadge";
import { formatItemRange, groupForList, itemAriaLabel, listRowTimeLabel } from "../calendarModel";
import { formatDayShort, formatDayTitle } from "../dateUtils";
import { joinClasses } from "./calendarHelpers";
import "./agenda-calendar.css";

function ListRow({ row, today, onOpen }) {
  const { item } = row;
  const range = formatItemRange(item, today);
  const people = item.kind === "absence" ? "" : peopleSummary(item.people, 3);
  return (
    <li>
      <button
        type="button"
        className={joinClasses("ag-list-item", item.cancelled ? "is-cancelled" : "")}
        aria-label={itemAriaLabel(item)}
        onClick={() => onOpen(item)}
      >
        <span className="ag-list-time">{listRowTimeLabel(row)}</span>
        <span className="ag-list-main">
          <span className="ag-list-title-line">
            <TypeBadge type={item.type} label={item.label} size="sm" />
            <span className={joinClasses("ag-list-title", item.cancelled ? "ag-strike" : "")}>{item.title}</span>
          </span>
          {item.location || range || people || (item.kind === "absence" && item.description) ? (
            <span className="ag-list-meta">
              {item.location ? (
                <span>
                  <MapPin size={12} aria-hidden="true" />
                  {item.location}
                </span>
              ) : null}
              {range ? <span>{range}</span> : null}
              {people ? (
                <span>
                  <Users size={12} aria-hidden="true" />
                  {people}
                </span>
              ) : null}
              {item.kind === "absence" && item.description ? (
                <span className="ag-list-reason">{item.description}</span>
              ) : null}
            </span>
          ) : null}
        </span>
        <ChevronRight className="ag-list-chevron" size={16} aria-hidden="true" />
      </button>
    </li>
  );
}

function TodayMarker({ today }) {
  return (
    <div className="ag-list-today" role="separator" aria-label={`Aujourd'hui, ${formatDayTitle(today)} : rien de prévu`}>
      <span>Aujourd'hui · {formatDayShort(today)}</span>
    </div>
  );
}

// Vue Liste : « En cours », puis un groupe par jour avec intertitre collant et repère « Aujourd'hui ».
export default function AgendaListView({ range, today, items, onOpenItem, onAdd, onExtend, canExtend, extendLabel }) {
  const model = useMemo(
    () => groupForList(items, range?.start, range?.end, { today }),
    [items, range?.end, range?.start, today],
  );

  if (model.isEmpty) {
    return (
      <div className="ag-list">
        <div className="ag-empty">
          <span className="ag-empty-icon">
            <CalendarDays size={28} aria-hidden="true" />
          </span>
          <h3>Rien de prévu sur cette période.</h3>
          <p>Ajoute une absence, un événement ou une échéance pour l'équipe.</p>
          <button type="button" className="ag-button" onClick={onAdd}>
            <Plus size={16} aria-hidden="true" />
            Ajouter un élément
          </button>
        </div>
        {canExtend ? (
          <div className="ag-list-footer">
            <button type="button" className="ag-button ag-button--secondary" onClick={onExtend}>
              {extendLabel}
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="ag-list">
      {model.ongoing.length ? (
        <section className="ag-list-group" aria-label="En cours">
          <h3 className="ag-list-day ag-list-day--ongoing">En cours</h3>
          <ul className="ag-list-rows">
            {model.ongoing.map((item) => (
              <ListRow
                key={`ongoing-${item.key}`}
                row={{ key: item.key, item, dayIndex: 1, dayCount: null }}
                today={today}
                onOpen={onOpenItem}
              />
            ))}
          </ul>
        </section>
      ) : null}
      {model.groups.map((group, index) => (
        <Fragment key={group.date}>
          {model.todayMarkerIndex === index ? <TodayMarker today={today} /> : null}
          <section
            className={joinClasses("ag-list-group", group.isToday ? "is-today" : "", group.date < today ? "is-past" : "")}
            aria-label={formatDayTitle(group.date, { withYear: true })}
          >
            <h3 className="ag-list-day">
              <span>{formatDayTitle(group.date, { withYear: group.date.slice(0, 4) !== today.slice(0, 4) })}</span>
              {group.relativeLabel ? (
                <span className={joinClasses("ag-pill ag-pill--sm", group.isToday ? "ag-list-day-today" : "ag-pill--white")}>
                  <span className="ag-pill-text">{group.relativeLabel}</span>
                </span>
              ) : null}
            </h3>
            <ul className="ag-list-rows">
              {group.rows.map((row) => (
                <ListRow key={row.key} row={row} today={today} onOpen={onOpenItem} />
              ))}
            </ul>
          </section>
        </Fragment>
      ))}
      {model.todayMarkerIndex !== null && model.todayMarkerIndex >= model.groups.length ? (
        <TodayMarker today={today} />
      ) : null}
      {canExtend ? (
        <div className="ag-list-footer">
          <button type="button" className="ag-button ag-button--secondary" onClick={onExtend}>
            {extendLabel}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export { AgendaListView };
