# Manuel de préparation du karaoké sur le Mac

Ce manuel couvre les modes de préparation, toutes les options de `prepare.py`, les vérifications des paroles et des timings, ainsi que les erreurs fréquentes.

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

Pour refaire les anciens morceaux avec une séparation de meilleure qualité, utiliser un nouveau dossier de sortie ou `--overwrite`, **sans `--reuse-stems`** : cette dernière option conserverait les anciennes pistes. Après un échec sur les paroles ou la mélodie, relancer exactement la même commande : les pistes WAV terminées sont conservées dans `.iris-stem-cache` à l’intérieur du dossier de sortie. Elles sont réutilisées uniquement si les empreintes de l’original, les réglages Demucs, l’intégrité et la durée des deux pistes correspondent. Le cache du morceau est supprimé après publication complète du paquet. Il reste local au Mac et ne doit pas être transféré sur le VPS.

L’alignement compare plusieurs phrases éloignées avant de décaler les repères LRC. Une phrase incomplète déclenche une recherche plus large puis, si nécessaire, un alignement du morceau entier ; un texte toujours incomplet provoque une erreur explicite, sans publier de paquet tronqué.

Le manifeste garde les modèles et réglages utilisés, ainsi que le nombre de mots à faible confiance. Un modèle plus grand réduit certaines erreurs mais ne garantit pas le texte chanté exact.

Après une mise à jour du script, réexécuter `.venv-karaoke-mac/bin/python -m pip install -r tools/karaoke/requirements.txt` pour installer également le moteur de hauteur. La nouvelle préparation Mac peut affiner les timestamps ; la relecture Anthropic sur le VPS les conserve ensuite exactement tels qu'importés.

Si l'alignement a terminé mais que l'export a échoué, `--resume-alignment` reprend le diagnostic `.alignment.json` du dossier de sortie. Le script vérifie l'empreinte de l'original, sa durée, sa langue et le modèle avant de l'utiliser ; Whisper et l'affinage ne sont pas relancés. Cette option ne réutilise pas automatiquement la séparation : `--reuse-stems` reste nécessaire si l'on dispose déjà d'un paquet complet valide dont reprendre les pistes. Ajouter `--overwrite` si des fichiers de sortie existent.

## Pipeline hybride : Demucs + RoFormer, IA et TIFA

Aucun traitement audio n’est lancé par l’installation. Les calculs lourds restent sur le Mac. Le backend n’ajoute que le relais d’arbitrage textuel, avec la clé Anthropic déjà configurée sur IRIS.

1. Demucs `htdemucs_ft` et BS-RoFormer Viperx 1297 séparent indépendamment le même original. RoFormer reçoit un WAV stéréo float décodé par FFmpeg. Les sorties sont contrôlées avant validation du cache. Les pistes ne sont pas mélangées : la paire Demucs sert à la lecture et à la mélodie ; RoFormer apporte un contrôle indépendant.
2. Whisper `large-v3` transcrit les deux voix isolées. Qwen3-ASR `0.6B` effectue une troisième transcription indépendante sur le mix original et, pour les langues prises en charge, son modèle ForcedAligner fournit aussi des timestamps. Les résultats sont mis en cache avec l’empreinte des fichiers et des versions.
3. Les paroles de référence sont comparées aux trois transcriptions. IRIS arbitre par lots de douze phrases et ne reçoit que les textes, jamais l’audio. Les phrases verrouillées restent inchangées ; les suppressions et déplacements sont refusés. L’arbitrage IA aide à choisir entre les candidats mais ne constitue pas une preuve acoustique.
4. Une ligne est refusée par défaut si aucune des trois reconnaissances ne correspond à au moins 50 % de son texte. Une ligne très incertaine ne doit donc plus être exportée silencieusement comme si elle était vérifiée.
5. MMS aligne les paroles, puis TIFA vérifie des fenêtres courtes sur les deux voix. Une correction TIFA n’est appliquée que si les conditions de cohérence sont satisfaites. L’export est refusé si le nombre de lignes à vérifier dépasse le plus grand de 3 ou 25 % des lignes, ou si le timing final diverge de celui de Qwen de plus de 1,5 s au-delà de ce même seuil. Les seuils sont des garde-fous, pas une mesure validée de précision.
6. TIFA-1.0 fourni ne prend pas en charge le français : pour cette langue, le pipeline utilise MMS et confronte ensuite les horaires à Qwen. D’autres langues sans aligneur Qwen gardent la transcription comme indice textuel ; elles ne peuvent pas fournir la comparaison indépendante de timestamps Qwen.

