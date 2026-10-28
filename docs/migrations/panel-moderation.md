# /panel moderation — création des convocations et bulles

Analyse en lecture du constructeur OasisBot le 28 octobre 2026 : 99 blocs et
112 connexions rendus. Aucun appel « Test », lancement de commande, envoi de MP ou
création de salon n'a été exécuté. Pas de code de migration produit dans ce lot.

## Publication et parcours opérateur

La commande de publication `/panel moderation` est réservée au rôle Administrateur.
Ses réponses sont privées. Elle actualise un message Components V2 existant :
salon `1488260105039511622`, message `1555297812223230014`.
Le texte annonce une actualisation horaire, mais le mécanisme de planification n'a
pas été examiné dans cette commande ; ne pas conclure qu'il est réalisé ici.

Le panneau propose un sélecteur natif de membre, un seul choix, enregistré dans
`choix_staff`. Ce sélecteur est configuré Anyone, mais sa suite contrôle effectivement
les rôles de l'exécutant : Administrateur `1321630097744199721`, Opérateur
`1321629751840084040` ou Opérateur en formation `1323371858686382100`.
Ses réponses sont privées (« Only them »). Ce garde diffère du rôle Staff générique :
conserver la distinction entre publication du panneau et utilisation du parcours.

Après ce contrôle, le parcours efface la collection `ticket_creation` de l'exécutant,
puis ouvre `convocation`, formulaire à deux champs :

- `convocation.raison` : raison de l'échange ;
- `convocation.bulle` : case « Ouvrir une bulle ? », booléen.

Les contraintes détaillées de longueur et d'obligation du formulaire n'ont pas été
confirmées dans son éditeur. L'identité provient du sélecteur précédent et non d'un
champ ID du formulaire.

Un message de vérification privé est créé, puis édité au fil du traitement.

## Contrôles et lecture du casier

Le parcours vérifie les rôles de la cible (Non validé, Membre, Mute), puis protège les
rôles Administrateur, Opérateur et Opérateur en formation. Une cible ainsi protégée
nécessite un exécutant Administrateur, sauf branche de simulation décrite plus bas.

Le contrôle de secours d'identifiant numérique emploie `choix_staff`, mais un ancien
contrôle de permissions conserve `{convocation.id}`, qui n'apparaît plus dans le
formulaire à deux champs. Remplacer cette chaîne de déductions par une recherche
réelle du membre dans le serveur ; l'absence de certains rôles/permissions ne prouve
pas qu'un membre a quitté le serveur.

Deux blocs HTTP GET vers l'API de modération Iris récupèrent le casier, sous les noms
`aaa` et `bbb`, selon la branche. Les modèles affichent :

- `response.sanctions_markdown` ;
- `response.has_active_fiche_s`, traduit en texte par `tmpfiche` ;
- membre, motif, puis boutons de préparation.

L'écran est intitulé Module Administrateur pour la cible protégée traitée par un
Administrateur ; Module Opérateur pour la cible ordinaire. Aucune requête API n'a
été testée ni aucun secret d'authentification recopié dans cette fiche.

## Simulation héritée

Pour les cibles protégées, un motif contenant `test` ou `Test` conduit vers un écran
« Mode de test actif ». Il utilise encore le compteur historique
`BGVAR_avertissement_num` au lieu du nouveau casier Iris.

Le bouton « Mettre en interdiction » de cette branche rejoint une note indiquant
qu'il est désactivé en test. Le diagramme relevé ne montre aucune suite reliée au
bouton de convocation de cet écran de test : ne pas prétendre qu'il crée réellement
un salon ou qu'il contourne les protections sur une action réelle.

Pour la migration, préférer un mode formation explicite à la détection du mot `test`
dans un motif ordinaire. Les simulations ne doivent jamais appliquer les permissions,
créer une sanction ou devenir des décisions réelles dans les statistiques.

## Création des deux familles

Les deux boutons réels de convocation (écrans Opérateur et Administrateur) rejoignent
le même test de `convocation.bulle` :

| Case bulle | Salon textuel créé | Catégorie |
| --- | --- | --- |
| Faux | `🚧・｜convoc-{user_displayName[{choix_staff}]}` | Contact Staff |
| Vrai | `🫧・｜bulle-{user_displayName[{choix_staff}]}` | Contact Staff |

Chaque bloc conserve l'ID du nouveau salon dans `convid`. La suite écrit, dans cet
ordre, des variables **du salon** :

1. `ticketv3_userid = choix_staff` ;
2. `ticketv3_msg = convocation.raison` ;
3. `ticketv3_auth = user_id` de l'intervenant.

Puis `convlink = convid` est enregistré **pour le membre concerné**.
La portée de `ticketv3_auth` est donc bien configurée par salon, et non comme un
stockage global unique. Cela précise le point encore incertain de l'analyse de
l'événement central.

