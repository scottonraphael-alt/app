# /panel soutient — demande et ouverture d'un salon de soutien

Lecture du constructeur OasisBot le 28 octobre 2026 : 33 blocs et 31 connexions. Le déclencheur observé s'écrit
bien `/panel soutient` ; ne pas corriger silencieusement son nom lors de la migration.
Cette fiche porte uniquement sur l'analyse : aucun salon créé, aucune demande traitée,
aucun MP envoyé et aucun nouveau code de tickets activé.

## Publication et présentation actuelle

La publication du panneau est réservée aux rôles Responsable et Administrateur,
avec réponses privées. Elle actualise le message V2 `1501800078866911303`, dans le
salon `1501795550062710825`.

Le bouton « Faire une demande de salon privé » est accessible à Anyone, sans limite
d'appuis ni cooldown ; ses réponses sont privées. Cela correspond à une demande
publique d'aide, pas à un bouton réservé aux Helpers.

Le texte actuel explique l'alternative à l'aide en MP, indique une possibilité
d'orientation vers les salons d'aide classiques, et prévoit jusqu'à deux personnes
supplémentaires ajoutées sur demande. Cette limite doit être prise en compte dans
la gestion des invités, pas confondue avec le nombre de Helpers/Staff qui ont déjà
accès au titre de leur rôle.

**Texte à corriger :** le premier paragraphe présente le salon comme accessible au
membre et à un seul Helper désigné, puis évoque l'accès du Staff. Cette présentation
ne reflète pas la règle métier confirmée : tous les Helpers, Helpers+ et Staff
peuvent consulter les échanges pour conseil et supervision réciproque. Le panneau
et les informations du formulaire doivent annoncer le bon périmètre de confidentialité.

## Demande initiale

Le bouton vérifie `BGVAR_tat_hastat` pour l'utilisateur. Si la valeur vaut 1, un
message refuse l'ouverture et renvoie vers un salon de soutien supposé existant.
Sinon le formulaire `tatform` collecte trois champs :

- `tatform.motif` : « Pourquoi ouvrir un salon de soutien ? » ;
- `tatform.trigger` : « Il y a t-il des triggers et lesquels ? » ;
- `tatform.consentement` : case « Consentement ».

Le résumé de la case indique un booléen true/false. Son explication détaillée,
son caractère obligatoire et les bornes de longueur des réponses n'ont pas été
confirmés dans l'éditeur du formulaire, non ouvert. Ne pas inventer ce que couvre
actuellement ce consentement. Aucun branchement explicite sur ce booléen n'est
visible dans le diagramme, sans que cela prouve que le formulaire n'impose aucune
validation native.

Après l'envoi du formulaire, l'ordre observé est :

1. Réponse privée « Demande envoyée ! Un Helper la prendra en charge rapidement ».
2. `tat_hastat = 1` pour le demandeur.
3. Variables d'exécution `tatuserid = user_id`, puis `tatusername = user_name`.
4. Publication de la demande dans `1499496022529806446` : membre, motif, triggers,
   date, mentions Helper `1499491909750755570` et Helper+ `1500591187185242203`.
5. Menu de traitement « Accepter / Refuser ».

Il s'agit donc d'une **demande préalable**. Aucun salon de soutien n'est créé avant
son acceptation. Le même drapeau couvre néanmoins demande en attente et salon ouvert ;
le message anti-doublon peut annoncer à tort un salon existant à un membre qui attend
simplement une réponse.

## Acceptation et interlocuteur initial

Le menu de décision est actuellement configuré **Anyone**, sans limite d'utilisations,
avec réponses privées. La branche Accepter ne contient pas de garde de rôle explicite
avant la création. L'accès réel au message dépend du salon de traitement ; il ne faut
pas assimiler cette configuration à une publication accessible à tout le serveur.
Il faut néanmoins vérifier les rôles au moment de la décision.

La branche :

1. Édite le message de demande pour afficher l'acceptation et son auteur.
2. Crée `🌸・｜soutien-{tatusername}`, salon textuel dans la catégorie Soutien, avec
   sujet `Ticket de {tatusername}`, et sauvegarde son ID dans `tickid`.
3. Enregistre des variables du salon :
   `ticketv3_userid = tatuserid`, `ticketv3_msg = tatform.motif`,
   `ticketv3_trig = tatform.trigger`, `ticketv3_auth = user_id`.

`user_id` est ici l'auteur de l'acceptation : c'est ainsi que le membre qui accepte
devient l'interlocuteur initial affiché par l'événement central (« Ton Interlocuteur
est … »). Aucun choix d'un autre Helper n'est visible dans ce producteur.

Le bloc de création comporte six overwrites, dont un overwrite **de membre** visant
`tatuserid`. Les autres ciblent des rôles ; leurs IDs précis ne sont pas tous visibles
dans la portion rendue des sélecteurs. Valider les rôles configurés et l'accès collectif
avant toute activation, sans déduire un ID d'après l'ordre de ces overwrites.

