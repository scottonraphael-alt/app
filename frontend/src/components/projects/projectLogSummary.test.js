import { projectLogSummary, PROJECT_AUDIT_LABELS } from './projectLogSummary';
it('décrit les changements de tâche et le blocage avant/après en français', () => {
  const result=projectLogSummary('project.task.updated',{title:'Préparer',project_title:'Soirée',before:{status:'a_faire',priority:'normale',blocked_reason:''},after:{status:'en_cours',priority:'haute',blocked_reason:'Manque le visuel'}});
  expect(result.text).toBe('a modifié la tâche « Préparer »');
  expect(result.extras).toContainEqual(['État','À faire → En cours']);
  expect(result.extras).toContainEqual(['Priorité','Normale → Haute']);
  expect(result.extras).toContainEqual(['Blocage','aucun blocage → Manque le visuel']);
});
it('rend lisibles la réattribution, les paramètres et les interactions', () => {
  const task=projectLogSummary('project.task.updated',{before:{assignee:{username:'Alex'}},after:{assignee:{display_name:'Camille'}}});
  expect(task.extras).toContainEqual(['Attribution','Alex → Camille']);
  expect(projectLogSummary('project.settings.updated',{before:{status:'en_cours'},after:{status:'archive'}}).extras).toContainEqual(['État','En cours → Archivé']);
  expect(projectLogSummary('project.ui.clicked',{label:'Annuler'}).text).toContain('Annuler');
  expect(projectLogSummary('project.ui.clicked',{label:'Annuler'}).extras).toContainEqual(['Origine','Interaction déclarée par l’interface']);
  expect(PROJECT_AUDIT_LABELS['project.task.downloaded']).toBe('Rendu téléchargé');
});
it('expose le motif de refus sans afficher un libellé anglais générique', () => {
  const result=projectLogSummary('project.action.failed',{reason:'Réservé au créateur.',operation:'PATCH /tasks'});
  expect(result.text).toContain('échec');
  expect(result.extras).toContainEqual(['Motif','Réservé au créateur.']);
  expect(projectLogSummary('project.viewed',{})).toBeNull();
});
it('décrit les cases cochées et les changements du bilan',()=>{
  expect(projectLogSummary('project.task.checklist.updated',{title:'Préparer',item_title:'Tester',after_done:true}).text).toContain('a coché l’étape « Tester »');
  const review=projectLogSummary('project.review.updated',{title:'Soirée',before:{attendance:null},after:{attendance:0,successes:'Un bon accueil'}});
  expect(review.text).toContain('le bilan du projet');expect(review.extras).toContainEqual(['Participants','non renseigné → 0']);
});
it('décrit le changement d’heure et des séquences du déroulé',()=>{
  const result=projectLogSummary('project.rundown.updated',{title:'Soirée',before:{start_time:'20:00',items:[]},after:{start_time:'21:00',items:[{title:'Accueil',duration_minutes:10,speaker:{username:'Alex'}}]}});
  expect(result.text).toContain('le déroulé du projet');expect(result.extras).toContainEqual(['Heure de départ','20:00 → 21:00']);expect(result.extras.find(([label])=>label==='Séquences')[1]).toContain('Accueil (10 min · Alex)');
});
it('décrit commentaires, duplication et récapitulatifs automatiques',()=>{
  const comment=projectLogSummary('project.task.comment.updated',{title:'Préparer',before:{body:'Avant'},after:{body:'Après'}});
  expect(comment.extras).toContainEqual(['Commentaire','Avant → Après']);
  expect(projectLogSummary('project.duplicated',{title:'Nouvelle édition',source_title:'Ancienne'}).extras).toContainEqual(['Projet d’origine','Ancienne']);
  expect(projectLogSummary('project.reminders.sent',{result:{task_count:3,helper_count:2}}).extras).toContainEqual(['Destinataires','3 tâches · 2 personnes']);
});
