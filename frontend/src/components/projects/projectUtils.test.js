import { dateLabel, filterProjects, isLate, progress, taskCounts } from './projectUtils';
import { calendarExport, calendarItems } from './projectCalendar';
const projects = [{
  id: 'a',
  title: 'Soirée jeux',
  description: 'Vocal',
  tags: ['Jeux'],
  members: [{
    id: 'm',
    display_name: 'Alex'
  }],
  status: 'en_cours',
  priority: 'haute',
  start_date: '2026-10-27',
  end_date: '2026-11-01',
  updated_at: '2026-10-26'
}, {
  id: 'b',
  title: 'Cinéma',
  members: [],
  status: 'archive',
  start_date: '2026-09-01',
  updated_at: '2026-10-27'
}];
const tasks = [{
  id: 't',
  project_id: 'a',
  title: 'Préparer',
  due_date: '2026-10-31',
  status: 'a_faire',
  assignee: {
    id: 'm'
  }
}, {
  id: 'done',
  project_id: 'a',
  title: 'Fait',
  due_date: '2026-10-30',
  status: 'valide',
  assignee: {
    id: 'm'
  }
}, {
  id: 'old',
  project_id: 'b',
  title: 'Ancien',
  due_date: '2026-10-30',
  status: 'a_faire'
}];
it('combine les filtres sans modifier les données', () => {
  expect(filterProjects(projects, {
    query: 'alex',
    mine: true,
    helperId: 'm'
  }).map(p => p.id)).toEqual(['a']);
  expect(filterProjects(projects, {
    status: 'archive'
  }).map(p => p.id)).toEqual(['b']);
  expect(filterProjects(projects, {
    priority: 'basse'
  })).toEqual([]);
  expect(projects[0].id).toBe('a');
});
it('compte uniquement les validations comme terminées', () => {
  expect(progress(taskCounts([...tasks, {
    status: 'rendu'
  }]))).toEqual({
    total: 4,
    done: 1,
    percent: 25
  });
  expect(progress()).toEqual({
    total: 0,
    done: 0,
    percent: 0
  });
});
it('respecte le jour limite et exclut les rendus des retards', () => {
  expect(isLate(tasks[0], '2026-11-01')).toBe(true);
  expect(isLate(tasks[0], '2026-10-31')).toBe(false);
  expect(isLate({
    ...tasks[0],
    status: 'rendu'
  }, '2026-11-01')).toBe(false);
  expect(isLate({
    status: 'a_faire'
  }, '2026-11-01')).toBe(false);
});
it('tolère une échéance absente ou invalide', () => {
  expect(dateLabel(null)).toBe('Sans échéance');
  expect(dateLabel('bad')).toBe('Date inconnue');
});
it('masque les archives et tâches validées par défaut', () => {
  expect(calendarItems(projects, tasks).map(e => e.id)).toEqual(['start-a', 't', 'end-a']);
  expect(calendarItems(projects, tasks, {
    mine: true,
    helperId: 'm'
  }).map(e => e.id)).toEqual(['t']);
  expect(calendarItems(projects, tasks, {
    projectId: 'b'
  })).toEqual([]);
  expect(calendarItems(projects, tasks, {
    includeClosed: true
  }).some(e => e.id === 'old')).toBe(true);
});
it('exporte la journée entière avec fin exclusive et lien direct', () => {
  const out = calendarExport([{
    ...tasks[0],
    date: '2026-12-31',
    kind: 'task',
    label: 'Échéance',
    title: 'Jeu, voix; suite\nLigne 2'
  }], 'https://iris.example', new Date('2026-10-27T12:00:00Z'));
  expect(out).toContain('DTSTART;VALUE=DATE:20261231\r\nDTEND;VALUE=DATE:20270101');
  expect(out).toContain('SUMMARY:Jeu\\, voix\\; suite\\nLigne 2');
  expect(out).toContain('https://iris.example/animateur/projects/a?task=t');
  expect(out.endsWith('END:VCALENDAR\r\n')).toBe(true);
});
it('replie les lignes longues sans couper les caractères UTF-8', () => {
  const title = 'Échange 🌸 '.repeat(20);
  const out = calendarExport([{
    id: 'long',
    project_id: 'a',
    date: '2026-10-27',
    title,
    kind: 'project',
    label: 'Début'
  }], 'https://iris.example');
  const byteLength = value => encodeURIComponent(value).replace(/%[A-F\d]{2}|./g, 'x').length;
  expect(out.split('\r\n').every(line => byteLength(line) <= 75)).toBe(true);
  expect(out.replace(/\r\n /g, '')).toContain(`SUMMARY:${title}`);
});
