# Atelier des projets animateurs

La refonte conserve les identifiants, briefs BlockNote, membres, tâches et fichiers existants. Aucun script de migration de contenu n'est nécessaire. Les champs ajoutés sont facultatifs avec priorité normale par défaut. Redéployer le backend et le frontend ensemble.

## Parcours

- **Carnet** `/animateur/projects` : projets en cours, terminés et archivés, recherche par nom/description/étiquette/membre, priorité, participation et tri. Progression = tâches validées / total ; les rendus ne sont pas comptés comme validés. Le panneau personnel affiche les tâches des projets en cours.
- **Fiche** : vue d'ensemble, tableau à quatre colonnes ou liste des tâches, brief partagé, équipe, fichiers et journal. Les éditeurs de rendu ne sont montés qu'à l'ouverture d'une tâche.
- **Calendrier** `/animateur/calendrier` : jalons de début/fin et échéances, mois ou agenda, filtres projet/personnel/éléments clos. Export `.ics` du mois filtré, journées entières avec fin exclusive ; c'est une copie, pas un abonnement synchronisé. Les dates du module sont des dates civiles et le jour courant suit Europe/Paris.

## Droits et cycle de vie

Le rôle Animateur ou Responsable suffit pour le nouvel espace, sans exiger le rôle Staff. Les anciens accès de lecture/fichiers Staff restent compatibles. Un animateur peut consulter les projets et rejoindre une équipe ; ajouter un autre membre nécessite d'être pilote ou responsable global, et la cible est vérifiée auprès de Discord.

Le **pilote** est le créateur. Lui et les responsables globaux gèrent paramètres, membres, tâches, validation et fichiers. La suppression définitive d'un projet reste réservée aux responsables globaux. Les membres peuvent modifier le brief, déposer des fichiers, écrire au journal et travailler sur leurs propres tâches.

Les tâches passent de « À faire » à « En cours », puis « À valider » via un rendu, enfin « Validée » par le pilote. Un blocage est une information distincte du statut. Une correction ou réouverture exige une consigne. Les fichiers du rendu précédent sont conservés si aucun nouveau fichier n'est déposé. L'ancien droit de correction d'un rendu par un responsable global est conservé.

Terminer un projet exige que toutes les tâches soient validées. Projets terminés et archives sont consultables ; rouvrir/restaurer avant d'y travailler. Un membre avec des tâches ouvertes doit être réattribué avant retrait. Le créateur ne peut être retiré. Réouvrir une ancienne tâche d'un membre retiré exige une attribution à un membre actuel dans le formulaire de correction.

## API et données

`GET /animateur/projects/workspace/overview` agrège les compteurs en MongoDB sans requête par projet. `PATCH /projects/{id}/settings` et `/brief` sont partiels pour éviter qu'un enregistrement du brief écrase les paramètres. `PATCH /tasks/{id}` contrôle les changements selon le rôle et compare `updated_at` pour détecter une modification concurrente. Les autres routes d'uploads et de rendus sont conservées, avec les limites de taille et les téléchargements sécurisés existants.

Le carnet charge les 500 projets les plus récemment modifiés et au maximum 500 tâches personnelles. Le calendrier charge 500 projets et 5 000 tâches ; un avertissement signale une troncature. Les projets et la liste des tâches sont paginés par huit éléments ; le volet personnel par cinq. Le tableau conserve toutes les tâches filtrées, avec défilement dans chaque colonne pour limiter la hauteur de page. Les listes détaillées conservent les limites historiques (500 tâches, 200 ressources).

Le journal présente les 100 dernières notes/actions fusionnées, uniquement aux membres et responsables globaux. Les notes sont persistées dans `project_notes` jusqu'à suppression du projet. Les actions viennent de `auth_logs`, soumis à sa rétention habituelle. La projection du journal exclut IP, navigateur et données techniques. Les nouvelles écritures sont également auditées et libellées dans les logs responsables. Les index sont créés au démarrage sans bloquer sur un conflit historique.

Les suppressions de tâches/ressources/projets retirent les références MongoDB comme auparavant ; les objets binaires déjà stockés ne font pas l'objet d'une purge physique automatique.

## Vérification

Tests hors ligne : `backend/tests/test_project_workspace.py`, régressions fichiers et logs, `ProjectsWorkspace.test.jsx`, `projectUtils.test.js`, puis compilation de production. Aucun envoi Discord ni screenshot de rendu.


## Audit exhaustif des parcours du module

Les écritures métier restent journalisées côté serveur (création, brief, paramètres, état du projet, membres, tâches, blocages, corrections, rendus, validations, fichiers et notes). Les résumés responsables détaillent les champs modifiés et les valeurs avant/après en français.

Les routes du module utilisent `ProjectAuditRoute` : consultations des collections, du calendrier et du journal, téléchargements de ressources/rendus, refus de permissions, erreurs de validation et échecs internes d'une session identifiée sont audités. Les erreurs de streaming survenant après l'ouverture d'une réponse peuvent rester dans les logs techniques du serveur ; un téléchargement journalisé décrit la réponse servie, pas sa réception complète par le navigateur.

