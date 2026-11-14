# UNO dans OasisGame

L’hôte ouvre **UNO → Rejoindre la table**. Chaque joueur choisit **Prendre une place**,
puis l’hôte distribue les cartes. La table accueille de 2 à 8 joueurs et des
spectateurs. Les cartes ont un dessin original en CSS dans la charte OasisGame :
corail, jaune crème, vert menthe, bleu pastel et dos violet. Aucun visuel officiel
de carte ni logo de marque n’est embarqué.

## Jouer une manche

Le paquet contient 108 cartes. Chacun en reçoit sept ; une carte numérotée ouvre
la défausse. Les cartes jouables sont indiquées par le serveur et mises en évidence.
Cliquer une carte pour la poser ; les jokers ouvrent un choix de couleur.
Les couleurs portent aussi un nom et un symbole pour ne pas reposer sur la seule teinte.

La pioche est volontaire. Si la carte obtenue est jouable, le joueur peut la poser
ou la garder et passer. Les autres cartes de sa main ne deviennent pas jouables
après cette pioche. Le bouton **UNO !** est disponible à une ou deux cartes :
l’annoncer avant l’avant-dernière carte protège contre la pénalité. Si l’annonce
est oubliée, les adversaires peuvent choisir **UNO oublié ! (+2)** avant le
prochain coup. L’auteur peut se rattraper avant d’être signalé.

Le serveur applique les effets des cartes, y compris l’inversion à deux joueurs,
et traite la contestation du +4. Il mémorise la présence ou l’absence de la couleur
précédente dans la main de l’auteur au moment du coup. Cette preuve n’est jamais
envoyée dans l’état public. Le résultat de la contestation est communiqué à tous,
sans dévoiler les cartes privées.

Si la pioche est vide, la défausse est remélangée en gardant sa dernière carte sur
la table. Une manche se termine lorsqu’un joueur n’a plus de cartes ; les pénalités
d’une dernière carte +2 ou +4 sont appliquées avant le calcul des points.
Les adversaires ne voient jamais les cartes piochées.

Les règles affichées dans l’interface détaillent les effets et pénalités. Référence
générale : [notice du jeu classique, Mattel](https://service.mattel.com/instruction_sheets/J3799-0920.pdf).
Les choix propres à cette table sont explicites : ouverture toujours numérotée,
pas de cumul des +2/+4, pas de « jump-in » ni d’échange 7–0, pas de fin automatique
à 500 points. Les points s’additionnent entre les revanches de la même table ;
**Nouvelle table** les remet à zéro. Les mains d’un joueur ayant abandonné ne
rapportent pas de points au vainqueur par forfait.

## Chronomètre et présence

L’hôte choisit un tour de 30, 60 ou 120 secondes, ou sans limite. À expiration,
le joueur pioche une carte et passe, sauf s’il a déjà pioché : dans ce cas, seul
le passage est effectué. Un +4 en attente est automatiquement accepté.

La déconnexion d’un joueur actif met la manche en pause pendant deux minutes.
Le retour dans ce délai restaure sa main et le même temps restant. Au-delà, le
joueur est considéré comme ayant abandonné et la table continue sans lui. Le
dernier joueur connecté remporte la manche par forfait ; si tous sont absents,
aucun vainqueur n’est attribué.

Comme les autres jeux de plateau de l’activité, les manches sont gardées en mémoire
dans un seul processus backend. Un redémarrage du backend ne restaure pas une partie.

## Confidentialité et protocole

Les projections publiques contiennent uniquement les nombres de cartes, la défausse,
la couleur active, le sens, les scores et l’historique public. Chaque connexion reçoit
sa main séparément. Une synchronisation ou une reconnexion utilise la même projection
personnalisée. Les spectateurs reçoivent une main vide. Ni l’ordre de pioche ni les
mains adverses ne sont transmis.

Les coups mentionnent la référence de manche et la révision actuelle. Le serveur
contrôle la présence dans la partie, le tour, l’identité de la carte dans la main,
la couleur, les contraintes après pioche et les défis en attente. Un clic doublé
ou un message d’une ancienne manche ne peut pas rejouer une carte.

## Déploiement

Aucune nouvelle dépendance ni variable d’environnement n’est nécessaire. Après
publication du commit, dans `/home/iris/app` :

```bash
git pull --ff-only origin codex/botghost-integration
docker compose up -d --build --no-deps backend frontend
```

Fermer puis relancer OasisGame pour charger le nouveau menu. Les invitations au
salon utilisent le panneau pastel et les liens Discord vérifiés existants.

## Validation

Les tests exercent la composition du paquet, la distribution, les coups légaux,
les jokers, les défis, les annonces et oublis UNO, la pioche et son recyclage,
les effets en duel, les fins de manche, les points, les délais, les forfaits,
les manches périmées et les droits. Une simulation vérifie la conservation des
108 cartes à chaque action. Deux connexions WebSocket vérifient les mains privées,
la synchronisation et la reconnexion ; les projections des spectateurs sont aussi
testées. Les tests React couvrent le menu, la pose, les couleurs, les annonces,
les contestations, les spectateurs et les commandes de l’hôte.

Le composant réel est vérifié sur ordinateur et à 390 px. Les captures utilisent
une table de démonstration locale, sans envoyer de partie ou message sur Discord.
