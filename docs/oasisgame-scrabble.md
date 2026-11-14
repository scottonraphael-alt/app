# Scrabble dans OasisGame

Le menu de l’Activity propose **Scrabble → Jouer avec les mots**. L’hôte ouvre la
table, les participants prennent une place et l’hôte lance la partie (2 à 4 joueurs).
Les autres membres peuvent suivre le plateau et discuter sans voir les chevalets.
Le fond sombre, les dégradés violet/bleu, les cartes arrondies, les boutons et les
accents pastel reprennent la charte existante. Les lettres sont couleur ivoire.

## Jouer

- Choisir une lettre puis une case, ou glisser la lettre sur le plateau.
- Pour reprendre une lettre en préparation, cliquer sa case ou sa lettre sur le chevalet.
- Un joker ouvre un sélecteur A–Z. Il conserve sa valeur de zéro pour toute la partie.
- Le serveur vérifie le mot et affiche ses points avant d’activer **Valider le mot**.
- **Mélanger** change uniquement l’ordre du chevalet personnel.
- **Échanger** permet de sélectionner des lettres, puis de confirmer leur échange.
  Il faut au moins sept lettres dans le sac ; l’échange termine le tour.
- **Passer** et **Abandonner** demandent confirmation. Le départ au menu par l’hôte
  pendant une partie demande aussi confirmation et ferme la partie pour tous.

Le premier mot doit traverser l’étoile centrale. Les placements suivants doivent
être contigus sur une ligne ou une colonne et reliés au plateau. Chaque mot formé
dans les deux directions est vérifié et compté. Les multiplicateurs s’appliquent
uniquement aux nouvelles lettres ; poser les sept lettres apporte 50 points.

La distribution française contient 102 lettres dont deux jokers. Le serveur tire
et mélange les lettres ; le navigateur ne décide ni des lettres ni du score.
À la fin, les valeurs des lettres restantes sont soustraites. Un joueur qui vide
son chevalet avec un sac vide reçoit aussi les valeurs restantes des autres.
Six tours consécutifs sans points terminent également la partie. Les égalités
sont conservées. Les scores sont ceux de la partie, remis à zéro à chaque revanche.

## Temps et présence

L’hôte choisit un tour sans limite, ou de 1, 2, 3 ou 5 minutes. À expiration,
le joueur passe automatiquement son tour. L’état serveur décide de l’échéance.

Une déconnexion suspend la partie pendant deux minutes. Une reconnexion dans ce
délai retrouve le même plateau, le même chevalet et le même temps restant. Au-delà,
le joueur est considéré comme ayant abandonné et la partie continue entre les
autres joueurs. Si plus personne ne reste, aucun vainqueur n’est attribué.

Comme les autres jeux de plateau d’OasisGame, les parties sont gardées en mémoire
dans le processus backend. Un redémarrage du backend ne restaure pas une partie ;
les déploiements se font entre les parties. Ce mode demande une seule instance du
backend pour un même salon, comme l’infrastructure WebSocket existante.

## Lexique

Le lexique embarqué comporte **114 763 formes** issues de
[Lexique 3.83](https://openlexicon.fr/datasets-info/Lexique383/README-Lexique.html),
de Boris New, Christophe Pallier et contributeurs. Il est fourni séparément sous
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) dans
`backend/assets/french_words.txt`, avec attribution et transformations documentées
dans `french_words.LICENSE.md`. Les accents sont neutralisés, Œ/Æ deviennent OE/AE,
les entrées non alphabétiques sont exclues et la longueur retenue est de 2 à 15.
Ce n’est pas le dictionnaire officiel de compétition : certains mots peuvent
différer. Les règles affichées dans le jeu indiquent cette distinction.

La validation ne fait aucun appel réseau pendant la partie. Un lexique absent ou
incomplet bloque l’ouverture du jeu, sans accepter silencieusement tous les mots.
Le sac et les chevalets ne figurent jamais dans l’état commun. Chaque connexion
reçoit uniquement son propre chevalet, y compris après une resynchronisation.
L’aperçu d’un coup est envoyé au seul joueur qui l’a demandé ; il ne modifie pas
le plateau. Les actions de jeu exigent la bonne manche et la bonne révision du tour.

## Déployer

Aucune nouvelle variable d’environnement ni dépendance backend n’est nécessaire.
Après avoir poussé le commit sur GitHub, dans `/home/iris/app` :

```bash
git pull --ff-only origin codex/botghost-integration
docker compose up -d --build --no-deps backend frontend
```

Fermer puis relancer l’Activity OasisGame pour charger le nouveau menu. Il n’y a
pas de commande slash à enregistrer pour ce jeu.

## Vérification

Les tests couvrent les scores, croisements, multiplicateurs, jokers, bonus de sept
lettres, conservation des 102 lettres, échanges, fins de partie, doublons de coups,
actions hors tour, délais, déconnexions, revanches et confidentialité par connexion.
Un test WebSocket à deux connexions exerce la resynchronisation et la reconnexion.
Les tests React couvrent le menu, le placement, l’aperçu serveur, les jokers,
les échanges, la confirmation des actions et les spectateurs.

Le rendu est vérifié sur ordinateur et à 390 px de large. Les captures sont des
états de démonstration du composant réel, pas une partie envoyée sur Discord.