L’installation isole RoFormer, TIFA et Qwen dans des environnements dédiés pour préserver les dépendances Whisper/MMS. Qwen utilise `qwen-asr==0.0.6` et son modèle d’alignement. Le checkout TIFA est figé à `7b210ca36ff5a2b79187fb1727af58fc977cc301`, son modèle 1.0 est vérifié par SHA-256. RoFormer tourne sur CPU. Cette configuration consomme davantage de disque et le premier traitement Qwen télécharge ses modèles depuis Hugging Face ; TIFA japonais peut aussi télécharger UniDic.

### Installation sur le Mac

Depuis la racine du projet :

```sh
.venv-karaoke-mac/bin/python tools/karaoke/setup_hybrid.py
```

Cela crée `.env.karaoke-hybrid` avec un secret de relais propre à cette fonction. Le fichier est privé, ignoré par Git et conservé lors des installations suivantes. Il ne contient pas la clé Anthropic. Son URL par défaut est `https://api.loasis.app` ; utiliser `--api-url https://autre-api.exemple` lors de la première création pour une autre installation.

### Relais sur le VPS — une seule fois

Récupérer le commit du backend sur le VPS, puis transférer uniquement le fichier de configuration depuis le Mac (remplacer `TON_VPS`) :

```sh
scp .env.karaoke-hybrid root@TON_VPS:/home/iris/app/.env.karaoke-hybrid
```

Sur le VPS :

```sh
cd /home/iris/app
cat .env.karaoke-hybrid >> .env
docker compose up -d --build --no-deps backend
```

La clé `ANTHROPIC_API_KEY` existante reste sur le serveur. Le modèle d’arbitrage réutilise `TICKET_SUMMARY_MODEL` ; le paramètre facultatif `KARAOKE_ARBITRATION_MODEL` dans `.env` permet d’en choisir un autre. Les candidats, les décisions et le modèle sont journalisés dans MongoDB, collection `karaoke_preparation_arbitrations`. L’API est protégée par le secret dédié ; elle n’expose pas une fonction d’IA publique.

### Génération — à lancer manuellement sur le Mac

```sh
set -a
source .env.karaoke-hybrid
set +a
caffeinate -i .venv-karaoke-mac/bin/python tools/karaoke/prepare.py \
  "$HOME/Music/Chansons" \
  --output "$HOME/Music/Karaoke-haute-qualite" \
  --device cpu --hybrid --overwrite
```

Le script contrôle l’accès au relais avant de commencer Demucs. Les modes précédents restent utilisables sans `--hybrid`. Le mode hybride choisit automatiquement MMS + TIFA ; ne pas ajouter `--allow-estimated` pour contourner un désaccord. Pour réutiliser des pistes Demucs d’un autre dossier, `--reuse-stems` exige un paquet complet valide pour chaque morceau. Une préparation japonaise échouée ne constitue pas un paquet réutilisable ; son cache WAV vérifié est repris automatiquement dans le même dossier de sortie.

Diagnostics conservés : `.demucs.transcript.json`, `.roformer.transcript.json`, `.qwen-transcript.json`, `.candidates.json`, `.arbitration.json`, `.hybrid.json`, `.ctc-baseline.json`, `.tifa.json` et `.quality.json`. Le dernier regroupe les lignes à vérifier, les timings incertains et les désaccords. En cas de refus, consulter `.candidates.json`, `.hybrid.json`, `.tifa.json` et `.quality.json` avant de forcer. Les caches sont liés aux fichiers et modèles ; `--refresh-arbitration` redemande à IRIS de choisir parmi les candidats en cache. Les pistes restent dans les caches locaux pour les reprises : ne pas copier les dossiers cachés `.iris-*` sur le VPS.

### Les options du mode hybride

