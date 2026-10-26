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


À l’import d’un nouveau ticket, l’interlocuteur est recherché dans le premier message
(« Ton Interlocuteur est <@identifiant> », y compris dans les embeds et composants Discord).
L’attribution est validée avec les rôles `DISCORD_HELPER_ROLE_ID` et `DISCORD_HELPER_ROLE2_ID`.
Sans mention exploitable, sans rôle autorisé ou si la personne est introuvable, le ticket reste non attribué.
Cette détection n’est exécutée qu’à la création : les synchronisations manuelles et quotidiennes
conservent les réattributions et désattributions effectuées dans Iris. Les deux rôles sont également
proposés dans la liste de réattribution manuelle.


### Création automatique des dossiers depuis Discord

Le backend recherche au démarrage puis toutes les 60 secondes les salons textuels dont le nom
commence par `🌸・｜soutien-`, dans la catégorie principale `DISCORD_TICKET_CATEGORY_ID`.
Les dossiers déjà présents sont ignorés, y compris les dossiers archivés ou réattribués.
Le message d’ouverture du bot doit contenir `Soutien de <@identifiant>` : cette mention identifie
la personne aidée, et `Ton Interlocuteur est <@identifiant>` permet d’attribuer le helper.
Les textes des embeds et composants Discord sont également lus. Si le salon est encore vide,
il sera retenté au prochain passage. Les salons existants correspondant au format sont aussi
récupérés après le déploiement, sans import manuel. Les catégories d’archives supplémentaires
ne déclenchent pas cette découverte.

L’accueil récupère les tickets et compteurs toutes les 30 secondes lorsqu’il est ouvert.
L’apparition d’un nouveau dossier prend généralement un à deux cycles de vérification.
Un dossier supprimé dans Iris est exclu de la découverte pour ne pas être recréé automatiquement ;
un nouvel import manuel du salon reste possible. Les réussites et erreurs sont journalisées
côté backend sous `services.ticket_import`. Aucun accès Anthropic n’est nécessaire à l’import.
