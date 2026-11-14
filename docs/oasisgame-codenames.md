# Codenames dans OasisGame

Mission de mots pour 4 à 16 joueurs : deux équipes, un maître-espion et de 1 à 7 agents par équipe. L’interface suit la charte sombre et pastel d’OasisGame. Référence demandée : https://codenames.game/. Les 493 mots français sont une sélection locale propre au projet, sans service externe ni images du jeu commercial.

## Déroulement

Les joueurs choisissent leur équipe et leur rôle avant le lancement par l’hôte. Les rôles sont ensuite verrouillés. Seuls les maîtres-espions reçoivent la clé complète ; les agents et les spectateurs reçoivent uniquement les couleurs révélées. Même un hôte agent ne reçoit pas la clé. Les maîtres-espions peuvent masquer leur clé et doivent éviter de partager leur écran.

La première équipe a 9 agents, l’autre 8. Il y a aussi 7 neutres et un assassin. Le maître-espion donne un mot et un nombre. Le serveur refuse les mots encore cachés sur la grille, en normalisant accents et ligatures. Les équipes restent responsables de juger les associations et les dérivés évidents.

Un bon choix permet de continuer jusqu’au nombre indiqué plus un essai bonus. Les indices 0 et ∞ autorisent des essais sans limite. Un neutre ou un agent adverse termine le tour ; l’agent adverse compte pour son équipe. Révéler l’assassin fait perdre immédiatement. Retrouver tous ses agents fait gagner.

Les agents peuvent proposer une carte sans la révéler. Une confirmation distincte engage la révélation. Il faut au moins un essai pour terminer volontairement le tour. Le carnet conserve les indices et les révélations publiques.

## Options et reconnexion

L’hôte choisit l’équipe de départ ou le hasard, et un chrono facultatif de 1, 2, 3 ou 5 minutes par phase (indice puis essais). À expiration, le tour change.

Une équipe peut continuer si son maître-espion et au moins un agent restent connectés. Sinon la mission se met en pause pendant 120 secondes. À expiration, une équipe complète gagne par forfait ; si les deux équipes sont incomplètes, la mission se termine sans vainqueur.

Les victoires sont conservées entre les nouvelles missions. L’hôte peut aussi recomposer les équipes. Comme les autres jeux en mémoire, une partie ne survit pas au redémarrage du backend.

## Déploiement

Aucune variable d’environnement ou dépendance supplémentaire.

```bash
cd /home/iris/app
git pull --ff-only origin codex/botghost-integration
docker compose up -d --build --no-deps backend frontend
```

Fermer puis relancer OasisGame. Dans Discord, constituer deux équipes de deux comptes pour vérifier que seuls les maîtres-espions voient les couleurs avant révélation.

Les tests couvrent les règles, les rôles, les indices, les fins de manche, les délais, les reconnexions, les projections privées WebSocket, les invitations et les commandes de l’interface.
