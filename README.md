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

### Rappel hebdomadaire des dossiers en retard

Le backend envoie un message Discord Components V2 dans le salon `1499495750151966862`
chaque dimanche à **12 h, Europe/Paris** (heure d’été/hiver gérée automatiquement).
Seuls les dossiers actifs, non démonstration, attribués à un membre ayant le rôle
`DISCORD_HELPER_ROLE_ID` ou `DISCORD_HELPER_ROLE2_ID` et sans suivi manuel depuis **7 jours**
sont concernés. Les helpers sont mentionnés individuellement, sans ping de rôle ni `@everyone`.
Les messages affichent le nom de la personne aidée et des liens `FRONTEND_URL/tickets/{id}`,
sans contenu de la conversation. `FRONTEND_URL` reprend l’adresse publique utilisée
pour l’authentification, par défaut `https://iris.loasis.app`.

L’horloge `last_helper_update_at` est mise à jour à la création, à la modification effective
des notes générales, compte-rendu, points de vigilance ou statut de suivi, à l’ajout/suppression
d’une note et à la génération manuelle d’une synthèse IA. Une réattribution accorde une semaine
au nouvel interlocuteur. La synchronisation Discord et la synthèse automatique ne remettent
jamais ce délai à zéro. Les dossiers anciens sans ce champ utilisent les dates disponibles
(notes, synthèse manuelle, création, ou modification postérieure à la dernière synchronisation).
Les dates d’anciennes éditions déjà écrasées par une synchronisation ne peuvent pas être reconstituées.

Le planificateur vérifie toutes les 30 secondes ; il peut rattraper un redémarrage après midi
le dimanche. Un verrou Mongo par dimanche empêche les redémarrages ou plusieurs workers
d’envoyer plusieurs fois le rappel. Sans dossier en retard, aucun message hebdomadaire n’est envoyé.
Les résultats (`sent`, `empty`, `failed`, ou `sending` si un processus a été interrompu)
et identifiants des messages sont conservés dans `ticket_reminder_runs`.
Après un échec ou une réponse réseau incertaine, le rappel n’est pas renvoyé automatiquement
ce dimanche pour éviter des notifications répétées : vérifier les logs `services.ticket_reminders`
et le salon avant un nouvel essai manuel. Le backend doit rester en fonctionnement.

Le bloc **Test temporaire** se trouve dans **Attribution des suivis**, après vérification
des droits coordinateur. Le bouton **Envoyer un test Discord** appelle
`POST /api/admin/ticket-reminders/test` (coordinateur obligatoire) et envoie réellement le rappel,
avec les mentions des helpers concernés. Sans retard, il envoie une confirmation V2 sans mention.
Un test par minute maximum est autorisé pour l’ensemble des coordinateurs ; il ne consomme pas
le rappel du dimanche. Pour retirer le test, supprimer le composant `TicketReminderTestPanel`,
son inclusion dans `AdminDashboardPage` et la route de test. Les tests automatisés simulent
les envois et ne publient rien sur Discord.

### Conservation des avatars des tickets

Les imports manuels et automatiques copient les avatars de la personne aidée, du helper attribué
et des auteurs des messages dans `IRIS_STORAGE_ROOT/iris/avatars/` (racine par défaut `/app/storage`).
Les notes et les réattributions conservent aussi l’avatar de leur auteur/interlocuteur.
La configuration Docker Compose monte déjà `resources-data` sur `/app/storage` : les copies
survivent aux redéploiements tant que ce volume et MongoDB sont conservés. Pour une autre
installation, utiliser un volume persistant à l’emplacement `IRIS_STORAGE_ROOT`.

Les copies sont servies par `GET /api/tickets/avatars/{clé}`, avec les mêmes droits que les tickets.
Les vues de tickets, listes, archives et attributions utilisent ces images via le domaine API.
Une synchronisation réutilise les portraits déjà conservés des auteurs, même si leur avatar Discord
change ou devient indisponible après leur départ. L’accès au membre sur Discord n’est pas nécessaire
pour servir une copie existante. Les écritures d’images sont atomiques, les URL dédupliquées,
et seules des images PNG/JPEG/GIF/WebP provenant des chemins d’avatars des CDN Discord sont acceptées
(1 Mo maximum, aucun suivi de redirection). Les SVG/HTML et URL arbitraires ne sont pas copiés.

