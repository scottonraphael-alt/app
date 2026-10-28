# Dossiers de tickets — code préparé pour intégration ultérieure

Ce lot prépare les quatre espaces Iris demandés : **Vérifications, Convocations,
Contacts Staff, Bulles d'échange**, avec découverte, attribution, actualisation,
conservation des fichiers et archives. Il est développé dans la copie isolée
`iris-botghost-preparation`, branche `codex/botghost-migration`.

Aucun raccordement à `server.py`, au client Discord actif, au routeur React ou au
NewDashboard actuel n'est effectué. `CASEWORK_ENABLED` vaut faux par défaut ; même si
le routeur est monté accidentellement, son API retourne 503 tant qu'il n'est pas activé.
Le worker ne démarre pas avec cette option désactivée. Aucun essai n'a contacté le
serveur réel, Anthropic ou la base de production.

## Ce qui est codé

| Fichier | Fonction |
| --- | --- |
| `backend/models/casework.py` | Contrats stricts d'import et d'actions versionnées |
| `backend/services/casework/policy.py` | Familles, configuration, droits frais, confidentialité et rôles d'attribution |
| `backend/services/casework/service.py` | Dossiers, attributions, notes, historique, recherche/pagination, archivage après disparition Discord |
| `backend/services/casework/sync.py` | Lecteur Discord, découverte authentifiée, pagination intégrale, bail de synchronisation, hooks |
| `backend/services/casework/assets.py` | Copies privées des fichiers Discord/V2 et rattachement des avatars locaux |
| `backend/services/casework/closure.py` | Sauvegarde vérifiée avant suppression et reprise d'une réponse de suppression perdue |
| `backend/services/casework/discord_gateway.py` | Transport optionnel de clôture avec le client discord.py partagé |
| `backend/services/casework/worker.py` | Cycle explicite, non démarré, découverte et actualisation quotidienne ou sur activité |
| `backend/services/casework/timeline.py` | Source 360° filtrée avant lecture et comptage |
| `backend/routers/casework.py` | API de dossiers, import, actions, messages et fichiers protégés |
| `frontend/src/pages/CaseworkPages.jsx` | Quatre pages dédiées, listes et espaces de lecture/suivi |
| `frontend/src/Casework.css` | Charte Casier, couleurs par famille, clair/sombre, sans navbar |
| `frontend/src/components/casework/CaseworkDashboardLinks.jsx` | Liens à insérer dans le module Staff du NewDashboard |
| `frontend/src/components/casework/caseworkAudit.js` | Libellés français à raccorder au journal Responsable |

## Modèle et conservation

`case_tickets` contient le type, le membre concerné, les accès, l'intervenant,
les notes, l'historique et les états. `case_messages` contient un document par message :
les conversations ne gonflent pas un unique document Mongo et ne sont pas plafonnées
à 1 000 messages. Les index sont créés par `service.indexes()`.

Les synchronisations protègent les changements manuels d'attribution et de notes.
Les avatars sont copiés avec le service existant, mais servis par une nouvelle route
vérifiant les droits du dossier : aucun besoin de donner accès à l'ancien module
Helper pour voir l'avatar d'un ticket Staff.

