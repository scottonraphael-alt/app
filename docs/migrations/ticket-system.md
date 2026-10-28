# Tickets OasisBot — analyse de l'événement central

Lecture du constructeur BotGhost le 28 octobre 2026. Bot OasisBot,
`1425117786354483263`. Événement ouvert : **When a channel is created**.
Cette fiche décrit l'analyse et les décisions métier, sans code de migration des
nouveaux tickets, sans modification de BotGhost et sans exécution sur Discord.
Le constructeur est resté « Saved », avec Undo désactivé pendant les lectures.

## Périmètre de la lecture

Le diagramme rendu comporte 118 blocs et 134 liaisons. Les résumés des blocs et les
liaisons portant un identifiant ont été relevés ; les propriétés des cinq panneaux,
des menus, des principaux boutons, des modifications de permissions, des messages
et destinations d'archive ont été lues. Ce relevé ne vaut pas analyse exhaustive des
commandes qui créent les salons. Certaines liaisons graphiques internes ne portent
pas d'identifiant exploitable dans le DOM ; ne pas inventer leur rattachement.

Les valeurs confidentielles de protection des transcriptions ne sont pas recopiées.

## Architecture reconnue

L'idée exprimée par l'utilisateur s'inspire de la reconnaissance antigène/anticorps :
plusieurs producteurs créent un salon avec un marqueur ; l'événement de création
reconnaît ce marqueur et déploie le panneau correspondant. Les parcours rejoignent
ensuite des actions communes.

Début de l'événement observé :

1. Attente de deux secondes.
2. Variable d'exécution `usridchan` depuis
   `{BGVAR_ticketv3_userid[{event_channel_id}]}`.
3. Variable d'exécution `msgchan` depuis
   `{BGVAR_ticketv3_msg[{event_channel_id}]}`.
4. Comparaison du nom du salon par **contains**, et non par un préfixe strict.
5. Définition de `ticktype` et envoi du panneau V2 correspondant.

| Type | Marqueurs de création reconnus | Objet |
| --- | --- | --- |
| 1 | `🎫・｜cstaff`, `⚜️・｜cstaff` | Contact Staff à l'initiative du membre |
| 2 | `🎫・｜convoc`, `🚧・｜convoc-` | Convocation privée à l'initiative du Staff |
| 3 | `🎫・｜vérif` | Échange complémentaire de vérification |
| 4 | `🌸・｜soutien` | Accompagnement avec un interlocuteur Helper |
| 5 | `🎫・｜bulle`, `🫧・｜bulle-` | Discussion privée rassurante à l'initiative du Staff |

**Précision utilisateur :** la bulle partage la mécanique d'une convocation mais
sert à parler en privé avec un membre qui n'a rien fait de mal. Le terme convocation
pouvant inquiéter, conserver une présentation rassurante et un libellé distinct,
y compris dans Iris et les archives. Ne pas présenter une bulle comme une sanction.

## Panneaux et données affichées

- Contact Staff : membre concerné, motif, attente de prise en charge, bouton de prise
  en charge puis version du message indiquant « Pris en charge par {user} ».
- Convocation : membre concerné, auteur via `{BGVAR_ticketv3_auth}`, motif.
- Vérification : membre concerné, échange complémentaire avant validation, auteur via
  `{BGVAR_ticketv3_auth}`.
- Soutien : membre, interlocuteur via `{BGVAR_ticketv3_auth}`, rappel de la demande,
  triggers via `{BGVAR_ticketv3_trig}`, mentions Helper et Helper+.
- Bulle : message précisant qu'il n'y a pas de problème, auteur et motif de l'échange.

Le motif et le propriétaire sont récupérés avec l'ID du salon. L'auteur et les
triggers apparaissent sans index dans les modèles de message : leur portée et leur
alimentation doivent être vérifiées dans les commandes productrices, notamment pour
les créations simultanées. Cela constitue un point à examiner, pas une panne prouvée.

## Menus et droits observés

Menus Contact Staff, convocation, vérification, bulle : rôle Staff
`1081957992401997830`, cinq options : ajouter un membre, retirer un membre,
restreindre, suspendre, fermer. Les réponses du menu sont configurées « Only them ».
Le menu du contact Staff après prise en charge conserve la même restriction de rôle.

Menu soutien « Actions Helper » : Staff, Helper `1499491909750755570`,
Helper+ `1500591187185242203` ; seulement ajouter, retirer et fermer.
Les options rejoignent les mêmes formulaires et le parcours de fermeture commun.

L'ajout ouvre `addm` et récupère la sélection de membre via `{addm.addm}` ; le retrait
utilise `{rmm.addm}`. Les blocs d'édition ajoutent respectivement un Allow ou un Deny
`VIEW_CHANNEL` pour cette identité, en conservant les autres permissions du salon.
Vérifier la cardinalité exacte du sélecteur lors de la lecture de son éditeur : le
résumé indique que les IDs multiples sont séparés par des virgules, sans prouver que
le formulaire actuel autorise plusieurs choix.

La restriction passe par une condition Administrateur `1321630097744199721`.
Le bouton « Lever les restrictions » exige aussi ce rôle. Les types prévus pour les
renommages de restriction sont 1, 2, 3, 5 ; pas le soutien.

Le bouton « Prendre en charge » du contact Staff est actuellement **Anyone**, sans
limite d'utilisations. Le parcours visible édite le message et l'épingle, sans étape
explicite d'enregistrement atomique d'une attribution. À corriger dans la migration.

Les boutons de réouverture et de confirmation de fermeture sont aussi configurés
Anyone. Il faut distinguer cette configuration du contexte qui expose effectivement
le message : une confirmation issue d'un menu privé n'est pas nécessairement visible
au membre du ticket. Recontrôler néanmoins les droits dans chaque interaction.

