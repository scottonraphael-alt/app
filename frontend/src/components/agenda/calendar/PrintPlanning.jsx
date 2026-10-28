import { useMemo } from "react";
import { createPortal } from "react-dom";

import { formatItemRange, groupForList, listRowTimeLabel } from "../calendarModel";
import { RECURRENCE_LABELS } from "../calendarModel";
import { formatDayTitle, endOfMonthIso, startOfMonthIso } from "../dateUtils";
import { peopleSummary } from "../HelperAvatar";
import "./agenda-print.css";

// Planning imprimable (vue liste du mois, de la semaine ou de la période affichée). Invisible à l'écran : la feuille
// @media print de agenda-print.css masque le reste de la page. Enregistrer en PDF = choisir cette destination.
export default function PrintPlanning({ view, anchor, range, today, items, title }) {
  const bounds = useMemo(() => {
    if (view === "mois") return { start: startOfMonthIso(anchor), end: endOfMonthIso(anchor) };
    return range ? { start: range.start, end: range.end } : null;
  }, [anchor, range, view]);
  const model = useMemo(
    () => (bounds ? groupForList(items, bounds.start, bounds.end, { today, repeatMultiDay: false }) : null),
    [bounds, items, today],
  );
  if (!model) return null;
  const rows = [
    ...model.ongoing.map((item) => ({ key: `o-${item.key}`, date: "En cours", row: { item, dayIndex: 1, dayCount: null } })),
    ...model.groups.flatMap((group) =>
      group.rows.map((row) => ({ key: row.key, date: formatDayTitle(group.date, { withYear: true }), row })),
    ),
  ];
  if (typeof document === "undefined") return null;
  // Rendu dans <body> : aucun ancêtre de la page ne peut le rogner ni le décaler à l'impression.
  return createPortal(
    <section className="ag-print-planning" aria-hidden="true" data-testid="print-planning">
      <h1>Planning · {title}</h1>
      <p className="ag-print-sub">L'Oasis · équipe staff · imprimé le {formatDayTitle(today, { withYear: true })}</p>
      {rows.length ? (
        <table>
          <thead>
            <tr>
              <th>Jour</th>
              <th>Heure</th>
              <th>Type</th>
              <th>Intitulé</th>
              <th>Lieu / personnes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, date, row }) => {
              const { item } = row;
              const range2 = formatItemRange(item, today);
              const people = item.kind === "absence" ? "" : peopleSummary(item.people, 4);
              return (
                <tr key={key}>
                  <td>{date}</td>
                  <td>{listRowTimeLabel(row)}</td>
                  <td>{item.label}</td>
                  <td>
                    <strong className={item.cancelled ? "is-cancelled" : ""}>{item.title}</strong>
                    {item.cancelled ? " (annulée)" : ""}
                    {range2 ? <small> · {range2}</small> : null}
                    {item.recurrence ? <small> · {RECURRENCE_LABELS[item.recurrence.freq]}</small> : null}
                  </td>
                  <td>{[item.location, people].filter(Boolean).join(" · ")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p>Rien de prévu sur cette période.</p>
      )}
    </section>,
    document.body,
  );
}

export { PrintPlanning };
