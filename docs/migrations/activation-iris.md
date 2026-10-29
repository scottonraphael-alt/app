# OasisLink et Iris : parcours natifs activés

Lot du 28 octobre 2026 sur `codex/botghost-integration`, à partir de la branche
`security/audit-fixes` et du premier raccordement `8b990d8`. Les fonctionnalités
natives sont maintenant activées par défaut dans le code. Aucun test n’a envoyé de
message réel, appliqué de rôle ou touché à la base de production.

## Déployer ce lot

1. Déployer **le backend et le frontend de cette branche**, puis redémarrer le backend.
2. Si ces variables ont été explicitement fixées à `false` sur l’hébergeur, les remettre
   à `true` : `CASEWORK_ENABLED`, `IRIS_NATIVE_WORKFLOWS_ENABLED`,
   `CASEWORK_LEGACY_CLOSURE_ENABLED`. Les défauts du nouveau code sont `true`.
3. Dans le module Responsable, ouvrir **Parcours Discord et rôles**
   (`/responsable/parcours-discord`). Les identifiants et GIF fournis sont préremplis.
   Vérifier les destinations, notamment le salon des alertes Staff de convocation.
4. Sur Discord, choisir **l’application OasisLink**, puis publier les panneaux natifs :
   `/panel verification`, `/panel contact-staff`, `/panel soutient`.
5. Arrêter l’utilisation des producteurs et commandes de tickets BotGhost correspondants.
   La publication remplace les trois anciens messages publics connus ; elle ne peut
   pas supprimer les commandes appartenant à une autre application Discord.

Les commandes sont enregistrées individuellement au démarrage, sans synchronisation
qui supprimerait les autres commandes du bot. Un échec de l’un des modules n’empêche
pas les autres commandes de s’enregistrer. L’activation est celle du code déployé :
la modification locale ne redémarre pas elle-même le serveur d’hébergement.

### Lecture du salon des formulaires

Le contrôle de publication reconnaît les rôles Opérateur/Opérateur en formation
configurés dans les variables existantes. Pour le serveur Oasis uniquement
(`1081957992188088391`), il reconnaît également les lecteurs déjà présents et
identifiés dans les logs : Bots `1081957992381042821`, Opérateur en formation
`1323371858686382100`, Opérateur `1321629751840084040`.
`VERIFICATION_REVIEW_READER_ROLE_IDS` permet de remplacer cette liste complémentaire
par des IDs séparés par des virgules (une valeur vide supprime ces défauts).
Cette liste autorise la publication dans un salon que ces rôles peuvent déjà lire :
elle ne modifie aucune permission Discord et n'accorde aucun droit de décision
ou d'accès aux pages Iris. Les contrôles Staff/Responsable des actions restent actifs.

## Commandes disponibles

| Commande OasisLink | Usage et droits |
| --- | --- |
| `/panel verification` | Admission ; Responsable ou Administrateur |
| `/panel-vérification` | Alias du même panneau d’admission |
| `/panel contact-staff` | Contact Staff ; Administrateur |
| `/panel soutient` | Demande de soutien ; Responsable ou Administrateur |
| `/panel moderation` | Panneau privé du Staff, sélection du membre puis convocation/bulle |
| `/convocation membre [formation]` | Préparer une convocation, avec contrôle des cibles Staff |
| `/bulle membre [formation]` | Échange privé rassurant, sans motif disciplinaire |
| `/dossier` | Actions privées du dossier lié au salon |
| `/purgatoire membre action` | Entrée/sortie avec motif et confirmation, tous les Staff |

Les boutons publics de Contact Staff et de demande de soutien sont ouverts aux membres.
Les droits de gestion sont revérifiés à chaque interaction. Le mode formation n’applique
aucun salon, rôle, MP ou sanction réelle.

## Paramètres fournis et conservés

| Rôle | ID |
| --- | --- |
| Membre | `1081957992381042822` |
| Non validé | `1081957992401997827` |
| 13-15 ans | `1081957992230047764` |
| 16-17 ans | `1081957992230047763` |
| 18-25 ans | `1081957992230047761` |
| 26 ans et plus | `1081957992230047760` |
| Purgatoire | `1523827999563186437` |

Les quatre GIF sont copiés dans `backend/assets/welcome/` et envoyés à Discord en
pièces jointes, avec une probabilité de 25 % chacun. Leur affichage ne dépend plus
de l’expiration des signatures CDN fournies. Ils peuvent être remplacés par un
upload GIF dans Iris. Les réglages persistants en base prennent le relais des défauts.
Les rôles Helper, Helper+, Staff, Responsable, coordination et les logs de sanctions
réutilisent la configuration du site.

`DISCORD_ADMIN_ROLE_ID` conserve son sens historique de coordination Helper.
L’Administrateur réel utilise `CASEWORK_ADMIN_ROLE_ID`, sinon le rôle existant
`SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID` (`1321630097744199721`).

## Production des salons et coexistence

Les créations sont réservées en base avant l’appel Discord. Un membre ne peut pas
ouvrir simultanément deux Contacts Staff, même dans les deux variantes. Les demandes
de soutien distinguent attente, acceptation en cours, salon ouvert et refus.
Seuls les Helpers/Helpers+ acceptent ; seul le rôle de coordination refuse, avec motif.
Le refus est conservé indépendamment du MP et permet une nouvelle demande après
le délai anti-spam (`CASEWORK_REQUEST_COOLDOWN_SECONDS`, défaut 300 secondes).

Les nouveaux marqueurs ne contiennent pas ceux reconnus par l’ancien événement
BotGhost, qui utilisait `contains` :