## Suspension et restriction : deux actions différentes

Suspension observée : déplacement dans **Archives Tickets**, remplacement de toutes
les permissions par quatre overwrites de rôles, suppression des accès individuels.
Le message de suspension indique explicitement qu'à la réouverture il faut rajouter
le membre via le menu Staff. Le bloc de réouverture remet le salon dans Contact Staff
et conserve les permissions présentes, sans restaurer les participants supprimés.

Restriction observée : vérification Administrateur, sauvegarde de `oldname`, renommage
selon le type avec `⚜️・｜…`, modification de deux overwrites sans effacer les autres,
message épinglé et bouton de levée. La levée rétablit `oldname` et modifie quatre
overwrites. Les rôles précis visés par ces overwrites ne sont pas tous confirmés :
les listes de rôles rendues ne montraient pas les valeurs sélectionnées au-delà de
leur portion affichée. Ne pas déduire ces IDs à partir du nom de l'action.

**Choix utilisateur :** à la réouverture d'un salon suspendu, restaurer automatiquement
les participants précédents. Conserver un instantané des accès pertinents avant
suspension ; appliquer les contrôles actuels de rôle et les garanties de confidentialité
avant restauration, plutôt qu'une restauration aveugle d'autorisations obsolètes.

## Fermeture et archives

Parcours observé :

1. Confirmation explicite de fermeture définitive, avec bouton Annuler.
2. Branchement selon `ticktype`.
3. Réinitialisation spécifique éventuelle : `cstaffv3_hastick=0` pour Contact Staff,
   `tat_hastat=0` pour soutien ; `convlink=1` pour convocation et bulle, avec reset
   après une minute.
4. Création de la transcription HTML, limitée à **1 000 messages** dans les cinq
   résumés de blocs.
5. Message V2 dans la destination d'archive, avec membre, auteur de clôture et URL.
6. Nettoyage de la confirmation, réponse « Sauvegarde du salon en cours … », attente
   de cinq secondes, suppression du salon via `{event_channel_id}`.

| Famille | Destination d'archive Discord |
| --- | --- |
| Contact Staff | `1448318880249282711` |
| Convocation | `1388187727035498516` |
| Vérification | `1387065654368276640` |
| Soutien | `1388891698314219623` |
| Bulle | `1555315200234627143` |

Les transcriptions contact Staff et convocation ont une protection par mot de passe
activée dans les propriétés examinées. Ne pas recopier de secret dans la documentation
ni supposer sans lecture que les autres blocs ont exactement la même configuration.

Les messages d'archive annoncent déjà « supprimé et archivé » alors que la suppression
vient plus tard dans le parcours. Pour la migration, distinguer sauvegarde confirmée,
archivage et suppression réellement confirmée. Ne supprimer aucun salon tant que
l'archive durable et sa destination n'ont pas été vérifiées ; éviter la troncature
silencieuse à 1 000 messages.

## Décisions utilisateur pour la migration

- Un intervenant principal par ticket, avec réattribution possible ; ce rôle n'exclut
  pas les autres intervenants autorisés de la consultation et du travail collectif.
- Réouverture : restauration automatique des participants précédents.
- Soutien : **tous les Helpers, Helpers+ et Staff peuvent lire les échanges**.
  L'accès collectif sert au conseil entre intervenants et à leur contrôle mutuel.
  Il s'agit d'une exigence de sécurité, pas d'une préférence d'affichage.
- L'attribution à un interlocuteur ne rend jamais le ticket privé pour lui seul.
  Les actions d'ajout/retrait doivent porter sur les participants individuels et ne
  pas servir à neutraliser le droit de regard collectif des rôles autorisés.
- Préserver les réattributions manuelles faites dans Iris : un rafraîchissement ou un
  import ne doit pas rétablir automatiquement l'auteur initial comme interlocuteur.
- Conserver la distinction de présentation bulle/convocation et leurs archives.

## Simplification envisagée, non encore développée

Un service commun peut stocker type, état, membre concerné, initiateur, intervenant
principal, participants, historique, panneau et références d'archive. Les préfixes
restent utiles à la reconnaissance des salons hérités et à leur lisibilité, tandis
que l'état de référence en base évite qu'un renommage change l'identité du dossier.

Séparer les transitions ouverture, prise en charge, suspension, réouverture,
restriction, levée, archivage et suppression ; contrôler les droits à chaque action,
empêcher les doubles panneaux/clôtures et reprendre les effets échoués sans doublons.
L'accès de supervision des soutiens doit rester indépendant des overwrites individuels.

## Analyse encore nécessaire avant code

Commandes repérées dans la liste BotGhost, sans analyse de leurs branches à ce stade :
`/panel contact-staff`, `/panel support`, `/panel soutient`, `/panel moderation`,
`/panel salon-aide`. `/panel verification` a déjà été analysée dans sa fiche propre.
Leur rôle exact dans la création des cinq familles doit être confirmé, sans se fier
uniquement au nom des commandes. `/install-convocation` apparaît désactivée ; ne pas
la considérer comme le parcours actif sans vérification.

À relever ensuite : gardes d'accès et catégories de création, collecte du motif,
sélection de l'interlocuteur, gestion des doublons et des membres absents, portée des
variables auteur/triggers, notification du membre, liens avec salons d'aide/support,
règles précises de restriction et attribution des rôles de supervision.

Aucun nouveau code de tickets n'est produit avant restitution et clarification de ces
parcours. Les documents et la préparation de la vérification restent sur la branche
isolée `codex/botghost-migration` ; la branche du site demeure indépendante.
