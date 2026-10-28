// Merge into the Responsable journal's event registry at integration.
export const CASEWORK_AUDIT_LABELS = {
 'casework.request.submitted':'Demande de dossier enregistrée', 'casework.requests.viewed':'Demandes d’ouverture consultées',
 'casework.request.retry_requested':'Reprise d’ouverture demandée', 'casework.room.created':'Salon natif ouvert',
 'casework.panel.publish_requested':'Publication de panneau demandée', 'casework.panel.published':'Panneau natif publié',
 'casework.training.simulated':'Simulation de ticket effectuée', 'casework.operation.requested':'Modification d’accès demandée',
 'casework.operation.confirmed':'Modification d’accès confirmée', 'casework.support.accept_requested':'Soutien accepté par un Helper',
 'casework.support.refuse_requested':'Refus de soutien enregistré par la coordination', 'casework.support.decision_recorded':'Décision de soutien enregistrée',
 'casework.summons.alerted':'Convocation sans réponse signalée au Staff',
 'casework.purgatory.enter_requested':'Entrée au Purgatoire demandée', 'casework.purgatory.exit_requested':'Sortie du Purgatoire demandée',
 'casework.purgatory.entered':'Entrée au Purgatoire confirmée', 'casework.purgatory.exited':'Accès initiaux restitués', 'casework.purgatory.failed':'Changement du Purgatoire à reprendre',
 'casework.settings.viewed':'Réglages des parcours consultés', 'casework.settings.update_requested':'Modification des parcours demandée',
 'casework.settings.updated':'Réglages des parcours enregistrés', 'casework.settings.gif_uploaded':'GIF d’accueil conservé dans Iris',

  'casework.listed': 'Liste des dossiers consultée',
  'casework.viewed': 'Dossier consulté',
  'casework.messages_viewed': 'Conversation consultée',
  'casework.import_requested': 'Ajout d’un salon demandé',
  'casework.action_requested': 'Action sur un dossier demandée',
  'casework.action_recorded': 'Action sur un dossier enregistrée',
  'casework.file_downloaded': 'Fichier du dossier téléchargé',
};
const ACTION_LABELS = {suspend:'Suspension',reopen:'Rétablissement des participants',restrict:'Restriction à l’administration',unrestrict:'Levée de restriction',add_member:'Ajout de participant',remove_member:'Retrait de participant',cancel_close:'Annulation de clôture', claim: 'Prise en charge', assign: 'Réattribution', note: 'Ajout d’une note interne', sync: 'Actualisation demandée', archive: 'Clôture demandée' };
export function caseworkAuditSummary(event, details = {}) {
  return { text: CASEWORK_AUDIT_LABELS[event] || 'Suivi d’un dossier', action: ACTION_LABELS[details.action] || null };
}
