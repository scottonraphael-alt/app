export function greetingFor(date = new Date()) {
  const hour = date.getHours();
  if (hour < 5) return "Bonne nuit, prends soin de toi";
  if (hour < 12) return "Bonjour";
  if (hour < 18) return "Bon après-midi";
  if (hour < 22) return "Bonsoir";
  return "Bonne nuit, prends soin de toi";
}

function plural(n, one, many) {
  return `${n} ${n > 1 ? many : one}`;
}

/** Résumé d'une phrase à partir des compteurs de la journée. */
export function summaryFor({ meetings = 0, deadlines = 0, tasks = 0, handoffs = 0 } = {}) {
  const parts = [];
  if (meetings) parts.push(plural(meetings, "réunion", "réunions"));
  if (deadlines) parts.push(plural(deadlines, "échéance", "échéances"));
  if (tasks) parts.push(plural(tasks, "tâche à rendre", "tâches à rendre"));
  if (handoffs) parts.push(plural(handoffs, "transmission à lire", "transmissions à lire"));
  if (!parts.length) return "Rien de prévu aujourd’hui pour toi : une journée tranquille.";
  const last = parts.pop();
  return `Aujourd’hui : ${parts.length ? `${parts.join(", ")} et ${last}` : last}.`;
}

export function minutesAgo(iso, now = Date.now()) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((now - t) / 60000));
}

export function agoLabel(iso, now = Date.now()) {
  const m = minutesAgo(iso, now);
  if (m === null) return "";
  if (m < 2) return "à l’instant";
  return `il y a ${m} min`;
}
