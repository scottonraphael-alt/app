import { AtSign, BellOff, BellRing } from "lucide-react";

import "@/Agenda.css";

import {
  OFFSET_KEYS,
  OFFSET_LABELS,
  reminderScheduleSummary,
  reminderStatusMeta,
  reminderStatusText,
} from "./agendaConstants";
import { parisNow, parseInstant } from "./dateUtils";

function scheduleOf(reminders) {
  const list = Array.isArray(reminders?.schedule) ? reminders.schedule.filter((item) => item && item.offset) : [];
  return [...list].sort((a, b) => {
    const left = parseInstant(a.due_at);
    const right = parseInstant(b.due_at);
    if (left !== null && right !== null && left !== right) return left - right;
    return OFFSET_KEYS.indexOf(a.offset) - OFFSET_KEYS.indexOf(b.offset);
  });
}

// Résumé d'une ligne : « Rappel J-2 envoyé · J-1 demain à 20 h 30 » (« aujourd'hui » / « demain » à Paris).
export function reminderSummary(reminders, nowMs = Date.now()) {
  if (!reminders || !reminders.enabled) return "Rappels Discord désactivés";
  const schedule = scheduleOf(reminders);
  const text = reminderScheduleSummary(schedule, { today: parisNow(nowMs).date });
  if (text) return text;
  return schedule.length ? "Aucun rappel à venir" : "Rappels en préparation";
}

function StatusIcon({ item }) {
  const meta = reminderStatusMeta(item);
  const Icon = meta.icon;
  return <Icon size={15} aria-hidden="true" className={item.status === "sending" ? "ag-spin" : undefined} />;
}

// État des rappels d'un élément (ReminderInfo) : liste détaillée, ou une ligne avec variant="short".
export default function ReminderSchedule({
  reminders,
  variant = "full",
  emptyLabel = "Aucun rappel Discord pour cet élément.",
  showPing = true,
  className = "",
}) {
  const classes = (base) => [base, className].filter(Boolean).join(" ");

  if (variant === "short") {
    const enabled = Boolean(reminders?.enabled);
    const Icon = enabled ? BellRing : BellOff;
    return (
      <p className={classes("ag-reminder-short")}>
        <Icon size={15} aria-hidden="true" />
        <span>{reminderSummary(reminders)}</span>
      </p>
    );
  }

  if (!reminders || !reminders.enabled) {
    return (
      <p className={classes("ag-reminder-empty")}>
        <BellOff size={15} aria-hidden="true" />
        {emptyLabel}
      </p>
    );
  }

  const schedule = scheduleOf(reminders);
  return (
    <div className={classes("ag-reminders")}>
      {schedule.length ? (
        <ul className="ag-reminder-list" aria-label="Rappels Discord">
          {schedule.map((item) => (
            <li key={`${item.offset}-${item.due_at || ""}`} className={`ag-reminder-item is-${item.status || "pending"}`}>
              <StatusIcon item={item} />
              <span className="ag-reminder-offset">{item.offset}</span>
              <span className="ag-reminder-copy">
                <span>{reminderStatusText(item)}</span>
                <small>{OFFSET_LABELS[item.offset] || ""}</small>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="ag-reminder-empty">
          <BellRing size={15} aria-hidden="true" />
          Rappels en préparation : ils apparaîtront après l'enregistrement.
        </p>
      )}
      {showPing && reminders.ping_role ? (
        <p className="ag-reminder-meta">
          <AtSign size={13} aria-hidden="true" />
          Avec mention du rôle
        </p>
      ) : null}
    </div>
  );
}

export { ReminderSchedule };
