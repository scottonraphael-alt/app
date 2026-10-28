// Merge into the Responsable journal's event registry at integration.
export const CASEWORK_AUDIT_LABELS = {
  'casework.listed': 'Liste des dossiers consultée',
  'casework.viewed': 'Dossier consulté',
  'casework.messages_viewed': 'Conversation consultée',
  'casework.import_requested': 'Ajout d’un salon demandé',
  'casework.action_requested': 'Action sur un dossier demandée',
  'casework.action_recorded': 'Action sur un dossier enregistrée',
  'casework.file_downloaded': 'Fichier du dossier téléchargé',
};
const ACTION_LABELS = { claim: 'Prise en charge', assign: 'Réattribution', note: 'Ajout d’une note interne', sync: 'Actualisation demandée', archive: 'Clôture demandée' };
export function caseworkAuditSummary(event, details = {}) {
  return { text: CASEWORK_AUDIT_LABELS[event] || 'Suivi d’un dossier', action: ACTION_LABELS[details.action] || null };
}
