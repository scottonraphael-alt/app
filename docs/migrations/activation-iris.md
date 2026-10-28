# Intégration BotGhost → Iris : état et bascule

Intégration du 28 octobre 2026, sur `codex/botghost-integration`, construite à partir
de `origin/security/audit-fixes` (`0c0b193`) et de la préparation `4186ba6`.
Les modifications récentes du site, de l’agenda, de l’équipe et de la supervision
sont conservées. Les anciennes fiches de préparation restent des références de
conception ; **ce document décrit le raccordement actuel**.

## Disponible dans ce lot

- Quatre espaces Staff, avec listes, archives et conversations : Vérifications,
  Convocations, Contacts Staff et Bulles d’échange. Accès depuis le NewDashboard,
  charte Casier, pas de navbar dans les espaces de lecture.
- API sous `/api/casework`, découverte des salons existants authentifiés, collecte
  quotidienne et sur activité, attribution manuelle préservée, notes, recherche sur
  tous les messages, pagination, fichiers/avatars locaux protégés. Suppression
  Discord : conservation de la dernière sauvegarde, désattribution et archive dont
  la complétude est explicitée.
- Sources supplémentaires dans la vue membre 360°, filtrées avant lecture et comptage.
  Les droits des anciennes sources Casier/Soutien et le garde de la page sont conservés.
- Formulaires sous `/staff/verifications` : attente/archives, tentatives, prise en
  charge, décisions argumentées, formation, références IA sélectionnées par un humain,
  suppression d’une tentative par un Responsable et tombstone contre sa réimportation.
- Import historique demandé par un Responsable depuis la liste : fils actifs,
  archivés publics et privés du salon `1226848987559100458`, avec pagination,
  progression/reprise et traitement conservateur des informations ambiguës.
  L’import ne modifie aucun message Discord et n’applique aucune décision ancienne.
- Préavis Anthropic demandé depuis le détail, avec règles d’admission configurées,
  citations vérifiées et références humaines ; aucun choix automatique. Trois demandes
  par minute et par utilisateur au maximum. Aucun résultat IA n’est conservé entre
  dossiers : suppression/retrait d’une référence prend effet immédiatement.
- Journal Responsable : événements de dossiers/formulaires dans la catégorie Tickets,
  libellés français, acteurs et actions, sans copie des conversations ou des notes.
- Moteur natif d’admission, derrière bascule explicite : `/panel-vérification`,
  formulaire obligatoire, panneau Staff V2 avec les réponses, vues persistantes,
  validation/rôles, quatre GIF d’accueil, ticket de discussion, clôture sans expulsion,
  approfondissement demandant un nouveau formulaire complet, refus/kick/ban justifiés.
  Sur Discord : prise en charge, validation, ticket et clôture uniquement ; les autres
  décisions se prennent dans Iris.
- Jobs durables : résultat confirmé étape par étape, notification MP indépendante,
  reprises humaines des étapes incertaines. Une réponse perdue n’entraîne pas une
  seconde sanction. Les messages incertains sont recherchés avec leur nonce lorsqu’il
  est encore observable ; leur absence ne prouve pas qu’ils n’ont jamais été envoyés.
- Kick/ban d’admission : protections fraîches et hiérarchie existantes de `/sanction`,
  mêmes verrous et baux de rôle temporaire, retrait/reprise de nettoyage par la
  maintenance existante, enregistrement au casier et logs dans les posts configurés.
  Le bannissement définitif reste réservé au rôle Administrateur de sanction.
- Clôture de salon depuis Iris : gel, sauvegarde complète et contrôle des fichiers
  avant suppression. La direction peut annuler une clôture bloquée avant la phase
  de suppression pour restaurer les permissions sauvegardées.

## Coexistence : configuration par défaut

```dotenv
# Collecte / lecture des quatre familles ; pas de nouveaux messages Discord.
CASEWORK_ENABLED=true
CASEWORK_CONTACT_CATEGORY_IDS=1081957992896942166
CASEWORK_SOURCE_BOT_IDS=1425117786354483263
CASEWORK_ADMIN_ROLE_ID=1321630097744199721
CASEWORK_SUSPENDED_CATEGORY_IDS=

# Commande native d’admission et effets Discord : désactivés par défaut.
IRIS_NATIVE_WORKFLOWS_ENABLED=false
# Clôtures destructrices des salons encore produits par BotGhost : séparées.
CASEWORK_LEGACY_CLOSURE_ENABLED=false
```

Le rôle historique `DISCORD_ADMIN_ROLE_ID` reste le coordinateur Helper : il n’accorde
pas les accès Administrateur aux nouveaux dossiers. Les Contacts Staff confidentiels
sont réservés aux Responsables/Administrateurs, y compris fichiers, archives et 360°.
Les dossiers avec un autre marqueur hérité de restriction restent conservateurs :
Administrateur uniquement, tant que leur mapping n’est pas confirmé.