Les pièces jointes Discord, ainsi que les médias V2 hébergés sur le CDN Discord,
sont copiés vers le stockage Iris privé. Les téléchargements refusent les hôtes
arbitraires, les redirections et les fichiers dépassant le plafond configuré
(50 Mio par fichier dans `Settings`, modifiable à l'intégration). Une copie trop grosse
ou indisponible reste explicitement non conservée et bloque une suppression gérée.
Les liens externes présents dans les messages ne sont pas aspirés comme des fichiers.

Les API ne renvoient ni chemin local ni URL CDN signée des fichiers. Le téléchargement
relit les droits du dossier ; les réponses sont privées, sans cache partagé, avec
`nosniff` et téléchargement forcé. Les avatars sont rattachés à un membre/auteur
présent dans ce dossier avant d'être servis.

Le panneau d'ouverture est conservé en base et masqué dans la conversation. Son motif
extrait des blocs de texte reste disponible dans le volet de suivi. La recherche
porte sur tous les messages conservés, avec expression littérale et pagination serveur.
Les messages déjà copiés ne sont pas purgés parce qu'ils disparaissent de Discord.

## Import, actualisation et clôture

Le lecteur emploie les API déjà présentes dans Iris et parcourt toutes les pages.
Il vérifie serveur, catégorie, préfixe strict, premier message d'ouverture, auteur bot
autorisé et identification non ambiguë du membre. Les cas non reconnus sont laissés
hors import automatique, plutôt que rattachés à un membre supposé.

La découverte retrouve les quatre familles par défaut. Elle n'importe pas à nouveau
les soutiens déjà gérés par `db.tickets`. Le moteur contient une politique `support`
pour un futur raccordement explicite, pas une migration automatique de cette collection.
Une phase de reprise des anciennes transcriptions BotGhost reste distincte : un salon
déjà supprimé avant la première collecte ne peut pas être reconstruit par ce lecteur.

Le cycle callable découvre les nouveaux salons puis synchronise les dossiers dus au
moins quotidiennement. Les hooks de création/édition/suppression de message peuvent
forcer une actualisation au passage suivant. Les erreurs isolées ne bloquent pas les
autres dossiers ; une synchronisation échouée est signalée avec délai de reprise.

Pour une suppression Discord inattendue, le dossier passe aux archives, conserve
ses données et n'a plus d'intervenant actif. Son archive est signalée comme **dernière
sauvegarde non garantie complète** : aucun dernier message non collecté n'est inventé.

Pour une clôture demandée depuis Iris :

1. Contrôle frais des droits, révision et référence de requête idempotente.
2. État « closing » avec motif et acteur, exécuté par un worker exclusif.
3. Sauvegarde des permissions avant toute mutation, puis gel de l'écriture du salon.
4. Copie de l'historique et des fichiers ; vérification de leur présence et empreinte.
5. Enregistrement du manifeste d'archive.
6. Nouveau contrôle des droits et du dernier message avant suppression Discord.
7. Archivage confirmé, retrait de l'attribution active et conservation du parcours 360°.

Un nouveau message après le snapshot empêche la suppression et impose une nouvelle
sauvegarde. Les administrateurs Discord peuvent contourner le gel d'écriture : Discord
ne fournit pas ici de transaction atomique entre lecture et suppression ; le contrôle
du dernier message réduit cette fenêtre sans promettre une atomicité inexistante.
Une réponse de suppression perdue est réconciliée à partir de l'état réel du salon,
sans double suppression. Une clôture échouée est visible et reprenable par la direction.
Le gel d'écriture demeure tant que la clôture n'est pas terminée ; le rétablissement
ou l'annulation guidée de cette clôture reste à ajouter avant exploitation générale.

## Politique d'accès

- Tickets ordinaires des quatre familles : Staff, Responsables et Administrateurs.
- Contact Staff confidentiel : Responsables et Administrateurs, sans droit implicite
  pour le Staff ordinaire. L'accès du membre concerné sur Discord ne crée pas un nouvel
  accès public à Iris ; l'authentification existante du site reste requise.
- Marqueur de restriction `⚜️` sur une convocation/vérification/bulle héritée : accès
  conservateur Administrateur seulement tant que le mapping réel des rôles restreints
  n'a pas été confirmé. Aucune hypothèse d'accès plus large n'est faite.
- Un marqueur plus restrictif peut resserrer les accès d'un dossier déjà importé.
  Un renommage inverse n'élargit jamais automatiquement la visibilité. La levée
  explicite et contrôlée devra être raccordée aux actions du futur moteur Discord.
- L'attribution ne donne jamais accès à une personne qui ne peut pas déjà lire le
  dossier. Le moteur conserve une attribution manuelle lors de la redécouverte.
- Politique préparée pour les soutiens : lecture collective Helpers/Helpers+/Staff,
  attribution à un Helper/Helper+ uniquement ; coordination pour la réattribution.

**Attention au nom historique d'un réglage Iris :** `DISCORD_ADMIN_ROLE_ID` est utilisé
par certaines fonctions Helper pour le coordinateur. Il n'est pas réutilisé comme
preuve d'accès aux Contacts Staff confidentiels. Le nouveau moteur utilise le rôle
Administrateur réel (`CASEWORK_ADMIN_ROLE_ID`, sinon
`SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID`, déjà fixé à `1321630097744199721`) et le rôle
Responsable. Vérifier ce mapping avec l'authentification du site lors de l'intégration.

La source 360° ne fournit que métadonnées et liens, jamais la conversation ou les notes.
Son filtrage s'applique aussi aux compteurs et aux archives. Un événement d'archivage
récent d'un dossier ancien reste visible, même si d'autres dossiers ont été ouverts
plus récemment. La page 360° conserve son garde actuel ; ajouter ces sources ne doit
pas ouvrir les casiers ou les suivis à de nouveaux rôles.

## Raccordement à la dernière version d'Iris

1. Reprendre la dernière branche stable et rapprocher ses services de fichiers,
   d'authentification, d'audit, de tickets, du bot et de la vue 360°. Ne pas écraser les
   changements intervenus dans la branche du site pendant cette préparation.
2. Valider les catégories autorisées, les IDs d'auteurs bot des anciens panneaux,
   l'accès du bot au stockage persistant et les droits réels des salons hérités.
3. Monter `routers.casework.router` sous `/api` seulement dans le périmètre choisi ;
   conserver les protections globales de session, CSRF et limitation de débit.
4. Construire `DiscordGateway(client_partage, settings)` après connexion du bot.
   Démarrer `worker.run(gateway, settings, stop_event)` sous garde explicite de
   fonctionnalité. Fermer proprement cette tâche à l'arrêt. Rien ne doit être lancé
   par le simple import du module.
5. Ajouter les hooks aux gestionnaires existants sans les remplacer :
   `worker.mark_message_activity` pour les messages ; `sync.channel_deleted` pour
   une suppression ; `sync.tighten_visibility` pour un changement vers un marqueur
   restreint d'un dossier connu. Les événements ne suffisent pas seuls : le cycle
   de découverte/synchronisation assure aussi la reprise après déconnexion du bot.
6. Monter les huit routes React (liste et détail), gardées Staff/direction :

| Route de base | Composant exporté |
| --- | --- |
| `/staff/dossiers/verification` | `VerificationTicketsPage` |
| `/staff/dossiers/summons` | `ConvocationsPage` |
| `/staff/dossiers/contact_staff` | `ContactsStaffPage` |
| `/staff/dossiers/bubble` | `BullesPage` |

   Chaque route de détail ajoute `/:caseId`. Passer `canReassign` selon la vraie
   autorité Responsable/Administrateur et `canSeeMember360` selon le garde actuel
   de la vue 360°, sans assimiler coordination Helper et administration serveur.
7. Insérer `CaseworkDashboardLinks` dans le module Staff du NewDashboard. Les
   booléens UI ne remplacent jamais les contrôles côté API. Les soutiens continuent
   d'utiliser leur module existant pendant cette étape.
8. Fusionner les événements de `casework.timeline.entries` avec la frise et ses
   compteurs après contrôle des droits. Relier les tickets de vérification au
   formulaire d'admission, tout en gardant ces deux objets distincts.
9. Ajouter `caseworkAudit.js` au registre et aux filtres du journal Responsable.
   Les consultations, recherches, imports, demandes d'action et téléchargements sont
   journalisés. Le contenu des notes et échanges n'est pas recopié dans les logs.
10. Avant d’autoriser une clôture Iris sur des salons encore créés par BotGhost,
    migrer leurs producteurs ou fournir un pont vérifié de remise à zéro des anciens
    indicateurs `cstaffv3_hastick`, `tat_hastat` et `convlink`. Ce moteur ne modifie pas
    le stockage BotGhost : supprimer un salon sans ce raccordement laisserait ses
    anciens boutons croire qu’un ticket existe encore. Ne pas activer cette coexistence
    destructrice sans le pont ou la bascule des producteurs.
11. Faire une validation de bout en bout sur un environnement de test, puis activer
    progressivement. Le manuel PDF devra décrire le parcours réellement raccordé.

Exemple de réglages à vérifier avant activation (aucun secret) :

```dotenv
CASEWORK_ENABLED=false
CASEWORK_CONTACT_CATEGORY_IDS=1081957992896942166
CASEWORK_SOURCE_BOT_IDS=1425117786354483263
CASEWORK_ADMIN_ROLE_ID=1321630097744199721
# Catégories où un salon est suspendu, si elles sont utilisées :
CASEWORK_SUSPENDED_CATEGORY_IDS=
```

## Périmètre qui reste séparé de ce lot

Ce lot ne remplace pas encore les commandes publiques BotGhost. La publication et
les formulaires de demande, l'acceptation/refus des demandes de soutien, les actions
natives de suspension/réouverture/restriction, le Purgatoire et les alertes de
convocation à trois jours restent à raccorder/développer selon les fiches métier.
Le système de formulaire d'admission préparé précédemment garde aussi sa propre
procédure d'intégration. Le PDF final n'est pas encore généré.

Les résumés Anthropic et rappels des suivis existants ne sont pas modifiés. Leur
extension éventuelle aux nouvelles familles doit recevoir des prompts adaptés,
respecter les accès et la provenance des messages, puis être branchée explicitement ;
aucun appel payant n'a été ajouté au cycle de ce lot.

## Vérifications

Tests Python : familles et sources autorisées, confidentialité des listes/détails/
fichiers/360°, séparation coordinateur/Administrateur, historique de 1 005 messages,
recherche littérale, conservation des attributions, révocation des rôles, suppression
inattendue, snapshot incomplet, sauvegarde avant suppression, réconciliation d'une
réponse perdue et désactivation du module. Tests React : quatre pages, pagination,
archives lisibles, confirmation de clôture et absence d'affichage sous une mauvaise
famille.

Les tests restent hors ligne ; aucun screenshot ni test d'envoi réel n'est produit.
La compilation globale de l'application ne valide pas encore ces routes non montées :
les tests importent directement leurs composants. Un test global après raccordement
reste nécessaire.

Résultat du lot préparé : **60 tests ciblés réussis**, dont 35 nouveaux pour les
nouveaux dossiers (26 Python, 9 React) et 25 pour la préparation des formulaires de
vérification. La syntaxe des composants, les exports d'icônes et la feuille CSS ont
également été contrôlés sans rendu ni screenshot.