| Famille native | Nom |
| --- | --- |
| Contact Staff | `💬・｜contact-staff-…` |
| Contact confidentiel | `🔒・｜contact-staff-…` |
| Convocation | `🛡️・｜convocation-…` |
| Bulle | `🫧・｜discussion-…` |
| Discussion de vérification | `📋・｜verification-…` |
| Soutien | `🌸・｜iris-soutien-…` |

Les anciens noms restent reconnus à l’import, dont `🌸・｜soutien-…`. Les soutiens
natifs alimentent aussi le module de suivi existant, sans écraser ses réattributions.
Les fichiers, avatars et conversations des dossiers sont conservés par le moteur
paginé de dossiers. La vue 360° évite de compter deux fois un soutien déjà fourni par
son ancienne source. Les droits des sources Casier/Soutien existantes restent inchangés.

Les indicateurs privés de BotGhost ne sont pas modifiables par Iris. Après une clôture
native d’un ancien salon, un ancien bouton BotGhost pourrait encore considérer son
ancien drapeau comme actif : utiliser les panneaux OasisLink après bascule et ne pas
republier les anciens producteurs. Les nouveaux verrous et demandes ne reposent plus
sur ces drapeaux.

## Gestion et confidentialité

Les dossiers disposent de prise en charge, réattribution, notes, recherche complète,
pagination, archives et fichiers protégés. Discord et Iris permettent aussi ajout/retrait
de participants, suspension/réouverture avec instantané, restriction/levée réservées
aux Administrateurs, et clôture après sauvegarde vérifiée. Les soutiens gardent la
lecture collective Helpers/Helpers+/Staff et ne peuvent pas être restreints à un seul
interlocuteur. Deux invités ordinaires au maximum y sont ajoutés.

Un contact confidentiel reste réservé au membre, aux Responsables et Administrateurs.
L’ajout d’un participant ne permet pas de contourner cette confidentialité. Une
attribution n’accorde aucun droit de lecture supplémentaire. Le bénéficiaire et les
accès de supervision ne peuvent pas être retirés comme de simples invités.

Une action interrompue est affichée « à vérifier ». Les demandes d’ouverture peuvent
être relues et reprises dans Iris, avec explication et confirmation d’un élément absent.
Une réponse Discord perdue ne déclenche pas une nouvelle création ou sanction aveugle.
Les opérations, consultations et demandes de reprise sont journalisées sans copier
les notes ou conversations dans le journal Responsable.

## Admissions et préavis IA

Le panneau présente les réponses au Staff, avec vues persistantes réinscrites au
redémarrage. Les seules décisions disponibles directement dans Discord sont prise
en charge, validation, ticket de discussion et clôture sans expulsion. Refus, kick,
ban, approfondissement et second avis passent par Iris avec justification argumentée.
La direction peut réattribuer un dossier d’admission.

Le préavis Anthropic est demandé explicitement dans Iris : citations vérifiées,
références choisies par un humain et aucune décision automatique. Un aperçu court
peut être publié temporairement dans le panneau Staff ; il expire ou est invalidé
lors du retrait d’une référence. Les archives complètes et explicitement décidées
peuvent être qualifiées manuellement comme exemples par un Responsable, sans
inventer leur date ou réattribuer leur ancienne décision au curateur. Les tests et
formations sont exclus durablement des références.

L’import du salon historique `1226848987559100458` est déclenché dans Iris par un
Responsable et parcourt les fils actifs, archivés publics et privés. Les informations
ambiguës restent signalées plutôt qu’inférées. La suppression d’un formulaire purge
ses réponses et références et laisse un tombstone contre sa réimportation.

Les kicks/bans réutilisent les protections de cible, verrous, baux de rôle temporaire,
casier et posts de logs existants. Le bannissement définitif exige le rôle Administrateur
prévu et le garde Staff de modération. Le plafond de modération IA à 3 000 tokens
n’est pas modifié.

## Purgatoire et alerte à trois jours

Tous les Staff peuvent demander entrée et sortie avec motif et confirmation. Les
cibles protégées ne sont pas sanctionnables. Le rôle d’accès initial Membre ou Non
validé et les overwrites sont sauvegardés avant mutation. Les autres rôles ne peuvent
pas redonner accès aux salons masqués. Les nouveaux salons sont pris en compte et
les instantanés ne sont pas remplacés par un état déjà restreint lors d’une reprise.
La sortie restitue le rôle et les permissions sauvegardés.

Les modifications d’accès d’un dossier impliquant un participant au Purgatoire et
la validation de ses accès d’admission attendent son rétablissement. Une opération
partielle reste réparable ; aucun délai d’expulsion ou de sanction n’est ajouté.

Une convocation ouverte sans réponse du membre depuis trois jours produit une
alerte dans la destination Staff configurée, après contrôle d’un historique complet.
Les destinations internes doivent être privées et accessibles aux seuls rôles prévus ;
un salon dont les droits sont trop larges est refusé. Aucune sanction automatique.

## Documentation et validation

- [Manuel de formation](../../output/pdf/iris-manuel-formation.pdf) : six pages.
- [Mémo Staff](../../output/pdf/iris-memo-staff.pdf) : une page.
- Suite backend hors ligne : **2 009 tests réussis**, six échecs déjà reproduits sur la
  base d’origine (cinq Web Push liés au venv, un cas historique d’agenda sous Python 3.13).
- Suite frontend complète : **105 tests réussis**. Build de production réussi avec
  avertissements d’ordre CSS existants et plugin ESLint indisponible dans le runtime local.
- Dix anciennes suites exigent un serveur de preview et/ou `/app` ; elles ne sont
  pas exécutées dans ce workspace. Aucun envoi ou rôle réel n’a servi de test.
- Les PDF ont été rendus et vérifiés ; aucune capture d’écran du site n’a été faite.
