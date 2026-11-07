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

Nommer les morceaux `Artiste - Titre.mp3` (ou WAV, FLAC, M4A, OGG…). Un fichier `Artiste - Titre.json` facultatif peut préciser `title`, `artist`, `album`, `source` et les alias. Une LRC existante est utilisée avant LRCLIB ; à défaut, Whisper transcrit le chant. La langue est détectée automatiquement.

```sh
.venv-karaoke-mac/bin/python tools/karaoke/prepare.py \
  "$HOME/Music/Chansons" --output "$HOME/Music/Karaoke-prepare"
```

Le dossier de sortie doit être séparé du dossier source. Les originaux ne sont jamais modifiés. Les morceaux sont traités un par un et les erreurs sont consignées dans `preparation-report.json`. Les noms identiques sont refusés pour éviter un écrasement. Une sortie valide est ignorée lors d'une nouvelle exécution ; utiliser `--overwrite` pour la régénérer.

Options utiles :

- `--device auto` utilise MPS pour Demucs sur un Mac compatible, CPU sinon. `--device cpu` permet de contourner un problème MPS. Whisper reste sur CPU pour la compatibilité de son alignement.
- `--model base` est plus léger ; `small` est le choix par défaut. La qualité n'est pas garantie sur le chant, en particulier avec chœurs, rap ou cris.
- `--language ja` impose une langue si la détection est mauvaise.
- `--recursive` parcourt les sous-dossiers.
- `--no-lrclib` évite la recherche de paroles en ligne.

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

Les battements et l'énergie préparés pilotent le fond, avec une montée avant les drops repérés. La voix isolée fait briller les paroles. Sans préparation, l'analyse Web Audio réagit au volume et aux basses du mix, y compris pour les extraits Deezer. Les effets sont désactivés par « réduire les animations » ; les éclats sont espacés d'au moins 3 secondes.

Le **Guide de notes** est optionnel et fonctionne sans micro. Le réglage **Mon octave** transpose uniquement le guide de l'utilisateur. Avec OasisLink et son accord actif, le joueur voit son propre repère orange et sa justesse ; les compteurs de vibratos et glissandos sont des estimations, pas une mesure certifiée. Ils nécessitent la nouvelle version du récepteur vocal (fenêtres de 100 ms décalées de 50 ms), et ne modifient pas le score. Aucun enregistrement de voix n'est conservé.

Les notes sont extraites automatiquement de la voix isolée : chœurs, harmonies, vibratos et rap peuvent produire un guide imparfait. Les drops détectés sont des variations d'énergie, pas une annotation humaine des couplets et refrains. Évaluer les premières chansons et corriger les paroles à la source si nécessaire.