- `--hybrid` active Demucs + RoFormer + Whisper + Qwen + arbitrage IRIS + MMS/TIFA. Il impose `--aligner tifa` et requiert l’installation Mac, `.env.karaoke-hybrid`, un relais IRIS joignable et le secret correspondant sur le serveur.
- `--allow-unverified-lyrics` autorise la génération même si des lignes n’ont pas assez de correspondance dans les reconnaissances. À utiliser seulement après avoir relu/corrigé les paroles ; le seuil normal est là pour empêcher la publication de lignes non confirmées.
- `--allow-unverified-timing` autorise l’export malgré trop de lignes signalées par TIFA ou un désaccord important avec Qwen. Cela ne répare pas le timing : le résultat doit être contrôlé à l’écoute.
- `--refresh-arbitration` ignore le résultat d’arbitrage en cache et interroge le modèle IRIS actuel. Les transcriptions et séparations valides restent réutilisables. Cette option ne se combine pas avec `--resume-alignment`.

### Référence complète des options

| Option | Effet |
| --- | --- |
| `DOSSIER` | Dossier source des chansons. Uniquement les fichiers audio pris en charge ; les liens symboliques sont ignorés. |
| `--output DOSSIER` | Dossier de sortie obligatoire, distinct du dossier source. |
| `--recursive` | Inclut les sous-dossiers du dossier source. |
| `--overwrite` | Remplace les résultats de sortie déjà présents. |
| `--device auto\|cpu\|mps` | Périphérique Demucs. `auto` utilise MPS si disponible et retente en CPU en cas d’échec. |
| `--aligner whisper\|mms\|tifa` | Choix d’alignement. `tifa` nécessite `--hybrid`; `--hybrid` choisit TIFA automatiquement. |
| `--hybrid` | Active le pipeline complet avec troisième reconnaissance Qwen et contrôles renforcés. |
| `--allow-unverified-lyrics` | Ignore le blocage des paroles insuffisamment corroborées. |
| `--allow-unverified-timing` | Ignore le blocage de timing lié aux contrôles TIFA/Qwen. |
| `--refresh-arbitration` | Redemande l’arbitrage textuel au relais IRIS. Incompatible avec `--resume-alignment`. |
| `--model tiny\|base\|small\|medium\|large-v3` | Modèle Whisper ; `large-v3` par défaut. Plus petit = généralement moins coûteux, parfois moins précis. |
| `--demucs-model htdemucs_ft\|htdemucs` | Variante du séparateur Demucs. |
| `--shifts 1..8` | Nombre de prédictions décalées moyennées par Demucs (2 par défaut). |
| `--overlap 0.1..0.75` | Recouvrement des fenêtres Demucs (0.5 par défaut). |
| `--resume-alignment` | Reprend un diagnostic d’alignement valide du même fichier, modèle et langue. |
| `--no-refine` | Désactive l’affinage final des timestamps. |
| `--pitch-engine crepe\|pyin` | Modèle d’extraction de la hauteur de référence (`crepe` par défaut ; `pyin` plus léger). |
| `--language CODE` | Force la langue, par exemple `en`, `fr`, `it`, `ja`. Omettre pour la détection automatique. |
| `--threads 1..16` | Nombre de threads donné au séparateur RoFormer (4 par défaut). |
| `--no-lrclib` | Désactive la recherche de paroles sur LRCLIB. |
| `--no-reconcile` | Ne confronte pas les paroles LRCLIB à la transcription. |
| `--allow-estimated` | Autorise une estimation de timing quand l’alignement échoue. À éviter pour diagnostiquer des décalages. |
| `--reuse-stems DOSSIER` | Réutilise un paquet complet valide de ce dossier sans relancer la séparation Demucs. |

Les extensions audio actuellement reconnues sont `.mp3`, `.ogg`, `.opus`, `.m4a`, `.aac`, `.flac`, `.wav` et `.webm`. Depuis zsh, un `!` dans un nom de fichier peut déclencher l’expansion d’historique même dans certains guillemets : exécuter `setopt NO_BANG_HIST` avant des commandes contenant un titre comme `Gimme! Gimme! Gimme!`, ou échapper les `!`.

### Diagnostic rapide