La demande est marquée acceptée avant la confirmation de création et de sauvegarde.
Prévoir un état de traitement intermédiaire plutôt qu'un succès affiché trop tôt.
Deux décisions simultanées doivent être arbitrées atomiquement et ne créer qu'un salon.

L'écriture des variables suit la création : comme pour les autres familles, la pause
de deux secondes de l'événement central ne garantit pas leur disponibilité. La future
ouverture doit utiliser l'état enregistré du dossier et une publication idempotente.

## Refus et échec de notification

La branche Refuser vérifie le rôle `1503100661728936046`. Son message d'erreur le
présente comme le rôle autorisé à refuser et renvoie vers `1499495750151966862` pour
solliciter la coordination. Le MP de refus parle de la coordination des Helpers.

Avec ce rôle, un formulaire `refustat` demande `refustat.raison`, puis :

1. Envoie au demandeur un MP V2 indiquant le refus par la coordination et son motif.
2. Édite le message interne pour afficher la demande refusée, son auteur et sa date.

Aucun bloc remettant `tat_hastat` à zéro n'est visible dans cette branche. Un membre
refusé peut donc rester bloqué derrière le drapeau « déjà un salon » jusqu'à une
intervention extérieure. Il ne faut pas répliquer ce blocage dans la migration.

Le bloc de MP a « Ignore this block's errors » désactivé et pas de chemins distincts
succès/erreur. Un échec de livraison peut donc empêcher l'édition suivante. L'interface
signale par ailleurs une erreur attachée à ce bloc ; aucun code d'erreur n'est interprété
et aucun envoi réel n'a été lancé pendant l'analyse.

La décision et la libération du verrou doivent être persistées indépendamment du MP.
Un MP fermé doit produire un état de notification non remise, sans faire perdre le
refus ni laisser une demande indéfiniment en attente.

## Choix utilisateur confirmés

- **Seuls les Helpers et Helpers+ peuvent accepter et devenir interlocuteur principal.**
- Tous les Helpers, Helpers+ et Staff gardent accès en lecture aux échanges ; être
  interlocuteur principal ne donne jamais une exclusivité de visibilité.
- Le refus demeure motivé et réservé à la coordination selon le parcours observé.
- Après refus, le membre peut refaire une demande : **pas de blocage permanent**,
  avec protection anti-spam.
- Les réattributions manuelles effectuées dans Iris restent prioritaires lors des
  actualisations/imports. Conserver distinctement initiateur, acceptant initial et
  interlocuteur actuel ; ne pas réaffecter le ticket à l'acceptant d'origine à chaque
  synchronisation.

Le garde d'acceptation doit être distinct du garde de refus : exiger uniquement Helper
sur l'ensemble du menu ne doit pas empêcher un coordinateur autorisé à refuser d'exercer
ce droit. Revalider chaque action côté serveur, y compris après un changement de rôle.

## Préparation métier du futur moteur

Séparer au minimum demande enregistrée, en attente, acceptation en cours, salon ouvert,
refusée, clôturée, et étapes de notification. Conserver l'ID de la demande et du salon,
le motif, les triggers, l'information de consentement pertinente, les acteurs, les
références Discord et un historique auditable.

L'unicité porte sur une demande ou un salon de soutien actif par membre et serveur,
avec réservation atomique avant les effets. Une demande refusée libère cette unicité
mais pas les protections anti-spam. Une demande ne doit pas être annoncée comme livrée
à l'équipe avant que son enregistrement et sa notification soient assurés ; prévoir
une notification durable et reprenable si Discord est indisponible.

Le panneau d'ouverture, les listes Iris, les archives et les synchronisations doivent
appliquer la même politique de visibilité collective du soutien. Ne pas importer la
politique « Administrateurs/Responsables uniquement » des Contacts Staff confidentiels
vers les soutiens : ce sont deux besoins et deux périmètres distincts.

Les limites d'invités, les garde-fous de retrait de participants et les réouvertures
ne doivent pas permettre de masquer les échanges aux rôles de supervision autorisés.
Les accès de rôle restent indépendants des invités individuels.

## État de l'analyse

Aucun nouveau code de soutien n'est produit ou branché pendant cette lecture.
Les contraintes exactes du formulaire et le périmètre natif du consentement restent
à confirmer avant de reproduire les validations. Le choix d'un délai anti-spam précis
n'a pas été demandé à l'utilisateur ; il reste une option de configuration à fixer,
sans inventer une sanction automatique ni un refus permanent.

Les autres producteurs `/panel support` et `/panel salon-aide` restent à examiner
pour déterminer leur lien éventuel avec ce circuit et les salons d'aide.

État final vérifié : « Saved », Undo et Redo désactivés ; aucune modification
fonctionnelle, sauvegarde de configuration ou exécution de test Discord.
