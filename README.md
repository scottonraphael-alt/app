# Here are your Instructions

### Tickets : synthèses Claude et actualisation quotidienne

La branche `security/audit-fixes` utilise directement l’API Anthropic pour les synthèses des tickets.
Configurer `ANTHROPIC_API_KEY` dans l’environnement du backend (ou son fichier `.env`, jamais dans Git).
Le modèle se règle avec `TICKET_SUMMARY_MODEL` ; sa valeur par défaut est `claude-haiku-5-5`.
La clé utilisée par la modération IA peut aussi servir aux synthèses. Aucune clé n’est envoyée au navigateur.

Au démarrage de l’API puis toutes les heures, un traitement recherche les dossiers actifs dont la dernière
actualisation automatique réussie date d’au moins 24 heures. Il synchronise leur salon Discord autorisé,
puis régénère la synthèse avec les messages, les notes et les repères actuels. Les dossiers archivés et
les démonstrations sont exclus. Au premier lancement, tous les dossiers actifs sont donc traités.
Un bail MongoDB évite le traitement simultané du même dossier par plusieurs processus. En cas d’échec,
l’ancienne synthèse reste disponible et une nouvelle tentative a lieu après expiration du bail d’une heure.
Le backend doit rester en fonctionnement ; l’ouverture du navigateur n’est pas nécessaire.

La page affiche les messages dans l’ordre chronologique, par pages de 50. L’API
`GET /api/tickets/{id}/messages?page=1&page_size=50` conserve les mêmes restrictions d’accès que les tickets.
`GET /api/tickets/{id}?include_transcript=false` permet de charger le dossier sans sa transcription complète.