- **« Relais IRIS non prêt » / HTTP 401 ou 503** : vérifier que `.env.karaoke-hybrid` a été chargé, que `KARAOKE_PREPARATION_SECRET` correspond exactement entre Mac et VPS et que le backend est à jour/configuré.
- **HTTP 502 pendant l’arbitrage** : le relais n’a pas obtenu de décision complète. Le lot de candidats est conservé sur le Mac ; corriger le relais ou relancer. Ne pas supprimer les fichiers `.candidates.json`.
- **Erreur Qwen / environnement absent** : relancer `tools/karaoke/setup_hybrid.py`, vérifier l’espace disque et la connexion internet du premier téléchargement. Les nouveaux modèles sont conservés dans le cache Hugging Face.
- **Refus “moins de 50 %”** : ouvrir `.candidates.json`, corriger le `.lrc`/`.txt` source si la référence est fausse ou si la version chantée diffère, puis relancer la même commande. Ne forcer qu’après contrôle humain.
- **Refus TIFA/Qwen sur le timing** : écouter les lignes listées dans `.tifa.json` et `.quality.json`. Les options de forçage publient malgré l’incertitude, elles ne corrigent pas la synchronisation.
- **Échec de build Docker « no space left »** : ce traitement s’exécute côté Mac et ses environnements ne font pas partie du build site. Le modèle Qwen est volumineux sur le Mac, mais le téléchargement de ses modèles n’ajoute pas de volume Docker au VPS.
- **Reprendre sans tout recalculer** : relancer la même commande dans le même dossier de sortie. Les artefacts et caches vérifiés sont repris. Pour remplacer les fichiers finaux ajouter `--overwrite`; ne pas effacer les dossiers `.iris-*` avant une reprise.

Pour afficher les arguments dans le terminal :

```sh
.venv-karaoke-mac/bin/python tools/karaoke/prepare.py --help
```

Ce pipeline n’a pas une précision de 99 % mesurée. Une évaluation à l’écoute reste nécessaire, particulièrement sur les chœurs, ad-libs, mélismes et lectures japonaises particulières.

## Comparer MMS CTC

`--aligner mms` place les paroles sur la voix isolée avec MMS sur CPU, indépendamment des timings Whisper. Whisper reste utilisé pour détecter la langue et transcrire quand le texte manque. Le moteur habituel reste `--aligner whisper` tant que la comparaison à l’écoute n’est pas validée. TorchAudio compatible est déjà dans les requirements Mac ; aucun paquet supplémentaire n’est ajouté au VPS. Le modèle MMS se télécharge une fois (environ 1,2 Go), puis reste dans le cache PyTorch ; sa licence est CC-BY-NC 4.0.

Pour comparer sans refaire Demucs ni remplacer les préparations existantes :

```sh
caffeinate -i .venv-karaoke-mac/bin/python tools/karaoke/prepare.py \
  "$HOME/Music/Chansons" \
  --output "$HOME/Music/Karaoke-MMS" \
  --reuse-stems "$HOME/Music/Karaoke-haute-qualite" \
  --device cpu --aligner mms
```

Il faut un paquet complet valide pour chaque morceau dans `--reuse-stems`. Sinon, retirer cette option : le cache de séparation du dossier de sortie est vérifié automatiquement. Ajouter `--overwrite` pour remplacer un résultat dans le même dossier.

MMS analyse des fenêtres avec recouvrement et garde leurs positions absolues. Des jokers absorbent les sons non transcrits entre phrases ; cela ne garantit pas qu’un texte incorrect sera refusé. Les scores faibles et durées suspectes figurent dans `Artiste - Titre.quality.json`. Les scores MMS et Whisper ne sont pas calibrés de la même façon : ne pas choisir simplement le plus grand score.

La confrontation avec Whisper est informative : les lignes mal reconnues, répétitions et lectures chantées ne sont plus supprimées. Les désaccords signalent des passages à écouter. La relecture Anthropic actuelle sur le VPS corrige le texte et les lectures après import, à timings fixes ; elle ne constitue pas encore un arbitrage avant alignement entre deux versions complètes.

Les nouveaux paquets japonais attachent les romaji aux moras en kana et aux groupes de kanji dont la lecture est connue. Un composé irrégulier reste groupé pour éviter d’inventer une lecture par kanji. Régénérer les anciens paquets pour bénéficier de ce découpage.

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
- `Artiste - Titre.quality.json` : passages incertains à vérifier (diagnostic local).
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
