# OasisGame — application Discord indépendante

Le cinéma reste dans CinéStream ; ses nouvelles connexions exigent les rôles `ACTIVITY_ALLOWED_ROLE_IDS`, ou les rôles staff contrôleurs si cette liste est vide. Il ne propose plus de bouton karaoké et ne bascule plus automatiquement vers un jeu quand aucune vidéo n’est présente.

OasisGame possède son OAuth et des jetons distincts. Tous les membres du serveur peuvent ouvrir une salle de jeux, sans rôle staff. Le premier membre devient hôte et choisit le jeu ; si l’hôte part, un participant restant le remplace. L’hôte peut revenir au menu « Jeux ». Les salles CinéStream et OasisGame sont isolées, même si Discord réutilise un identifiant d’instance.

Le menu propose :

- **Karaoké** : uniquement depuis le salon `1569069812804751431`. Le serveur vérifie aussi la présence vocale réelle du membre via le bot OasisLink ; un simple identifiant de salon envoyé par le navigateur ne suffit pas. Le bot doit être connecté et voir ce salon. L’accueil de 20 secondes, les morceaux Mac, les scores et les classements sont conservés.
- **Blind test** : page de préparation dédiée, avec styles et décennies Deezer, nombre de manches et durée, puis bouton « Lancer la partie ». Aucun rôle staff n’est requis pour l’hôte OasisGame. Le blind test n’est pas limité au salon karaoké.
- **Puissance 4** : duel en direct ou contre l’ordinateur, trois tailles de grille, chrono facultatif et spectateurs. L’hôte ouvre le plateau depuis le menu. Les joueurs prennent une place avant de lancer la manche. Le score est conservé entre les revanches du même duel.
- **Morpion** : grille 3 × 3, duel entre membres ou contre l’ordinateur à trois niveaux. Le jeu propose un chrono facultatif, des spectateurs, des revanches et la relecture de la dernière manche.
- **Scrabble** : plateau 15 × 15, de 2 à 4 joueurs, chevalets privés, jokers et lexique français local. Voir [les règles et le déploiement](oasisgame-scrabble.md).
- **Démineur** : solo ou coopération jusqu’à 8 joueurs, trois difficultés, premier clic protégé et chronomètre. Voir [les règles et le déploiement](oasisgame-minesweeper.md).

## Créer l’application

1. Ouvrir [Discord Developer Portal](https://discord.com/developers/applications) et créer l’application **OasisGame** dans le même compte ou la même équipe que CinéStream.
2. Dans **General Information**, copier son **Application ID**. Dans **OAuth2 → Redirects**, ajouter `https://127.0.0.1` et cliquer sur **Save Changes**. Cette URL est requise pour que Discord autorise l’Activity. Le SDK gère le retour dans Discord. Dans **OAuth2**, récupérer aussi le **Client Secret** et le conserver dans le `.env` du VPS.
3. Ajouter les **URL Mappings** utilisés par CinéStream, sur cette nouvelle application :

   | Prefix | Target |
   | --- | --- |
   | `/` | Le même domaine frontend qu’utilise CinéStream, sans protocole, par exemple `iris.loasis.app` si c’est le domaine de ton installation |
   | `/backend` | `api.loasis.app` |

   L’entrée frontend reconnaît automatiquement l’identifiant d’OasisGame grâce à `/api/games/config` : aucun identifiant d’application à compiler dans JavaScript.
4. Activer **Activities → Settings → Enable Activities**, puis les plateformes désirées. Discord crée une commande d’entrée **Launch** ; elle doit utiliser le lancement d’Activity géré par Discord. Ne pas configurer un endpoint d’interactions du bot de modération pour ce lancement.
5. Configurer l’installation de cette nouvelle application sur le serveur et autoriser les membres à utiliser les applications/Activities. Les restrictions de rôles du lancement de CinéStream ne doivent pas être recopiées sur OasisGame.
6. Pour les essais, utiliser les développeurs et testeurs de cette application. Pour l’accès à tous les membres, suivre la procédure de **vérification d’Activity** de Discord : une application non vérifiée reste réservée aux développeurs et testeurs. Une simple installation sur le serveur ne lève pas cette restriction.

Sources officielles : [première Activity](https://github.com/discord/discord-api-docs/blob/main/developers/activities/building-an-activity.mdx), [URL Mappings](https://github.com/discord/discord-api-docs/blob/main/developers/activities/development-guides/local-development.mdx), [Activities vérifiées et non vérifiées](https://support-dev.discord.com/hc/en-us/articles/26576097154199-What-are-Verified-and-Unverified-Activities).

## Configurer le VPS

Dans `/home/iris/app/.env`, ajouter :

```dotenv
OASISGAME_DISCORD_CLIENT_ID=IDENTIFIANT_PUBLIC_OASISGAME
OASISGAME_DISCORD_CLIENT_SECRET=SECRET_OAUTH_OASISGAME
OASISGAME_DISCORD_BOT_TOKEN=TOKEN_DU_BOT_OASISGAME
```

Conserver `ACTIVITY_DISCORD_CLIENT_ID` et `ACTIVITY_DISCORD_CLIENT_SECRET` pour CinéStream. OasisGame réutilise le récepteur vocal OasisLink existant.

Le token de l’onglet **Bot** de l’application **OasisGame** permet au backend de vérifier l’instance Discord avant d’annoncer la recherche de joueurs. OasisGame publie dans le salon confirmé par Discord. Si Discord lui refuse l’envoi, OasisLink prend le relais s’il a accès au salon. Le bot qui publie doit avoir la permission **Envoyer des messages**, ou **Envoyer des messages dans les fils** selon le salon. **Voir les anciens messages** permet de retrouver le message de lancement et **Créer une invitation** permet un lien direct dans les salons vocaux. Le bouton **Inviter** dans l’Activity ouvre la boîte d’invitation Discord.

Les invitations sont publiées sous forme de panneaux Components V2 : couleur
pastel par jeu, accroche, mention de l’hôte sans notification, nombre de joueurs
et bouton vers le lien Discord vérifié. Le message d’information sur l’analyse
vocale utilise aussi un panneau, avec les explications du score, le consentement
facultatif, les boutons réels de l’activité et le conseil du casque. Les messages
déjà envoyés ne sont pas modifiés ; seuls les prochains envois utilisent ce rendu.
Pour mettre à jour ces deux types de messages, reconstruire `backend` et
`karaoke-voice` (profil `karaoke`). Aucune reconstruction frontend n’est nécessaire.

Après publication du commit :

```bash
cd /home/iris/app
git fetch origin
git merge --ff-only origin/codex/botghost-integration
docker compose up -d --build --no-deps backend frontend
docker compose --profile karaoke up -d --no-deps karaoke-voice
```

Dans Discord, fermer les anciennes Activities et lancer **OasisGame**, depuis le salon karaoké pour chanter. Tester aussi depuis un autre salon : le blind test doit rester accessible, tandis que le karaoké doit être bloqué. Vérifier l’ouverture avec un membre sans rôle staff, puis le transfert d’hôte, les deux jeux et le retour au menu.

Sans identifiants OasisGame configurés, la nouvelle application affiche un état explicite de configuration manquante ; CinéStream continue d’utiliser ses identifiants existants.
