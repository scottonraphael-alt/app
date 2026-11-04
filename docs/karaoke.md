# Karaoké et blind test Oasis

## Accès

- **Dans Iris** : lien « Karaoké & blind test » sur l'accueil, route `/karaoke`. La session Iris existante est requise. Les membres connectés sur le site partagent la salle `site-oasis`.
- **Dans l'Activity Discord** : bouton Karaoké de CinéStream. Chaque instance Discord a sa propre salle, sa file d'attente, son animateur et ses scores. Sans vidéo disponible, l'Activity démarre directement en karaoké.
- Les membres du serveur accèdent à l'Activity via l'OAuth existant. Les contrôles sont réservés aux rôles `ACTIVITY_CONTROLLER_ROLE_IDS` (Staff par défaut). Sur le site, les Responsables et Animateurs sont également autorisés. Les actions sensibles HTTP revérifient les rôles auprès de Discord.

Le code de l'archive `karaoke-complet-v1-v2-v3.zip` a été repris par modules. Le serveur et l'application Iris n'ont pas été remplacés par leurs versions présentes dans l'archive.

## Fonctions intégrées

- Paroles LRC, LRCLIB, romanisation japonais/chinois/coréen et autres alphabets, remplissage des paroles et pauses.
- Blind test avec réponses et scores calculés sur le serveur, titre/artiste/source, manches communes, révélation et classement.
- Catalogue local et extraits Deezer de 30 secondes réservés au blind test. Recherche par titre/artiste, filtre langue/source, recherche Deezer à la demande de l'animateur.
- Favoris sauvegardés par membre en MongoDB.
- Réservation de chansons : jusqu'à trois par joueur, 50 dans la file. L'animateur lance la suivante ; la fin du morceau passe également à la suivante. Chacun peut retirer ses réservations, l'animateur toutes les réservations.
- Roulette partagée, solo/duo, exclusions et évitement de la sélection précédente lorsque le nombre de candidats le permet. Chaque joueur peut se retirer du tirage.
- Fonds originaux Néon, Océan, Aurore, avec particules et réaction à la musique lorsque Web Audio est disponible. Aucun visuel Joysound sous licence n'a été copié.
- Import audio via le site/Activity par un animateur, avec titre, artiste et source. Formats MP3/OGG/OPUS/M4A/AAC/FLAC/WAV/WEBM. 200 Mo et 20 minutes maximum ; aucun téléchargement audio depuis une URL fournie par un joueur.

## Installation serveur CPU

Le backend continue à fonctionner sans les services facultatifs : karaoké, paroles LRC et blind test restent disponibles. Pour la préparation Whisper et le score vocal :

```sh
docker compose --profile karaoke up -d --build
```

Deux services sont ajoutés :

1. `karaoke-preparation` : une file CPU, deux threads, WhisperX avec modèle `base` INT8, Demucs pour isoler la voix et extraction de la hauteur de référence. Les modèles sont téléchargés au premier traitement puis conservés dans le volume `karaoke-models`. Prévoir de la place disque et de la RAM ; le service est plafonné à 6 Go et deux CPU. La durée dépend du morceau et du processeur, sans garantie de quelques minutes. On peut réduire les threads/CPU dans Compose pour privilégier l'API.
2. `karaoke-voice` : récepteur Discord Node 24, `@discordjs/voice` avec DAVE, décodeur Opus et calcul de caractéristiques audio en mémoire. Aucun port n'est publié sur l'hôte. L'API et ce service communiquent sur le réseau Docker existant.

Les chansons complètes sont dans le volume `karaoke-music`, les paroles et références dans `resources-data:/app/storage/karaoke`. La banque musicale est montée en lecture seule dans le worker de préparation. Le backend est le seul service qui importe les fichiers.

L'API doit rester à **un processus Uvicorn**, comme la configuration actuelle : les salles Activity et la session vocale sont en mémoire. Un déploiement multi-processus nécessiterait un état partagé (Redis et verrou de salle), pas seulement plusieurs workers Uvicorn.

## OasisLink et consentement

Le service vocal utilise par défaut le **même bot OasisLink** via `DISCORD_BOT_TOKEN` et une connexion Gateway séparée limitée aux événements vocaux. Il ne réenregistre pas de commandes et ne traite pas la modération. Un bot n'occupe qu'un vocal par serveur ; si OasisLink y est déjà utilisé, la demande est refusée. Si cette identité provoque un conflit avec un autre usage vocal, on peut fournir `KARAOKE_BOT_TOKEN` pour un bot spécialisé déjà invité sur le serveur.

L'animateur rejoint son vocal puis clique sur « Connecter OasisLink » (l'Activity renseigne le salon ; sur le site, saisir son identifiant). Le service vérifie la présence effective de l'animateur dans le salon. Permissions nécessaires : voir le salon, se connecter, écrire dans son chat vocal ; intents Guilds et GuildVoiceStates. Aucune permission d'administration n'est nécessaire.

Un message d'information est envoyé **avant** la connexion vocale et aux nouveaux arrivants. Chaque joueur active séparément « J'accepte l'analyse de ma voix ». Un joueur sans accord n'a pas de flux audio abonné au décodeur. Le retrait est pris en compte côté API immédiatement et côté récepteur au passage suivant (environ 300 ms). Les joueurs absents de la salle de jeu ou du vocal ne sont pas analysés.

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

Validation locale : 482 tests backend, 32 tests web et deux tests audio Node passent.

Tests locaux : règles du blind test et paroles de l'archive ; file, favoris, roulette, droits, consentement/retrait, signature et anti-rejeu des lots, scoring silencieux/rythme/octave, invalidation du cache, publication atomique d'une préparation simulée et import protégé. Le décodeur Opus installé a été testé avec du son synthétique réel. La dépendance DAVE est chargée (`@discordjs/voice` 0.19.2, `@snazzah/davey` 0.1.12). Tests des composants web et vérification indépendante des règles Hooks/variables JavaScript.

Compilation frontend complète effectuée avec `DISABLE_ESLINT_PLUGIN=true CI=false` : le plugin intégré CRA est incompatible avec l'ESLint 9 déjà installé localement et le projet a un avertissement d'ordre CSS des réunions. Les nouveaux composants sont vérifiés séparément avec ESLint. ECharts manquant dans l'environnement local a été fourni temporairement pour cette compilation, sans changement de version dans le projet.

Aucun accès au serveur de production ni salon Discord de test n'a été utilisé. Docker n'est pas installé dans cet environnement : les images et le téléchargement des modèles lourds restent à valider sur le serveur. Le code est livré avec cette distinction ; il ne constitue pas une validation vocale réelle de bout en bout.

Après déploiement : importer un morceau, attendre sa préparation, rejoindre le vocal à deux, connecter OasisLink, vérifier l'annonce, tester sans accord puis avec accord, retirer l'accord, comparer une note à l'octave et calibrer la latence. Vérifier desktop et mobile. La réception audio Discord reste expérimentale dans la bibliothèque et ne bénéficie pas d'une garantie officielle de stabilité.

Sources techniques : [Discord Voice/DAVE](https://github.com/discord/discord-api-docs/blob/main/developers/topics/voice-connections.mdx), [récepteur @discordjs/voice](https://github.com/discordjs/discord.js/tree/main/packages/voice), [WhisperX](https://github.com/m-bain/whisperX).
