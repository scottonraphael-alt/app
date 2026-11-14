# Solitaire et Sudoku dans OasisGame

Deux jeux individuels sont accessibles depuis le menu. L’hôte choisit le jeu de la salle ; chaque participant joue ensuite sur son propre plateau, indépendamment de l’hôte. Aucune carte, grille ou progression individuelle n’est envoyée aux autres joueurs.

## Solitaire Klondike

52 cartes, 7 colonnes, 4 fondations par famille. Les colonnes acceptent une carte ou une suite visible, par couleurs alternées en ordre décroissant. Seul un roi ouvre une colonne vide. La dernière carte cachée est automatiquement retournée lorsqu’elle est libérée.

Les fondations vont de l’as au roi dans la même famille. Il est possible de reprendre leur carte supérieure vers une colonne. La pioche distribue 1 ou 3 cartes au choix pour la nouvelle donne ; seule la carte supérieure de la défausse est jouable. Quand la pioche est vide, la défausse peut être retournée sans limite, en conservant son ordre de distribution.

Les déplacements se font par clic : sélectionner une carte ou une suite puis cliquer sa destination. L’interface fonctionne au toucher et avec les boutons accessibles au clavier. Un bouton permet de désélectionner. Indice repère un déplacement légal depuis la défausse ou une colonne, sans garantir une stratégie gagnante. Les donnes sont aléatoires et ne sont pas garanties gagnables. La victoire nécessite les 52 cartes sur les fondations.

## Sudoku

Grille 9 × 9, avec chiffres fixes et solution unique vérifiée par recherche de solutions lors de la génération. Les niveaux Douce, Équilibrée et Corsée visent respectivement 36, 45 et 50 cases vides, en conservant l’unicité. Ce sont des niveaux de densité d’indices, sans classement par technique humaine ; si retirer davantage de cases compromet l’unicité, certaines restent remplies.

Cliquer une case puis un chiffre, ou utiliser les flèches et les touches 1–9. Supprimer, Retour arrière ou 0 efface une case modifiable. Le mode Notes permet de poser et retirer des candidats. Placer un chiffre efface les notes de cette case et ce candidat dans ses cases voisines. Les conflits de ligne, colonne ou carré sont signalés en rose.

Vérifier compare les chiffres saisis à la solution. Indice complète la case sélectionnée si elle est incorrecte ou vide, sinon une autre case incomplète. Les aides sont comptées. Une grille complètement correcte déclenche la victoire.

## Sauvegarde et pause

Les plateaux sont calculés côté navigateur, adaptés au solo sans classement compétitif. La sauvegarde `localStorage` est séparée par compte Discord et par jeu. Elle conserve la partie, les aides utilisées, le chrono et jusqu’à 100 actions annulables. Une sauvegarde mal formée est ignorée. Si le navigateur refuse le stockage, un message indique que seule la session ouverte conserve la partie.

Le chronomètre ne compte que le temps de jeu affiché : il s’arrête en pause, lorsque la page est masquée, après la victoire et quand le composant n’est pas affiché. Annuler ne remet pas le chrono à zéro, ne supprime pas les aides déjà utilisées et compte comme un coup au Solitaire. Ouvrir les règles met la partie en pause. Commencer une nouvelle partie demande confirmation, puis remplace la sauvegarde locale.

Changer de navigateur ou d’appareil, ou effacer les données du site, supprime l’accès à cette sauvegarde. Les autres membres ne peuvent pas contrôler une partie individuelle. Revenir au menu change le jeu de toute la salle, mais conserve les sauvegardes individuelles.

## Déploiement

Aucune dépendance ou variable d’environnement supplémentaire.

```bash
cd /home/iris/app
git pull --ff-only origin codex/botghost-integration
docker compose up -d --build --no-deps backend frontend
```

Fermer puis relancer OasisGame. Vérifier les deux jeux depuis deux comptes : les progressions doivent rester indépendantes. Quitter puis revenir sur le même navigateur doit restaurer la partie.
