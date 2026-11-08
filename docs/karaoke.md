# Karaoké et blind test Oasis

## Accès

- **Dans Iris** : lien « Karaoké & blind test » sur l'accueil, route `/karaoke`. La session Iris existante est requise. Les membres connectés sur le site partagent la salle `site-oasis`.
- **Dans l'Activity Discord** : bouton Karaoké de CinéStream. Chaque instance Discord a sa propre salle, sa file d'attente, son animateur et ses scores. Sans vidéo disponible, l'Activity démarre directement en karaoké.
- Les membres du serveur accèdent à l'Activity via l'OAuth existant. Les contrôles sont réservés aux rôles `ACTIVITY_CONTROLLER_ROLE_IDS` (Staff par défaut). Sur le site, les Responsables et Animateurs sont également autorisés. Les actions sensibles HTTP revérifient les rôles auprès de Discord.

Le code de l'archive `karaoke-complet-v1-v2-v3.zip` a été repris par modules. Le serveur et l'application Iris n'ont pas été remplacés par leurs versions présentes dans l'archive.

## Fonctions intégrées

- Paroles LRC, LRCLIB, romanisation japonais/chinois/coréen et autres alphabets, remplissage des paroles et pauses.
- Blind test avec réponses et scores calculés sur le serveur, titre/artiste/source, manches communes, révélation et classement.
- Catalogue karaoké limité aux lots Mac complets et valides, avec recherche, langue, favoris et file d’attente. Les extraits Deezer restent réservés au blind test.
- Favoris sauvegardés par membre en MongoDB.
- Réservation de chansons : jusqu'à trois par joueur, 50 dans la file. L'animateur lance la suivante ; la fin du morceau passe également à la suivante. Chacun peut retirer ses réservations, l'animateur toutes les réservations.
- Roulette partagée, solo/duo, exclusions et évitement de la sélection précédente lorsque le nombre de candidats le permet. Chaque joueur peut se retirer du tirage.
- Fonds originaux Néon, Océan, Aurore, avec particules et réaction à la musique lorsque Web Audio est disponible. Aucun visuel Joysound sous licence n'a été copié.
- Interface de lecture : badges Catalogue et Je participe en haut à gauche ; volumes musique et voix guide indépendants dans le menu audio au survol (ou au clic sur écran tactile). Bouton du guide de notes à côté des scores ; thème et octave dans le menu à icône. Les commandes s’effacent après 3,2 secondes sans activité et restent affichées pendant l’utilisation d’un menu. Aucun réglage de synchronisation manuel.

## Préparation recommandée sur Mac

Le traitement lourd peut désormais être réalisé hors du VPS. Le [guide du script Mac](../tools/karaoke/README.md) décrit l’installation, la préparation d’un dossier et la copie du lot de fichiers.

Le mode par défaut de l’API est `KARAOKE_PREPARATION_MODE=external` : un import non préparé ne lance ni ne met en file de modèle sur le VPS. Seuls les lots Mac complets et validés sont proposés dans le catalogue karaoké, sélectionnés au démarrage ou acceptés dans la file. Un ancien morceau non préparé est écarté et la position de lecture réinitialisée ; les fichiers restent sur le disque. Les anciennes réservations non préparées sont ignorées en passant au morceau suivant. Les lots Mac valides fournissent directement les paroles, le score de référence, le mix personnel et les effets, sans base de préparation à reconstruire.

Pour conserver explicitement l’ancien worker CPU optionnel, configurer `KARAOKE_PREPARATION_MODE=server` pour le backend et lancer le profil Compose `karaoke-cpu`. Ce worker reste facultatif ; sa configuration et les anciens diagnostics CPU ci-dessous concernent uniquement ce mode.

## Installation serveur CPU facultative

Le backend continue à fonctionner sans les services facultatifs : karaoké, paroles LRC et blind test restent disponibles. Pour la préparation Whisper et le score vocal :

```sh
docker compose --profile karaoke --profile karaoke-cpu up -d --build
```

Deux services sont ajoutés :

1. `karaoke-preparation` : une file CPU, deux threads, WhisperX avec modèle `base` INT8, Demucs pour isoler la voix et extraction de la hauteur de référence. Les modèles sont téléchargés au premier traitement puis conservés dans le volume `karaoke-models`. Prévoir de la place disque et de la RAM ; le service est plafonné à 6 Go et deux CPU. La durée dépend du morceau et du processeur, sans garantie de quelques minutes. On peut réduire les threads/CPU dans Compose pour privilégier l'API.
2. `karaoke-voice` : récepteur Discord Node 24, `@discordjs/voice` avec DAVE, décodeur Opus et calcul de caractéristiques audio en mémoire. Aucun port n'est publié sur l'hôte. L'API et ce service communiquent sur le réseau Docker existant.