L'événement `When a channel is created` repère ces deux marqueurs après sa pause de
deux secondes. La création précède les trois écritures : cette attente fixe n'est
pas une garantie de disponibilité des métadonnées. La migration doit initialiser le
dossier puis publier son panneau à partir de cet état, avec idempotence, sans course
entre deux flux indépendants.

### Permissions à corriger ou confirmer

Les deux blocs de création comportent quatre overwrites. Le quatrième est configuré
**A role / ID or variable**, avec `{choix_staff}` dans **Role ID or variable**, alors
que `choix_staff` est l'ID d'un membre choisi dans le sélecteur natif. C'est une
incohérence de type visible : l'accès individuel doit être un overwrite de membre.
Aucune création n'a été exécutée pour provoquer ou confirmer une erreur HTTP.

Les rôles précis des trois autres overwrites ne sont pas confirmés par la portion
rendue des sélecteurs de rôles. Ne pas inventer leurs IDs. Vérifier la visibilité de
l'exécutant, du membre concerné et des rôles de supervision avant toute activation.

Les boutons réels de préparation sont configurés Anyone, sans limite ni cooldown.
Ils apparaissent dans un parcours privé ; cela ne signifie pas que le panneau est
accessible à tous. Revalider toutefois les droits actuels, l'auteur de la session et
l'état du dossier au moment du clic, puis empêcher les doubles créations.

## Notification privée, actuellement distincte de la création

« Informer en MP » est une action séparée ; la création du salon ne mène pas
automatiquement à ce bouton. Le parcours :

1. Vérifie que `BGVAR_convlink[choix_staff]` est non vide ;
2. choisit le texte selon la case bulle ;
3. envoie le MP au membre sélectionné ;
4. envoie un retour à l'intervenant.

Avant création, un message exige l'ouverture préalable d'une convocation. La présence
d'un lien en variable ne garantit pas que le salon existe encore : vérifier le salon
réel, son type et son lien au membre avant notification, surtout après une clôture.
Dans l'événement central, `convlink` est momentanément remplacé par `1` à la clôture ;
un simple test « non vide » accepte aussi ce marqueur temporaire.

Le MP de convocation annonce trois jours pour répondre avant une sanction automatique.
Aucun déclencheur différé de sanction n'est visible dans ce parcours. Le MP de bulle
précise qu'il n'y a pas de problème et invite à un échange, sans menace de sanction.
Préserver cette différence de ton.

### Boutons Purgatoire

Les écrans réels proposent « Envoyer au Purgatoire », configuré Runs blocks, mais les
liaisons du diagramme relevé n'indiquent pas de suite raccordée à ces deux boutons.
Il ne faut pas les présenter comme une action fonctionnelle sur la seule présence du
libellé. Le rôle et le fonctionnement de `/purgatoire` restent à analyser séparément.

## Choix utilisateur confirmés pour la migration

- Trois jours sans réponse à une convocation : **alerte au Staff, décision humaine**.
  Corriger le texte du MP qui annonce aujourd'hui une sanction automatique.
- Étendre la protection des cibles à **tous les membres ayant le rôle Staff** : seul
  un Administrateur peut les convoquer. La migration doit appliquer ce contrôle aux
  deux modes d'ouverture, et pas seulement aux trois rôles listés actuellement.
- Bulle : même mécanique de discussion privée, présentation rassurante pour un membre
  qui n'a rien fait de mal. Aucun motif disciplinaire implicite dans son affichage.
- Règles déjà retenues pour l'ensemble des tickets : intervenant principal
  réattribuable ; restauration des participants à la réouverture ; visibilité de
  tous les soutiens pour tous les Helpers, Helpers+ et Staff.

## Incident d'interface pendant l'analyse

L'ouverture des propriétés de l'ancien écran de test a fait apparaître une
modification dans le constructeur, sans saisie d'un champ. La lecture a été arrêtée
immédiatement et l'unique modification a été annulée (Undo redevenu désactivé).
La sauvegarde de l'état rétabli a d'abord été bloquée par le contrôle automatique,
car le périmètre autorisé était une lecture seule. L'utilisateur a ensuite autorisé
explicitement **uniquement la sauvegarde de l'état rétabli**, sans autre modification.
La sauvegarde de l’état rétabli a été vérifiée dans l’en-tête : « Saved », Undo
désactivé. Aucune modification fonctionnelle volontaire n’a été ajoutée.
Les anciens éditeurs susceptibles de normaliser des données ne seront pas rouverts
pour compléter des détails sans nécessité.

## Suite de l'analyse

Cette commande établit le lien complet producteur → variables de salon → événement
pour convocation/bulle. Il reste à examiner `/panel contact-staff`, `/panel soutient`
et les autres producteurs pertinents, ainsi que le mécanisme éventuel d'actualisation
horaire. Aucune activation du code préparé ni modification fonctionnelle de la commande
BotGhost n'est prévue pendant cette phase d'analyse.
