import { durationLabel } from './rundownUtils';
import { dateLabel, personName, PRIORITY, PROJECT_STATUS, TASK_STATUS } from './projectUtils';

export const PROJECT_AUDIT_LABELS = {
  'project.rundown.updated':'Déroulé de l’animation mis à jour',
  'project.templates.viewed':'Modèles de projet consultés',
  'project.template.created':'Modèle de projet enregistré',
  'project.template.applied':'Modèle de projet utilisé',
  'project.template.deleted':'Modèle de projet supprimé',
  'project.task.checklist.updated':'Étape de checklist mise à jour',
  'project.review.updated':'Bilan du projet mis à jour',
  'project.action.failed': 'Action sur un projet : échec',
  'project.task.downloaded': 'Rendu téléchargé',
  'project.resource.downloaded': 'Ressource téléchargée',
  'project.tasks.viewed': 'Tâches consultées',
  'project.resources.viewed': 'Fichiers consultés',
  'project.activity.viewed': 'Journal du projet consulté',
  'project.workspace.viewed': 'Liste des projets consultée',
  'project.calendar.viewed': 'Calendrier des projets consulté',
  'project.members.searched': 'Animateurs recherchés',
  'project.ui.clicked': 'Interaction dans les projets',
  'project.ui.changed': 'Champ ou filtre modifié',
  'project.ui.submitted': 'Formulaire envoyé',
  'project.ui.toggled': 'Volet ouvert ou fermé',
  'project.ui.edited': 'Éditeur utilisé',
  'project.ui.shortcut': 'Raccourci utilisé',
};
const fields = {title:'Titre',description:'Description',priority:'Priorité',tags:'Étiquettes',start_date:'Date de début',end_date:'Date de fin',status:'État',assignee:'Attribution',blocked_reason:'Blocage',review_note:'Consigne de correction',checklist:'Checklist',attendance:'Participants',event_date:'Date de l’animation',successes:'Réussites',improvements:'Pistes d’amélioration',next_steps:'Prochaine fois',start_time:'Heure de départ',items:'Séquences'};
function formatValue(key,value) {
  if (value == null || value === '') return key === 'blocked_reason' ? 'aucun blocage' : 'non renseigné';
  if (key === 'status') return TASK_STATUS[value] || PROJECT_STATUS[value] || value;
  if (key === 'priority') return PRIORITY[value] || value;
  if (key === 'items') return value.length?value.map((item,index)=>`${index+1}. ${item.title} (${durationLabel(item.duration_minutes)} · ${item.speaker?personName(item.speaker):'à attribuer'})`).join(' ; '):'aucune séquence';
  if (key === 'checklist') return `${value.filter(item=>item.done).length}/${value.length} étapes cochées : ${value.map(item=>item.title).join(', ')}`;
  if (key === 'assignee') return personName(value);
  if (key.endsWith('_date')) return dateLabel(value);
  return Array.isArray(value) ? value.join(', ') || 'aucune' : String(value);
}
export function projectLogSummary(type,d) {
  const title = d.title || d.after?.title || d.before?.title;
  const target = title ? ` « ${title} »` : '';
  const extras=[];
  if (d.project_title) extras.push(['Projet',d.project_title]);
  if (['project.task.updated','project.settings.updated','project.review.updated','project.rundown.updated'].includes(type)) {
    for (const key of Object.keys(d.after || {})) {
      if (fields[key] && JSON.stringify(d.before?.[key]) !== JSON.stringify(d.after[key])) extras.push([fields[key],`${formatValue(key,d.before?.[key])} → ${formatValue(key,d.after[key])}`]);
    }
    return {text:`a modifié ${type === 'project.task.updated' ? 'la tâche' : type === 'project.review.updated' ? 'le bilan du projet' : type === 'project.rundown.updated' ? 'le déroulé du projet' : 'les paramètres du projet'}${target}`,extras};
  }
  if (type === 'project.task.checklist.updated') return {text:`a ${d.after_done?'coché':'décoché'} l’étape « ${d.item_title || 'Étape'} » de la tâche${target}`,extras};
  if (type === 'project.member.removed') return {text:`a retiré ${d.member_username || d.member_id || 'un membre'} du projet`,extras};
  if (type === 'project.comment.added') return {text:'a publié une note dans le journal du projet',extras};
  if (type.startsWith('project.ui.')) {
    extras.push(['Origine','Interaction déclarée par l’interface']);
    if (d.value != null) extras.push(['Sélection',d.value]);
    if (d.length != null) extras.push(['Taille',`${d.length} ${d.label?.toLowerCase().includes('fichier')?'fichier(s)':'caractères'}`]);
    return {text:`· ${PROJECT_AUDIT_LABELS[type] || 'Interaction'} : ${d.label || ''}`,extras};
  }
  if (PROJECT_AUDIT_LABELS[type]) {
    if (d.reason) extras.push(['Motif',d.reason]);
    if (d.operation) extras.push(['Opération',d.operation]);
    if (d.original_filename) extras.push(['Fichier',d.original_filename]);
    return {text:`· ${PROJECT_AUDIT_LABELS[type]}${target}`,extras};
  }
  return null;
}