Les chansons complètes sont dans le volume `karaoke-music`, les paroles et références dans `resources-data:/app/storage/karaoke`. La banque musicale est montée en lecture seule dans le worker de préparation. Le backend est le seul service qui importe les fichiers.

L'API doit rester à **un processus Uvicorn**, comme la configuration actuelle : les salles Activity et la session vocale sont en mémoire. Un déploiement multi-processus nécessiterait un état partagé (Redis et verrou de salle), pas seulement plusieurs workers Uvicorn.

## OasisLink et consentement

Le service vocal utilise par défaut le **même bot OasisLink** via `DISCORD_BOT_TOKEN` et une connexion Gateway séparée limitée aux événements vocaux. Il ne réenregistre pas de commandes et ne traite pas la modération. Un bot n'occupe qu'un vocal par serveur ; si OasisLink y est déjà utilisé, la demande est refusée. Si cette identité provoque un conflit avec un autre usage vocal, on peut fournir `KARAOKE_BOT_TOKEN` pour un bot spécialisé déjà invité sur le serveur.

OasisLink rejoint automatiquement le salon vocal du participant à l’ouverture du karaoké. L’Activity fournit son salon lorsqu’il est disponible ; sinon le récepteur retrouve le vocal du membre via Discord. Le service vérifie sa présence effective dans ce salon. La connexion est idempotente pour une même salle, avec cinq tentatives automatiques maximum. Une autre salle active reste prioritaire : le lecteur attend sa libération puis reprend la connexion. Les sessions sans joueur depuis 10 secondes, sorties du karaoké ou sans récepteur prêt depuis 35 secondes sont libérées automatiquement. Les résultats sont archivés avant remplacement, et les accords vocaux ne sont pas transférés à la nouvelle session. Permissions nécessaires : voir le salon, se connecter, écrire dans son chat vocal ; intents Guilds et GuildVoiceStates. Aucune permission d'administration n'est nécessaire.

Un message d'information est envoyé **avant** la connexion vocale et aux nouveaux arrivants. Chaque joueur clique sur « Activer les scores » pour donner son accord à l’analyse ; le même bouton devient « Désactiver les scores » pour retirer cet accord. La connexion automatique ne donne aucun accord implicite. Un joueur sans accord n'a pas de flux audio abonné au décodeur. Le retrait est pris en compte côté API immédiatement et côté récepteur au passage suivant (environ 300 ms). Les joueurs absents de la salle de jeu ou du vocal ne sont pas analysés.

- Pas d'accès au micro du navigateur/Activity, donc la permission microphone reste désactivée dans Nginx.
- Pas de stockage d'enregistrement vocal, de transcription de joueurs ni d'envoi de leur voix à Whisper ou à une API d'IA.
- Audio PCM éphémère en mémoire ; seules activité vocale et hauteur estimée sont transmises au serveur interne.
- Les scores récapitulatifs sont enregistrés en MongoDB (`karaoke_results`) à la fin/changement de morceau ou à l'arrêt de la session.
- Signature HMAC, horodatage, numéro de séquence et génération de morceau sur les lots du récepteur ; le navigateur ne peut pas déclarer un score.
- Arrêt de l'écoute en cas d'erreur de communication, arrêt de session si elle n'est plus consultée depuis 90 secondes, durée maximale de six heures. Les consentements ne survivent pas au redémarrage de l'API.

La clé interne est dérivée de `APP_SESSION_SECRET` avec un contexte distinct. On peut la remplacer par `KARAOKE_VOICE_SECRET` (32 caractères minimum), identique dans le backend et le service vocal. Aucune de ces clés n'est envoyée au navigateur.

## Alignement et scoring

Les imports sont placés dans une file MongoDB durable. Le worker relit la banque locale et prépare aussi les nouveaux fichiers déposés directement dans le volume. Les erreurs de préparation apparaissent dans le menu ; « Préparer / réessayer » relance un morceau en échec. Un changement de fichier invalide sa référence.

1. Vérification de la durée par FFprobe.
2. Séparation vocale Demucs sur CPU (facultative via `KARAOKE_DEMUCS_ENABLED=false`).
3. Détection automatique de langue et transcription WhisperX. Les paroles LRC/LRCLIB disponibles remplacent le texte transcrit pour l'alignement forcé.
4. Alignement phonétique, avec horodatages de caractères pour japonais/chinois lorsque disponibles. La lecture bascule sur les horodatages alignés une fois prêts.
5. Mélodie approximative extraite de la voix isolée via pYIN, par pas de 100 ms. Sans voix isolée, pas de référence de justesse.

