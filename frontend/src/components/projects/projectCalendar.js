export function calendarItems(projects, tasks, {
  includeClosed = false,
  projectId = '',
  mine = false,
  helperId
} = {}) {
  const allowed = projects.filter(p => (includeClosed || p.status === 'en_cours') && (!projectId || p.id === projectId));
  const ids = new Set(allowed.map(p => p.id));
  return [...(!mine ? allowed.flatMap(p => [{
    id: `start-${p.id}`,
    project_id: p.id,
    date: p.start_date,
    title: p.title,
    kind: 'project',
    label: 'Début du projet'
  }, ...(p.end_date ? [{
    id: `end-${p.id}`,
    project_id: p.id,
    date: p.end_date,
    title: p.title,
    kind: 'end',
    label: 'Fin prévue'
  }] : [])]) : []), ...tasks.filter(t => ids.has(t.project_id) && t.due_date && (includeClosed || t.status !== 'valide') && (!mine || t.assignee?.id === helperId)).map(t => ({
    ...t,
    date: t.due_date,
    kind: 'task',
    label: t.status === 'valide' ? 'Tâche validée' : 'Échéance de tâche'
  }))].sort((a, b) => a.date.localeCompare(b.date) || a.title.localeCompare(b.title, 'fr'));
}
const icsEscape = value => String(value || '').replace(/\\/g, '\\\\').replace(/\r?\n/g, '\\n').replace(/;/g, '\\;').replace(/,/g, '\\,');
export function calendarExport(items, origin, now = new Date()) {
  const stamp = now.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//IRIS//Projets//FR', 'CALSCALE:GREGORIAN', ...items.flatMap(item => {
    const next = new Date(`${item.date}T12:00:00Z`);
    next.setUTCDate(next.getUTCDate() + 1);
    const path = `/animateur/projects/${item.project_id}${item.kind === 'task' ? `?task=${encodeURIComponent(item.id)}` : ''}`;
    return ['BEGIN:VEVENT', `UID:${icsEscape(item.id)}@iris`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${item.date.replace(/-/g, '')}`, `DTEND;VALUE=DATE:${next.toISOString().slice(0, 10).replace(/-/g, '')}`, `SUMMARY:${icsEscape(item.title)}`, `DESCRIPTION:${icsEscape(item.label)}`, `URL:${origin}${path}`, 'END:VEVENT'];
  }), 'END:VCALENDAR', ''];
  const fold = line => {
    let result = '',
      bytes = 0;
    for (const char of line) {
      const point = char.codePointAt(0);
      const size = point < 128 ? 1 : point < 2048 ? 2 : point < 65536 ? 3 : 4;
      if (bytes + size > 75) {
        result += '\r\n ';
        bytes = 1;
      }
      result += char;
      bytes += size;
    }
    return result;
  };
  return lines.map(fold).join('\r\n');
}
