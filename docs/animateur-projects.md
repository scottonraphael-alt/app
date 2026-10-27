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