Le score de rythme compare l'activité aux fenêtres réellement alignées, pénalise les lignes manquées et le chant dans les pauses. La justesse compare la hauteur chantée à la référence **en ignorant l'octave**. Elle reste approximative sur le chant, les chœurs et les micros Discord. Les scores couvrent la période après l'accord du joueur. La compensation de latence est personnelle, entre -500 et +2000 ms ; casque recommandé. L'activité vocale seule ne prouve pas que les paroles ont été chantées : c'est un jeu amical, pas un dispositif anti-triche absolu.

Whisper n'analyse pas les joueurs en direct. Les extraits Deezer ne sont jamais utilisés pour l'alignement ou la référence mélodique. Les paroles anciennes sans préparation conservent l'affichage estimé fourni par le code d'origine ; le score vocal attend une référence alignée.

## Configuration facultative

- `KARAOKE_DIR=/data/karaoke`, `KARAOKE_CACHE_DIR=/app/storage/karaoke`.
- `KARAOKE_VOICE_URL=http://karaoke-voice:8091` côté API.
- `KARAOKE_BACKEND_URL=http://backend:8000/api/activity/karaoke` côté récepteur.
- `KARAOKE_BOT_TOKEN` : bot vocal distinct, sinon OasisLink.
- `KARAOKE_WHISPER_MODEL=base`, `KARAOKE_CPU_THREADS=2`, `KARAOKE_DEMUCS_ENABLED=true`.
- Catalogue : `KARAOKE_CATALOG_ENABLED`, `KARAOKE_DEEZER_CHART`, `KARAOKE_DEEZER_PLAYLISTS`, `KARAOKE_DEEZER_QUERIES`, `KARAOKE_CATALOG_PER_SOURCE`, `KARAOKE_CATALOG_TOTAL`, `KARAOKE_CATALOG_TTL_HOURS`.
- `KARAOKE_LRCLIB_ENABLED=true` pour la récupération des paroles.

## Validation et limites de la livraison

Validation locale : 485 tests backend, 32 tests web et deux tests audio Node passent.

Tests locaux : règles du blind test et paroles de l'archive ; file, favoris, roulette, droits, consentement/retrait, signature et anti-rejeu des lots, scoring silencieux/rythme/octave, invalidation du cache, publication atomique d'une préparation simulée et import protégé. Le décodeur Opus installé a été testé avec du son synthétique réel. La dépendance DAVE est chargée (`@discordjs/voice` 0.19.2, `@snazzah/davey` 0.1.12). Tests des composants web et vérification indépendante des règles Hooks/variables JavaScript.

Compilation frontend complète effectuée avec `DISABLE_ESLINT_PLUGIN=true CI=false` : le plugin intégré CRA est incompatible avec l'ESLint 9 déjà installé localement et le projet a un avertissement d'ordre CSS des réunions. Les nouveaux composants sont vérifiés séparément avec ESLint. ECharts manquant dans l'environnement local a été fourni temporairement pour cette compilation, sans changement de version dans le projet.

Aucun accès au serveur de production ni salon Discord de test n'a été utilisé. Docker n'est pas installé dans cet environnement : les images et le téléchargement des modèles lourds restent à valider sur le serveur. Le code est livré avec cette distinction ; il ne constitue pas une validation vocale réelle de bout en bout.

Après déploiement : importer un morceau, attendre sa préparation, rejoindre le vocal à deux, vérifier la connexion automatique et l’annonce, tester sans score puis activer les scores, retirer l’accord et comparer une note à l’octave. Vérifier desktop et mobile. La réception audio Discord reste expérimentale dans la bibliothèque et ne bénéficie pas d'une garantie officielle de stabilité.

