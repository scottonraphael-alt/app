# Préparer le karaoké sur le Mac

Le VPS ne charge ni Whisper ni Demucs avec ce flux. Le traitement lourd et les premiers téléchargements de modèles ont lieu sur le Mac. Python **3.11** et FFmpeg sont recommandés pour la compatibilité des dépendances audio.

## Installation unique

Depuis la racine du dépôt :

```sh
brew install python@3.11 ffmpeg
"$(brew --prefix python@3.11)/bin/python3.11" -m venv .venv-karaoke-mac
.venv-karaoke-mac/bin/python -m pip install --upgrade pip
.venv-karaoke-mac/bin/python -m pip install -r tools/karaoke/requirements.txt
```

Ces paquets ne font partie d'aucun build Docker du site.

## Traiter un dossier

Nommer les morceaux `Artiste - Titre.mp3` (ou WAV, FLAC, M4A, OGG…). Un fichier `Artiste - Titre.json` facultatif peut préciser `title`, `artist`, `album`, `source` et les alias. Une LRC ou un TXT existant est utilisé avant LRCLIB ; à défaut, Whisper transcrit le chant. La recherche utilise aussi le titre dans les métadonnées audio, notamment son écriture originale. Les paroles LRCLIB non synchronisées peuvent être alignées si aucune LRC compatible n'est disponible. La langue est détectée automatiquement.

```sh
.venv-karaoke-mac/bin/python tools/karaoke/prepare.py \
  "$HOME/Music/Chansons" --output "$HOME/Music/Karaoke-prepare"
```

Le dossier de sortie doit être séparé du dossier source. Les originaux ne sont jamais modifiés. Les morceaux sont traités un par un et les erreurs sont consignées dans `preparation-report.json`. Les noms identiques sont refusés pour éviter un écrasement. Une sortie valide est ignorée lors d'une nouvelle exécution ; utiliser `--overwrite` pour la régénérer.

Options utiles :

- `--device auto` utilise MPS pour Demucs sur un Mac compatible, CPU sinon. Si Demucs échoue sur MPS, ce mode relance automatiquement la séparation complète sur CPU. `--device cpu` permet de contourner directement un problème MPS. Whisper reste sur CPU pour la compatibilité de son alignement.
- Le réglage par défaut privilégie la qualité pour **tous les nouveaux morceaux** : Whisper `large-v3`, Demucs `htdemucs_ft`, deux prédictions décalées moyennées, recouvrement de 50 %, puis affinage des timestamps à 50 ms sur la voix isolée. La hauteur utilise le modèle `CREPE full`, avec filtrage des silences et de la confiance, et reste calculée sur la voix isolée. Le temps dépend du Mac et du morceau et peut dépasser dix minutes. Les modèles sont téléchargés automatiquement la première fois.
- `--model medium` ou `--model small` réduit le coût de reconnaissance si nécessaire. `--demucs-model htdemucs --shifts 1 --overlap 0.25 --no-refine --pitch-engine pyin` propose un traitement plus léger. Ces options ne changent pas les modèles installés sur le VPS.
- `--language ja` impose une langue si la détection est mauvaise.
- `--recursive` parcourt les sous-dossiers.
- `--no-lrclib` évite la recherche de paroles en ligne.
- Pour les langues japonaise, chinoise et coréenne, les résultats LRCLIB uniquement romanisés sont écartés : les paroles doivent rester dans leur écriture originale et la lecture latine se place au-dessus. Si aucune version compatible n'est trouvée, la transcription locale sert de source. Fournir une LRC correcte dans le dossier source reste préférable pour corriger une erreur de transcription.
- `--reuse-stems "$HOME/Music/Karaoke-prepare"` réutilise une préparation existante vérifiée du même fichier audio pour recalculer paroles et mélodie sans relancer Demucs. On peut écrire dans un autre dossier pour comparer les résultats ; pour remplacer le dossier existant, ajouter `--overwrite`.
- Un fichier `Artiste - Titre.txt` placé avec l'original permet de fournir les paroles exactes, une phrase par ligne. La LRC reste prioritaire si les deux fichiers existent. Le script conserve ces lignes lors de l'alignement ; sans texte fourni, il regroupe les fragments de transcription en phrases chantées.
- Pour le japonais, l'alignement et l'affinage travaillent automatiquement sur les sons en kana, puis les kanji et les romaji sont remis dans le résultat. Les autres langues conservent leur alignement natif. Une lecture chantée particulière peut être précisée dans `Artiste - Titre.readings.json`, par exemple `{"cette phrase japonaise": {"le mot concerné": "sa lecture en kana"}}`. La phrase et le mot doivent correspondre aux paroles ; la lecture est propre au morceau. Une modification de ce fichier impose un nouvel alignement et invalide la reprise d'un ancien diagnostic.

