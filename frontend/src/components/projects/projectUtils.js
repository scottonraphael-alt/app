export const PROJECT_STATUS = {
  en_cours: 'En cours',
  termine: 'Terminé',
  archive: 'Archivé'
};
export const TASK_STATUS = {
  a_faire: 'À faire',
  en_cours: 'En cours',
  rendu: 'À valider',
  valide: 'Validées'
};
export const PRIORITY = {
  basse: 'Basse',
  normale: 'Normale',
  haute: 'Haute'
};
export const personName = person => person?.display_name || person?.username || 'Membre';
export const todayKey = () => new Intl.DateTimeFormat('fr-CA', {
  timeZone: 'Europe/Paris',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit'
}).format(new Date());
export function dateLabel(value, long = false) {
  if (!value) return 'Sans échéance';
  const date = new Date(`${String(value).slice(0, 10)}T12:00:00`);
  return Number.isNaN(date.getTime()) ? 'Date inconnue' : date.toLocaleDateString('fr-FR', {
    day: 'numeric',
    month: long ? 'long' : 'short',
    year: 'numeric'
  });
}
export const isLate = (task, today = todayKey()) => !!task.due_date && task.due_date < today && !['rendu', 'valide'].includes(task.status);
export function progress(counts = {}) {
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  return {
    total,
    done: counts.valide || 0,
    percent: total ? Math.round((counts.valide || 0) / total * 100) : 0
  };
}
export function taskCounts(tasks) {
  return tasks.reduce((counts, task) => ({
    ...counts,
    [task.status]: (counts[task.status] || 0) + 1
  }), {});
}
export function filterProjects(projects, {
  query = '',
  status = 'actifs',
  mine = false,
  helperId,
  priority = '',
  sort = 'updated'
} = {}) {
  const term = query.trim().toLocaleLowerCase('fr');
  const weight = {
    haute: 0,
    normale: 1,
    basse: 2
  };
  return projects.filter(p => (status === 'tous' || (status === 'actifs' ? p.status === 'en_cours' : p.status === status)) && (!mine || p.created_by?.id === helperId || p.members?.some(m => m.id === helperId)) && (!priority || (p.priority || 'normale') === priority) && (!term || `${p.title} ${p.description} ${(p.tags || []).join(' ')} ${p.members?.map(personName).join(' ')}`.toLocaleLowerCase('fr').includes(term))).sort((a, b) => sort === 'date' ? (a.end_date || '9999').localeCompare(b.end_date || '9999') : sort === 'title' ? a.title.localeCompare(b.title, 'fr') : sort === 'priority' ? weight[a.priority || 'normale'] - weight[b.priority || 'normale'] || a.title.localeCompare(b.title, 'fr') : String(b.updated_at).localeCompare(String(a.updated_at)));
}
export const ACTIVITY_LABELS = {
  'project.template.created':'a enregistré un modèle',
  'project.template.applied':'a utilisé un modèle',
  'project.task.checklist.updated':'a mis à jour une étape de checklist',
  'project.review.updated':'a mis à jour le bilan',
  'project.created': 'a créé le projet',
  'project.settings.updated': 'a modifié les paramètres',
  'project.details.updated': 'a modifié le projet',
  'project.content.updated': 'a mis à jour le brief',
  'project.member.added': 'a ajouté un membre',
  'project.member.removed': 'a retiré un membre',
  'project.task.created': 'a créé une tâche',
  'project.task.updated': 'a mis à jour une tâche',
  'project.task.submitted': 'a rendu une tâche',
  'project.task.validated': 'a validé une tâche',
  'project.task.deleted': 'a supprimé une tâche',
  'project.resource.uploaded': 'a ajouté un fichier',
  'project.resource.deleted': 'a supprimé un fichier',
  'project.comment.added': 'a laissé une note'
};