Sources techniques : [Discord Voice/DAVE](https://github.com/discord/discord-api-docs/blob/main/developers/topics/voice-connections.mdx), [récepteur @discordjs/voice](https://github.com/discordjs/discord.js/tree/main/packages/voice), [WhisperX](https://github.com/m-bain/whisperX).

## Si le build échoue avec « No space left on device »

Cette erreur concerne le disque (ou les inodes), pas le plafond de RAM du worker. La première version installait UniDic dans le backend et réinstallait toutes les dépendances d'Iris dans le worker. Cette duplication est supprimée : le japonais utilise désormais pykakasi, livré dans une petite wheel pure Python, et le worker a une liste minimale de dépendances sans les intégrations du backend. Cutlet reste utilisable si déjà installé, mais n'est plus une dépendance du build.

Vérifier l'espace sur le serveur :

```sh
df -h
df -i
docker system df
```

On peut supprimer les caches de construction inutilisés avec `docker builder prune` ; cette commande demande confirmation et ne supprime pas les volumes MongoDB, chansons ou modèles. Elle oblige à retélécharger/reconstruire les couches supprimées. Ne pas utiliser une purge des volumes pour résoudre ce problème.

Après récupération du commit correctif, construire les images séparément pour réduire le pic d'espace temporaire :

```sh
docker compose build backend
docker compose --profile karaoke-cpu build karaoke-preparation
docker compose --profile karaoke build karaoke-voice
docker compose --profile karaoke --profile karaoke-cpu up -d --no-deps backend karaoke-preparation karaoke-voice
```

Cette séquence suppose que MongoDB est déjà en fonctionnement et ne reconstruit pas le frontend. Whisper/PyTorch et les modèles nécessitent toujours de l'espace disque ; la correction ne peut pas rendre exploitable un disque encore saturé.

## Catégories Deezer du blind test

Dans **Blind test → Lancer un blind test**, les animateurs disposent de deux filtres combinables :

- **20 styles** : Animé, Pop, Rock, J-pop, K-pop, Jazz, Électro, Rap/Hip-hop, R&B, Soul, Funk, Disco, Metal, Reggae, Country, Blues, Classique, Chanson française, Latino, Indie/Alternative.
- **8 décennies** : années 1950, 1960, 1970, 1980, 1990, 2000, 2010 et 2020.

Exemple : sélectionner **Rock** et **Années 1980**. Le choix d’une catégorie passe la source sur les extraits Deezer ; les fichiers locaux ne sont pas classés automatiquement. « Rejouer » conserve les filtres de la partie.

Les sélections utilisent des playlists publiques Deezer dont les titres correspondent aux thèmes demandés. Il s’agit de sélections thématiques, pas d’une vérification de l’année de sortie originale de chaque enregistrement. Seuls les morceaux disposant d’un extrait valide sont retenus. Une sélection vide ou indisponible est signalée, sans remplacer silencieusement le thème par le classement général.

Les catégories sont chargées uniquement à la demande. Les requêtes simultanées pour une même sélection sont regroupées, les chargements réseau sont limités et 24 sélections au maximum restent en cache mémoire. Aucun service karaoké/Whisper supplémentaire n’est nécessaire.


## Points de chant et fin de morceau

Le compteur reçoit des points calculés côté serveur : jusqu’à 100 points par tranche chantée de 100 ms attendue dans les paroles. Une référence de hauteur exploitable partage les points à parts égales entre présence vocale et justesse (octave ignorée) ; sans hauteur, la présence attendue suffit. Le silence ne rapporte rien. Chaque gain est doré au maximum possible, turquoise au-dessus de la moitié, violet sinon. Le score repart de zéro avec une nouvelle lecture.

À la fin d’un morceau, les résultats restent visibles pendant un compte à rebours partagé de 70 secondes. Tout participant peut le mettre en pause ou le reprendre ; l’animateur peut passer immédiatement au suivant. La file est prioritaire, puis le serveur tire un autre lot Mac valide (le même morceau uniquement s’il est seul). Une sélection manuelle annule le compte à rebours. Le calcul de l’échéance et le changement de morceau restent sur le serveur.

Les effets visuels utilisent les fortes montées d’énergie et les drops préparés ou mesurés en direct ; ce ne sont pas des annotations manuelles des refrains. Les salves de particules sont espacées d’au moins 12 secondes et désactivées avec la préférence de réduction des animations.


## Accueil et classements

Une nouvelle salle affiche un accueil partagé de 20 secondes avant la première lecture. Chaque membre choisit « Je participe » pour rejoindre la roulette ; cette inscription reste disponible pendant la partie et ne donne pas l’accord d’analyse vocale. Rejoindre une salle déjà en cours ne relance pas l’accueil. Quand le dernier membre ferme la salle, ses minuteries sont annulées et la prochaine ouverture retrouve l’accueil.

L’icône trophée ouvre les classements par chanson et général. Ils enregistrent les points calculés par le serveur à la fin d’une chanson avec le score vocal actif. Chaque membre conserve son meilleur score par morceau ; le classement général additionne ces records, sans cumuler les répétitions. Les données persistent dans MongoDB (`karaoke_bests`), avec au maximum 100 joueurs affichés par classement.

La tessiture est réglable à côté du bouton du guide, séparément des thèmes : Très grave (−2 octaves), Grave (−1), Neutre, Aigu (+1), Très aigu (+2). Ce réglage reste personnel ; le calcul de justesse ignore l’octave.