Pour refaire les anciens morceaux avec une séparation de meilleure qualité, utiliser un nouveau dossier de sortie ou `--overwrite`, **sans `--reuse-stems`** : cette dernière option conserverait les anciennes pistes. Le manifeste garde les modèles et réglages utilisés, ainsi que le nombre de mots à faible confiance. Un modèle plus grand réduit certaines erreurs mais ne garantit pas le texte chanté exact.

Après une mise à jour du script, réexécuter `.venv-karaoke-mac/bin/python -m pip install -r tools/karaoke/requirements.txt` pour installer également le moteur de hauteur. La nouvelle préparation Mac peut affiner les timestamps ; la relecture Anthropic sur le VPS les conserve ensuite exactement tels qu'importés.

Si l'alignement a terminé mais que l'export a échoué, `--resume-alignment` reprend le diagnostic `.alignment.json` du dossier de sortie. Le script vérifie l'empreinte de l'original, sa durée, sa langue et le modèle avant de l'utiliser ; Whisper et l'affinage ne sont pas relancés. Cette option ne réutilise pas automatiquement la séparation : `--reuse-stems` reste nécessaire si l'on dispose déjà d'un paquet complet valide dont reprendre les pistes. Ajouter `--overwrite` si des fichiers de sortie existent.

## Fichiers produits

Pour `Artiste - Titre.mp3` :

- L'original est copié sans réencodage.
- `Artiste - Titre.lrc` : paroles Enhanced LRC avec balises de mots.
- `Artiste - Titre.pitch.json` : hauteur de référence, pas de 100 ms.
- `Artiste - Titre.inst.mp3` : instrumental.
- `Artiste - Titre.voix.mp3` : voix guide.
- `Artiste - Titre.energy.json` : courbes d'énergie des pistes, battements et drops possibles.
- `Artiste - Titre.karaoke.json` : manifeste portable, paroles et romaji alignés, langue, empreintes d'intégrité.
- `Artiste - Titre.json` : métadonnées du morceau.
- `Artiste - Titre.alignment.json` : diagnostic texte/timestamps sur le Mac, conservé pour comprendre une erreur sans perdre le résultat brut du modèle. Ce fichier n'est pas nécessaire à la lecture sur le VPS.

**Copier l'ensemble**, en conservant les noms et leur voisinage, dans le dossier monté en `KARAOKE_DIR` sur le VPS (par défaut `/data/karaoke` dans le conteneur backend). Il ne suffit pas de copier seulement l'instrumental. Le dossier utilise actuellement le volume Docker `karaoke-music` : on peut y copier les fichiers via un conteneur ou le remplacer par un montage du dossier musical de l'hôte, selon l'installation.

Exemple de copie locale vers le conteneur, après transfert du dossier préparé sur le VPS :

```sh
docker compose cp /chemin/sur/le/vps/Karaoke-prepare/. backend:/data/karaoke/
```

Ne pas effacer le volume existant. Le catalogue relit les morceaux sous quelques secondes ; actualiser la liste ou sélectionner à nouveau le morceau après une copie. Les pistes `.inst.mp3` et `.voix.mp3` ne sont pas présentées comme des chansons distinctes. Les signatures sont fondées sur le contenu, donc déplacer les fichiers du Mac au VPS ne casse pas la préparation.

## Mettre à jour le VPS

Arrêter l’ancien worker lourd s’il était utilisé, puis reconstruire le site et, si nécessaire, le récepteur vocal :

```sh
docker compose stop karaoke-preparation
docker compose up -d --build --no-deps backend frontend
docker compose --profile karaoke up -d --build --no-deps karaoke-voice
```

MongoDB doit déjà fonctionner. Le profil `karaoke` ne démarre plus Whisper/Demucs ; l’ancien worker lourd demande explicitement `karaoke-cpu`. Le service vocal est facultatif pour le mix personnel, les effets et le guide de référence.

## Lecture

Chaque joueur dispose d'un curseur **Voix guide**, mémorisé sur son appareil : 0 % = instrumental seul, 100 % = instrumental avec la voix guide. Cela ne modifie jamais la lecture ni le mix des autres joueurs. Le son original est conservé comme repli si une piste séparée n'est pas disponible.

Les deux pistes séparées sont décodées dans le navigateur, puis démarrées ensemble sur une même horloge Web Audio, avec le même point de départ et la même vitesse. Les pauses, sauts et reprises les concernent toujours ensemble. Une seule paire de pistes est gardée pour le morceau courant ; le chargement initial peut prendre plus longtemps qu'une lecture en streaming. Sans Web Audio ou si une piste échoue, le lecteur revient au morceau original.