Le démarrage raccorde les tâches au superviseur existant et partage le client Discord
actuel. Aucun second bot ni second collecteur des soutiens existants n’est lancé.
Les hooks de messages et salons complètent les traitements existants sans remplacer
l’automodération, les statistiques ou les autres commandes.

## Activer le parcours d’admission natif

Avant de remplacer la publication BotGhost, renseigner les valeurs manquantes :

```dotenv
VERIFICATION_REVIEW_CHANNEL_ID=1425589415165558825
VERIFICATION_WELCOME_CHANNEL_ID=1081957994125860905
CASEWORK_NATIVE_CATEGORY_ID=1081957992896942166
VERIFICATION_MEMBER_ROLE_ID=
VERIFICATION_UNVERIFIED_ROLE_ID=
# Objet JSON avec les quatre identifiants distincts, sous forme de chaînes :
VERIFICATION_AGE_ROLE_IDS={"13-15":"ID","16-17":"ID","18-25":"ID","26+":"ID"}
# Les quatre véritables URL du panneau d’accueil existant, distinctes :
VERIFICATION_WELCOME_GIFS=["https://.../1.gif","https://.../2.gif","https://.../3.gif","https://.../4.gif"]
# Règles explicites utilisées uniquement lors de la demande d’un préavis :
VERIFICATION_ADMISSION_RULES=
```

Le salon de lecture doit être privé au Staff/direction. Le transport refuse d’y
publier si un rôle ordinaire peut le lire. Les rôles Membre, Non validé et âges doivent
être distincts, non gérés par Discord et sous le rôle du bot. La catégorie native doit
appartenir au périmètre autorisé. L’attribution des rôles n’est pas commencée si la
configuration des quatre GIF ou du salon d’accueil n’est pas valide.

Après arrêt du producteur de formulaires BotGhost correspondant, activer
`IRIS_NATIVE_WORKFLOWS_ENABLED=true`, redémarrer et publier `/panel-vérification` avec
un Responsable ou un Administrateur. L’enregistrement est individuel et ne synchronise
pas globalement les autres commandes de l’application. Les vues sont réinscrites au
redémarrage. Une panne d’installation n’arrête pas les autres fonctions du bot.

Un panneau de suivi interrompu reste en attente de réconciliation plutôt que renvoyé
aveuglément. Les anciennes archives ne déclenchent pas une notification Staff chacune.
La suppression d’un formulaire entraîne la mise à jour/rédaction du panneau natif lié
au prochain cycle actif ; aucune suppression des anciennes copies BotGhost n’est faite.

## Ce qui reste à migrer ensuite

Les producteurs publics Contact Staff/Soutien et le panneau de convocation/bulle,
leurs menus natifs de suspension/réouverture/restriction, l’alerte de convocation à
J+3 et le Purgatoire ne sont pas remplacés par ce lot. Ils restent chez BotGhost.
La collecte et les pages Iris fonctionnent en parallèle de ces producteurs existants.
Les soutiens conservent leur module, résumés et rappels actuels.

**Ne pas activer `CASEWORK_LEGACY_CLOSURE_ENABLED` tant que les producteurs concernés
ou un pont de remise à zéro des variables BotGhost ne sont pas migrés.** Sinon leurs
anciens indicateurs `cstaffv3_hastick`, `tat_hastat`, `convlink` pourraient continuer
à déclarer un ticket ouvert après sa suppression par Iris. L’archivage après une
suppression réalisée par le système existant reste disponible sans cette option.

Les règles d’admission sont configurées par environnement dans ce lot ; leur éditeur
Responsable et le préavis court dans Discord restent à raccorder. La réattribution
avancée des admissions et les notifications de second avis restent à compléter.
L’ID du rôle Purgatoire et ses autorités d’entrée/sortie ne sont pas inventés.

Le manuel de formation PDF final et sa fiche courte seront produits après ce dernier
raccordement, pour décrire les écrans et processus effectivement stabilisés.
Aucun déploiement, import de production, message Discord ni changement BotGhost
n’a été réalisé pour vérifier le code de ce lot.

## Vérification de ce lot

- Compilation de production React réussie, avec les avertissements d’ordre CSS déjà
  présents dans les modules agenda/réunions ; aucun screenshot produit.
- Suite frontend complète : **105 tests réussis**.
- Contrôle backend hors ligne : **1 982 réussites et six échecs reproduits sur la base
  distante inchangée**. Cinq dépendent de Web Push indisponible dans le venv local,
  le sixième concerne le traitement historique d’un JSON profondément imbriqué dans
  l’agenda. Aucun de ces fichiers métier n’est modifié par ce lot.
- Après les corrections de revue : **73 tests ciblés réussis** pour les dossiers,
  formulaires, le transport natif, les reprises et la vue 360°.
- Dix anciennes suites prévues pour un serveur de prévisualisation et/ou des chemins
  `/app` ne sont pas exécutables dans ce workspace local. Aucun environnement distant
  n’a été utilisé pour contourner cette limitation.
