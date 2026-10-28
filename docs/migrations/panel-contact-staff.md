# /panel contact-staff — analyse du producteur Contact Staff

Lecture du constructeur OasisBot le 28 octobre 2026 : 21 blocs et 19 connexions
rendus. Aucun code applicatif produit, aucune commande exécutée et aucun salon créé.
Les paramètres ont été consultés sans saisie dans les champs de configuration.

## Publication du panneau

La commande `/panel contact-staff` est réservée au rôle Administrateur ; ses réponses
sont privées. Elle actualise le message V2 `1470532624887054596`, dans le salon
`1081957993492533364`.

Le texte public présente trois motifs non exclusifs : signalement d'un comportement
ou problème, discussion/contestation d'une sanction, autres questions ou demandes.
Il précise qu'un salon privé sera ouvert et que d'autres participants pourront être
ajoutés selon la situation. Le bouton « Contacter le Staff » est accessible à Anyone,
sans cooldown ni limite d'appuis ; les réponses de son parcours sont privées.

L'accès public à ce bouton est cohérent avec la fonction de contact : ne pas le
remplacer par un garde Staff lors de la migration. Les gardes Staff/administration
concernent les actions de gestion du dossier.

## Formulaire et prévention des doublons

Le bouton rejoint un contrôle de `BGVAR_cstaffv3_hastick`, pour le membre exécutant.
La branche graphique `== 1` mène au refus indiquant qu'un Contact Staff existe déjà
et que d'autres thématiques peuvent être abordées dans celui-ci. L'autre branche
ouvre `cstaff`, formulaire à deux champs :

- `cstaff.raison` : « Pourquoi souhaites-tu ouvrir un contact staff » ;
- `cstaff.adm` : case « Discuter avec un administrateur ».

Les contraintes exactes de longueur et d'obligation n'ont pas été relevées dans
l'éditeur du formulaire. Il n'a pas été ouvert pour éviter les normalisations
involontaires constatées sur certains anciens éditeurs BotGhost.

Le contrôle d'ouverture a lieu avant le formulaire. Le drapeau est écrit seulement
après la création du salon et l'enregistrement de ses métadonnées. Il n'y a pas de
seconde vérification ni de réservation atomique visible après l'envoi du formulaire.
Deux formulaires ouverts en parallèle peuvent donc passer ce premier contrôle avant
que le premier ne positionne le drapeau : c'est un risque de concurrence déduit de
l'ordre des blocs, pas un double ticket provoqué pendant l'analyse.

Le drapeau vaut 1 et ne conserve pas l'ID du salon. Il ne permet pas à lui seul de
retrouver un ticket ou de vérifier qu'il existe encore. La réinitialisation à 0 se
trouve dans la fermeture Contact Staff de l'événement central, déjà documentée.

## Deux variantes, une même famille

| Choix du formulaire | Salon créé | Variable de retour |
| --- | --- | --- |
| Administrateur non coché | `🎫・｜cstaff-{User.displayName}` | `tickid` |
| Administrateur coché | `⚜️・｜cstaff-{User.displayName}` | `created_channel_564f` |

Les deux salons sont textuels, créés dans la catégorie Contact Staff. Leur sujet est
`Contact Staff de {User.displayName}`. Chaque branche écrit ensuite :

1. `ticketv3_userid = user_id`, pour le nouveau salon ;
2. `ticketv3_msg = cstaff.raison`, pour le nouveau salon ;
3. `cstaffv3_hastick = 1`, pour le membre demandeur.

Aucun `ticketv3_auth` n'est défini ici : le membre contacte une équipe, avec prise en
charge ultérieure, contrairement à une convocation initiée par un intervenant.
L'événement central reconnaît les deux marqueurs, leur attribue `ticktype=1` et
publie le panneau Contact Staff correspondant.

Les suites des deux branches s'arrêtent sur le drapeau ; aucun bloc explicite de
confirmation finale avec lien vers le nouveau salon n'est visible. Prévoir cette
confirmation dans le nouveau parcours, une fois la création et les accès confirmés.

## Permissions constatées et limites du relevé

Le salon classique comporte quatre overwrites et la variante Administrateur cinq.
Dans les deux, l'accès individuel du demandeur est correctement configuré comme
**A member**, avec `{user_id}`, permettant notamment lecture, écriture et fichiers.
C'est différent de l'incohérence ID membre / champ ID de rôle relevée dans les deux
créations de `/panel moderation`.

Les autres overwrites ciblent des rôles ; leurs IDs précis ne sont pas tous visibles
dans la portion rendue des sélecteurs. Ne pas conclure à leur identité d'après leur
ordre. Le rôle de confidentialité doit être établi à partir des choix métier
ci-dessous et des rôles configurés, puis vérifié avant activation.

## Choix utilisateur confirmés

- Variante classique : Contact Staff ordinaire.
- Case « Discuter avec un administrateur » : accès au **membre concerné, aux
  Administrateurs et aux Responsables**, et non à l'ensemble du Staff.
- **Un seul Contact Staff ouvert par membre**, toutes variantes confondues.
  Si le membre souhaite un contact confidentiel alors qu'un classique est ouvert,
  il faut d'abord clôturer le premier. Pas de deuxième ticket parallèle ni de
  transfert automatique du dossier existant.

Cette confidentialité doit être maintenue lors des prises en charge, ajouts de
participants, suspensions, réouvertures et levées de restriction. Un rôle Staff
générique ne doit pas suffire pour gérer une variante confidentielle. Si un
intervenant perd les droits nécessaires, son attribution ne lui conserve pas l'accès.

Elle doit aussi couvrir les archives et Iris : liste, réponses, fichiers, recherche,
vue membre 360° et liens de transcription. L'événement existant classe les deux
variantes comme Contact Staff et utilise la même destination d'archive ; ses droits
et ceux de l'URL de transcription doivent être vérifiés pour ne pas divulguer un
contact confidentiel par son archive. Ne pas réutiliser aveuglément les droits d'un
ticket ordinaire pour cette variante.

La règle de visibilité collective des **soutiens** reste distincte : Helpers,
Helpers+ et Staff conservent leur droit de regard sur tous les échanges de soutien.

## Simplifications envisagées avant code

Un producteur unique peut créer un dossier `contact_staff` avec un niveau de
confidentialité explicite, puis préparer le salon et son panneau. Les deux variantes
partagent le formulaire et les données sans copier deux chaînes de blocs.

L'unicité doit porter sur membre + serveur + famille Contact Staff, y compris pendant
une création en cours ou une suspension non clôturée. Stocker l'ID réel du salon,
prévoir une création idempotente et un état réparable si la création ou la sauvegarde
échoue. Un dossier incohérent ne doit ni produire des doublons ni bloquer indéfiniment
le membre derrière un drapeau devenu obsolète.

Les préfixes et le panneau demeurent lisibles ; les droits et la famille du dossier
en base restent la référence lors des renommages et des synchronisations Iris.
Le délai fixe de deux secondes de l'événement central ne doit plus servir de seule
garantie que les métadonnées ont été enregistrées.

## État et suite

Analyse seulement. Aucun test Discord ou modification fonctionnelle du panneau.
La suite naturelle est `/panel soutient`, pour comprendre la demande, l'attribution
d'un interlocuteur et la collecte des triggers, puis les autres producteurs utiles.
