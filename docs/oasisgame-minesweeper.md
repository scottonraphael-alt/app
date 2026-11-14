# Démineur dans OasisGame

Le menu propose **Démineur → Explorer la grille**. L’hôte règle la difficulté et
le mode ; les membres choisissent **Participer**, puis l’hôte lance la partie.
Le jeu utilise le fond sombre, les cartes arrondies, les accents menthe et lilas
et les sons discrets d’OasisGame.

| Difficulté | Grille | Mines |
| --- | --- | --- |
| Découverte | 9 × 9 | 10 |
| Intermédiaire | 16 × 16 | 40 |
| Expert | 30 × 16 | 99 |

## Modes et règles

En **solo**, une seule place est disponible ; les autres membres peuvent regarder.
En **coopération**, jusqu’à huit participants explorent la même grille, y compris
en rejoignant une partie en cours. Une mine déclenchée termine la partie de toute
l’équipe. La victoire demande de découvrir toutes les cases sûres, pas de poser
tous les drapeaux. Les contributions comptent les cases découvertes par chaque joueur.

- Cliquer une case pour la découvrir. Les zones vides s’ouvrent automatiquement.
- Clic droit, touche **F** ou **Espace** : poser ou retirer un drapeau.
- Sur mobile, activer le bouton **Drapeau**, puis toucher une case.
- Un chiffre indique le nombre de mines dans ses huit voisins. Cliquer ce chiffre
  découvre les voisins non marqués si le nombre de drapeaux correspond. Des drapeaux
  incorrects peuvent donc provoquer une défaite.
- Les flèches permettent de parcourir la grille au clavier et **Entrée** de jouer.

Le premier clic déclenche le tirage des mines, en excluant sa case et tous ses
voisins. Le chronomètre démarre à ce moment. Le tirage n’est pas garanti sans
devinette après cette ouverture ; les règles de l’interface le précisent.

Les grandes grilles défilent horizontalement à l’intérieur de leur cadre, en gardant
des cases lisibles sur mobile. Les états de victoire et de défaite montrent les mines
et identifient les drapeaux incorrects. L’hôte peut rejouer avec un nouveau tirage ou
revenir aux réglages. Quitter une partie pour le menu demande confirmation.

## Synchronisation

Le backend est la source de vérité pour le tirage, les découvertes, les drapeaux,
les résultats et le temps. Aucun emplacement de mine cachée ni graine aléatoire
n’est envoyé aux joueurs ou aux spectateurs avant la fin de partie. Chaque coup
doit citer la bonne manche et la bonne révision ; un coup ancien ne peut pas
retirer un drapeau ou révéler une case dans une grille plus récente.

Si un participant quitte une partie coopérative, les autres continuent. Lorsque
plus aucun participant n’est connecté, le chronomètre se suspend. Le retour d’un
joueur dans les deux minutes restaure la même grille et reprend le chronomètre
sans compter la pause. Au-delà, la partie est terminée comme abandonnée. Les spectateurs ne
maintiennent pas artificiellement le chronomètre actif.

Les salles suivent le fonctionnement existant des jeux de plateau : état en mémoire
dans une seule instance backend ; un redémarrage du backend ne restaure pas la partie.
Les invitations automatiques utilisent le panneau pastel et le lien vérifié existants,
uniquement pour une table coopérative qui attend encore des joueurs.

## Déploiement et contrôles

Aucune nouvelle dépendance ni variable d’environnement n’est nécessaire. Après avoir
poussé le commit, dans `/home/iris/app` :

```bash
git pull --ff-only origin codex/botghost-integration
docker compose up -d --build --no-deps backend frontend
```

Fermer et relancer l’Activity pour charger le nouveau menu.

Les tests couvrent les tailles, la protection du premier clic, le tirage, les chiffres,
l’ouverture des zones, les drapeaux, les découvertes autour d’un chiffre, la victoire,
la défaite, les actions malformées ou périmées, les droits, la limite de huit joueurs,
les contributions, le chronomètre et la reconnexion. Un test à deux WebSockets vérifie
la grille commune et la reprise. Les tests React couvrent le menu, le clavier, le clic
droit, les commandes tactiles, les spectateurs, les réglages et les confirmations.

Le rendu est contrôlé à 1180 px et 390 px, y compris le défilement du mode Expert.
Les captures de présentation utilisent le composant réel avec une grille locale de
démonstration ; aucun message ou partie de test n’est créé sur le serveur Discord.
