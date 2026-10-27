export const ANNOUNCEMENT_AUDIT_LABELS = {
  'announcement.catalogue.viewed': 'Catalogue Discord consulté',
  'announcement.drafts.viewed': 'Bibliothèque d’annonces consultée',
  'announcement.draft.created': 'Brouillon d’annonce créé',
  'announcement.draft.viewed': 'Brouillon d’annonce ouvert',
  'announcement.draft.updated': 'Brouillon d’annonce enregistré',
  'announcement.draft.deleted': 'Brouillon d’annonce supprimé',
  'announcement.previewed': 'Structure d’annonce vérifiée',
  'announcement.assets.viewed': 'Fichiers d’annonces consultés',
  'announcement.asset.uploaded': 'Fichier d’annonce ajouté',
  'announcement.asset.downloaded': 'Fichier d’annonce ouvert',
  'announcement.publication.requested': 'Publication d’annonce demandée',
  'announcement.publication.sent': 'Annonce publiée sur Discord',
  'announcement.publication.failed': 'Publication d’annonce échouée ou incertaine',
  'announcement.publications.viewed': 'Historique des annonces consulté',
  'announcement.publication.viewed': 'Version d’annonce consultée',
  'announcement.publication.cancelled': 'Publication programmée annulée',
  'announcement.action.failed': 'Action sur une annonce refusée ou échouée',
  'announcement.ui.clicked': 'Commande du composeur utilisée',
  'announcement.ui.changed': 'Champ du composeur modifié',
  'announcement.ui.edited': 'Texte du composeur modifié',
  'announcement.ui.shortcut': 'Raccourci du composeur utilisé',
  'announcement.ui.submitted': 'Formulaire du composeur validé',
  'announcement.ui.toggled': 'Volet du composeur ouvert ou fermé'
};
export function announcementLogSummary(type, d = {}) {
  const extras = [];
  for (const [key, label] of Object.entries({
    announcement_id: 'Brouillon',
    publication_id: 'Publication',
    channel_id: 'Salon Discord',
    revision: 'Version',
    before_revision: 'Version précédente',
    original_filename: 'Fichier',
    label: 'Commande ou champ',
    value: 'Sélection',
    length: 'Longueur',
    scheduled_at: 'Programmation UTC',
    reason: 'Motif'
  })) {
    if (d[key] !== undefined && d[key] !== null) extras.push([label, String(d[key])]);
  }
  if (d.source === 'client') extras.push(['Origine', 'Interaction déclarée par l’interface']);
  return {
    text: `${ANNOUNCEMENT_AUDIT_LABELS[type] || 'Action sur une annonce'}${d.title ? ` · « ${d.title} »` : ''}`,
    extras
  };
}