Le périmètre de l'interface (`.pj-page`, dialogues et éditeurs du module) enregistre clics, navigation, onglets, pagination, filtres/champs validés, envois de formulaires, annulations/confirmations, volets, raccourcis et sortie d'éditeur. Ces événements `project.ui.*` portent explicitement `source=client` ; ils décrivent une interaction, jamais une preuve de réussite métier. Les textes des champs et éditeurs ne sont pas recopiés dans ces événements : seules leur taille et les sélections de filtres sont enregistrées. La capture est retirée en quittant le module. L'envoi d'interactions dépend de la connexion du navigateur.

Le journal d'équipe exclut les événements d'interface, consultations répétées et refus ; les responsables disposent de l'ensemble dans les logs IRIS.


## Modèles, checklists et bilan

**Modèles.** Trois modèles de départ (soirée jeux, débat/échanges, concours) sont proposés dans Nouveau projet avec un aperçu des tâches. Le pilote ou un responsable global peut aussi enregistrer un projet existant comme modèle partagé, y compris depuis une archive. Ce geste ne modifie pas l'archive. Le modèle conserve brief, description, étiquettes et structure de 50 tâches au maximum. Il ne reprend ni les participants au projet, ni rendus, pièces jointes, notes d'équipe ou bilan. Les références d'images déjà présentes dans le brief restent des références au contenu existant.

Les tâches générées sont attribuées au créateur et repartent à faire, avec de nouveaux identifiants et cases décochées. Leurs échéances conservent un décalage par rapport à la fin prévue (ou au début en l'absence de fin), sans précéder le début du nouveau projet. Les insertions partielles font l'objet d'un nettoyage compensatoire en cas d'erreur. Supprimer un modèle personnalisé, réservé à son auteur ou à un responsable global, ne supprime aucun projet créé avec lui. Les modèles intégrés sont protégés. Le catalogue affiche les 200 modèles personnalisés les plus récents et envoie seulement un aperçu, sans charger tous les briefs.

**Checklists.** Le formulaire de tâche permet d'ajouter, renommer et retirer jusqu'à 50 étapes. Le pilote gère cette structure. Le membre attribué et le pilote peuvent cocher/décocher une étape tant que le projet et la tâche sont ouverts. Toutes les étapes doivent être cochées avant l'envoi du rendu, avec contrôle serveur. Les tâches historiques sans checklist gardent leur fonctionnement. Les mutations de cases et le formulaire d'édition comparent la version de tâche pour refuser les écrasements concurrents.

**Bilan.** L'onglet Bilan rassemble date, nombre de participants (zéro est une valeur valide), réussites, pistes d'amélioration et idées pour la prochaine fois. Le pilote et les responsables globaux peuvent le préparer et le modifier sur un projet actif ou terminé. Une archive est en lecture seule jusqu'à restauration. Le bilan porte auteur et date de modification et refuse une écriture basée sur une version dépassée. Le formulaire conserve le brouillon en cas d'erreur et permet de recharger le bilan en cas de conflit.

Les nouveaux gestes sont inclus dans les interactions d'interface et les logs métier : modèle enregistré/appliqué/supprimé, étape cochée/décochée, structure modifiée et bilan avant/après. Aucun nouveau secret, rôle Discord ou variable d'environnement n'est nécessaire. Déployer frontend et backend ensemble.

## Déroulé de l’animation

L'onglet Déroulé propose une chronologie paginée par huit séquences, un éditeur à hauteur limitée, une trame accueil/animation/clôture et un export texte. Le pilote et les responsables globaux modifient date, heure de départ (Paris), ordre, titres, durées, intervenants et consignes. Les horaires sont recalculés par addition des durées ; les dates réelles apparaissent lors des passages à minuit, aux changements de mois et d’année. Sans date choisie, J+N indique le décalage en jours. Il s'agit d'un programme prévisionnel en heures civiles, sans minuteur ou déclenchement automatique.

Le plan contient au maximum 50 séquences, avec une durée positive en minutes entières ; chaque séquence et le déroulé complet peuvent s’étendre sur plusieurs jours. La saisie propose jours, heures et minutes, et chaque séquence affiche ses dates et heures de début et de fin. Le serveur contrôle que la date de fin reste dans la plage de dates représentable. Les identifiants sont uniques et chaque intervenant choisi est vérifié dans l'équipe. Réattribuer les séquences est nécessaire avant de retirer leur intervenant du projet. Le projet actif est modifiable ; les projets terminés ou archivés restent consultables et exportables jusqu'à réouverture/restauration.

`PUT /projects/{id}/rundown` refuse un conflit de version du déroulé ou une modification concurrente du projet. Les ajouts, suppressions, réordonnancements et consignes sont audités avant/après, avec leur auteur ; les interactions restent capturées dans les logs d'interface. Le brouillon est conservé en cas d'erreur et un bouton permet de recharger la version du serveur. Aucun script de migration n'est nécessaire pour les anciens projets.

Les modèles personnalisés conservent l'heure et la structure du déroulé ; à l'application, la date reprend le début du nouveau projet, les identifiants sont régénérés et les intervenants restent à attribuer. Aucun contenu de déroulé n'est ajouté aux chargements groupés du carnet ou du calendrier. Déployer le backend et le frontend ensemble.

Les durées du déroulé suivent le calendrier civil en heure de Paris : une séquence de deux jours conserve son horaire local deux dates plus tard. Les anciens déroulés stockés en minutes sont conservés sans migration, y compris dans les modèles et les logs.