Les battements et l'énergie préparés pilotent le fond, avec une montée avant les drops repérés. La voix isolée fait briller les paroles. Sans préparation, l'analyse Web Audio réagit au volume et aux basses du mix, y compris pour les extraits Deezer. Les effets sont désactivés par « réduire les animations » ; les éclats sont espacés d'au moins 3 secondes.

Le **Guide de notes** est optionnel et fonctionne sans micro. Le réglage **Mon octave** transpose uniquement le guide de l'utilisateur. Avec OasisLink et son accord actif, le joueur voit son historique vocal sous forme de briques jaunes à la hauteur réellement chantée, ainsi que sa justesse ; les compteurs de vibratos et glissandos sont des estimations, pas une mesure certifiée. Ils nécessitent la nouvelle version du récepteur vocal (fenêtres de 100 ms décalées de 50 ms), et ne modifient pas le score. Aucun enregistrement de voix n'est conservé.

## Relecture IA sur le VPS

IRIS réutilise `ANTHROPIC_API_KEY` du backend. Aucune clé n'est nécessaire sur le Mac et aucun paquet audio supplémentaire n'est installé sur le VPS. Au premier chargement d'un morceau préparé, IRIS lance la relecture en arrière-plan ; la lecture reste disponible. Le résultat est conservé dans MongoDB (`karaoke_lyric_reviews`), avec les corrections avant/après et les passages signalés. Une nouvelle préparation ou un changement de modèle déclenche une nouvelle relecture.

L'API reçoit le titre, l'artiste, la langue et les blocs de texte identifiés, sans audio ni timestamps. L'IA ne peut proposer que du texte pour des identifiants existants. Le code refuse les ajouts/suppressions de blocs, les réponses invalides et toute modification des timestamps. Les romaji des blocs corrigés sont recalculés ; les originaux sur disque restent intacts. Les corrections sont rechargées automatiquement dans le navigateur une fois prêtes.

Les lectures latines existantes sont également relues dans le contexte des phrases. L'IA peut proposer un romaji différent pour un kanji ambigu sans modifier son texte ni son timing. Ce changement de lecture est conservé dans l'historique avant/après. Une lecture particulière propre à l'interprétation chantée ne peut pas être garantie sans écouter l'audio ; les cas incertains doivent être signalés.

Une lecture confirmée dans `.readings.json` est marquée `reading_locked` dans le paquet : la relecture IA la conserve, avec son texte japonais, au lieu de revenir à une lecture de dictionnaire. Les indices des sons alignés servent à retrouver les horaires des mots affichés ; le script refuse un résultat auquel des sons fournis manquent.

Configuration facultative du backend : `KARAOKE_LYRICS_AI_MODEL` (par défaut le modèle de synthèse déjà configuré dans IRIS), `KARAOKE_LYRICS_AI_ENABLED=false` pour désactiver. Une seule chanson est relue à la fois ; les demandes simultanées sont dédupliquées. Les erreurs conservent les paroles d'origine, avec au plus trois tentatives espacées. Les appels utilisent les crédits Anthropic du serveur, une relecture par version de chanson.

L'IA peut encore se tromper. Sans écouter l'audio, elle ne peut pas garantir le mot exact ni corriger un vrai décalage temporel. Ces cas sont signalés ; une LRC ou un TXT correct reste la référence pour réaligner le morceau sur le Mac.

Les notes sont extraites automatiquement de la voix isolée : chœurs, harmonies, vibratos et rap peuvent produire un guide imparfait. Les drops détectés sont des variations d'énergie, pas une annotation humaine des couplets et refrains. Évaluer les premières chansons et corriger les paroles à la source si nécessaire.

Lorsqu'une LRC compatible est disponible, ses repères servent de fenêtres de recherche pour aligner chaque phrase sur la voix. Les limites des mots sont recalculées à partir du son, puis affinées. Cela évite de traverser librement un long passage instrumental en décalant les phrases suivantes. Si les premiers repères ne sont pas confirmés, le script revient à l'alignement global. Les mots auxquels le modèle attribue une durée nulle restent dans le texte et sont signalés comme incertains ; ils ne sont plus supprimés silencieusement.

La hauteur est bien calculée depuis `vocals.wav` produit par Demucs, ou depuis `.voix.mp3` en mode réutilisation. Les notes tenues sont découpées visuellement aux limites des paroles alignées. Cela ajoute des briques lisibles sur une même note ; les passages sans hauteur détectée restent vides.