Un traitement de rattrapage démarre avec l’API puis repasse chaque heure sur les dossiers existants,
y compris archivés, sans modifier notes, attributions, dates de suivi ni compteurs d’activité.
Les opérations conditionnelles empêchent d’écraser une modification concurrente.
Si le CDN ou le disque est temporairement indisponible, l’import reste possible avec l’URL d’origine
et une copie est retentée après une heure. Un avatar déjà disparu du CDN et jamais conservé ne peut
pas être récupéré ; une initiale est affichée en cas d’échec de chargement dans la conversation.
Les métadonnées de copie sont conservées dans la collection `ticket_avatars`, sans expiration.

### Consultation, recherche et traitement des tickets

L’ouverture d’un dossier par l’interface appelle `POST /api/tickets/{id}/view` : elle actualise
`last_helper_update_at` et alimente le journal. Les GET de détail, la pagination chargée en fond,
les avatars et le polling ne comptent jamais comme une intervention humaine.
Les rappels hebdomadaires tiennent donc compte des ouvertures et des modifications manuelles.

La vue **À traiter** des suivis ouverts regroupe les dossiers sans interlocuteur, sans ouverture
ni mise à jour depuis sept jours, en échec de synchronisation ou en échec de synthèse.
Les motifs sont calculés côté serveur et affichés sur chaque ligne de cette vue.
Le bouton **Rechercher** du dossier recherche dans toute la transcription, avec un mot/une expression
(insensible à la casse et aux accents) et/ou une période de dates, interprétées à Paris.
Les résultats sont paginés par 20 et permettent d’ouvrir la page du message et de le surligner.
Le message d’ouverture automatique masqué reste exclu des résultats visibles.

Les messages et la synthèse restent actualisés ensemble chaque jour côté serveur.
Les états `sync_status`, `sync_error`, `last_sync_attempt_at`, `summary_status`, `summary_error`
permettent d’afficher une actualisation en cours, sa réussite ou son échec. Un échec Anthropic
conserve la dernière synthèse et les messages synchronisés ; il ne devient pas une fausse erreur Discord.

Les actions manuelles des tickets utilisent la collection centrale `auth_logs`, sa rétention
et ses restrictions responsables existantes. La catégorie **Tickets** du journal permet de filtrer
consultations, imports manuels, modifications, notes, attributions/désattributions, archivages/réactivations,
suppressions, synchronisations manuelles, recherches, générations IA et tests de rappel Discord.
Les événements gardent auteur, date, IP, méthode, résultat, dossier et champs concernés,
avec des longueurs pour les textes : les conversations, contenus de notes et termes recherchés
ne sont pas recopiés dans le journal. Les échecs métier sont également consignés.
Les consultations de listes, filtres, recherches de listes, choix d’interlocuteur, changements d’onglet,
pagination, ouvertures de pièces jointes et rédaction/fermeture d’une note sont signalés par l’interface
avec `source: client` pour les distinguer des opérations vérifiées par le serveur.
Le journal de ces interactions n’est pas une preuve d’une modification de données.
Les erreurs d’authentification et d’autorisation continuent d’utiliser le journal de sécurité existant.
Un échec du journal est signalé dans les logs serveur sans annuler une modification déjà enregistrée.

L’archivage retire l’interlocuteur affecté. Un dossier archivé ne peut pas être réaffecté ;
sa réactivation le laisse sans interlocuteur. Les anciennes affectations des dossiers déjà archivés
sont supprimées au démarrage du backend, sans modifier leur date de suivi.

### Statistiques du serveur — blocs 1 à 3

Collecte sans texte des messages, registre technique de 30 jours et premiers compteurs
réservés aux responsables : bouton **Statistiques du serveur** dans le NewDashboard.
Les catégories staff et soutien sont collectées mais masquables dans les résultats.
Le détail du stockage, des limites, du déploiement et des blocs suivants figure dans
[docs/server-statistics.md](docs/server-statistics.md).

Le bloc 2 ajoute les graphiques Apache ECharts : zoom, heatmap, filtres communs, tableaux
accessibles et comparaison des périodes avec indication de la couverture de connexion.

Le bloc 3 ajoute l’onglet Membres et fidélisation : annuaire humain, arrivées/départs,
croissance, cohortes J+7/J+30, premier message, accueil et régularité. Les cohortes se
construisent à partir du déploiement ; une période trop récente reste indiquée en attente.
