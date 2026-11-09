# Site public de L’Oasis

Le dossier `dist/` contient les trois pages et leurs ressources. Nginx peut servir ce dossier directement, sans compilation.

| Page | Adresse après mise en ligne |
| --- | --- |
| Accueil | https://loasis.app/ |
| Conditions d’utilisation | https://loasis.app/conditions-utilisation/ |
| Politique de confidentialité | https://loasis.app/politique-de-confidentialite/ |

Les deux textes sont des brouillons. Ils indiquent Raph Scotton comme éditeur et responsable du traitement, le compte Discord `raph_scttn` pour les demandes, et la France pour l’hébergement. La durée prévue est de deux ans pour les scores, les favoris et les journaux. Le code actuel ne configure pas leur expiration à deux ans. Appliquer cette durée aux données concernées et valider les bases légales, notamment pour les classements, avant de retirer la directive `noindex`. Voir [les informations à fournir aux personnes selon la CNIL](https://www.cnil.fr/fr/informer-les-personnes).

## Repérer le dossier servi sur le VPS

Afficher les conteneurs du VPS.

```sh
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
```

Dans le proxy inverse, repérer la destination du domaine `loasis.app`. Si tu utilises Nginx Proxy Manager, consulte le **Proxy Host** correspondant et note son **Forward Hostname / IP**. Prends ensuite le conteneur web qui reçoit ce trafic.

```sh
site_container='NOM_DU_CONTENEUR_WEB'
docker exec "$site_container" nginx -T 2>&1 | grep -E 'server_name|^[[:space:]]*root[[:space:]]'
docker inspect --format '{{range .Mounts}}{{println .Type .Source "->" .Destination}}{{end}}' "$site_container"
```

La directive `root` indique le dossier servi **dans le conteneur**. Si ce dossier se trouve dans un montage, `Source` indique le dossier correspondant **sur le VPS**. Lorsque `root` pointe vers un sous-dossier de `Destination`, reporte le même sous-dossier sous `Source`.

## Copier les pages

Récupère le commit sur le VPS ou décompresse l’archive du site dans un dossier dédié. Le répertoire à copier contient directement `index.html`, `assets/` et les deux dossiers légaux.

Quand le dossier servi correspond à un montage inscriptible, sauvegarde son contenu avant d’ajouter les pages. Remplace les deux valeurs en majuscules par celles que tu as relevées. La copie concerne uniquement le site public de L’Oasis.

```sh
site_container='NOM_DU_CONTENEUR_WEB'
site_root='RACINE_NGINX_DANS_LE_CONTENEUR'
site_files='/home/iris/app/site-loasis/dist'
site_backup="$(mktemp -d /home/iris/loasis-backup.XXXXXX)"
docker cp "$site_container:$site_root/." "$site_backup/" &&
  docker cp "$site_files/." "$site_container:$site_root/"
```

Si le montage est en lecture seule, copie les fichiers depuis le VPS directement dans le dossier correspondant à `Source`, après sauvegarde. Si le conteneur n’a pas de montage pour ce site, configure un montage persistant de `site-loasis/dist` vers la racine Nginx dans son Compose ou dans sa configuration de lancement. Une copie dans la couche du conteneur disparaîtrait lors de sa recréation.

Après mise en ligne, ouvre les deux URL légales dans une fenêtre privée et vérifie qu’elles affichent chacune leur propre page sans connexion. Saisis alors les URL dans les champs **Terms of Service URL** et **Privacy Policy URL** d’OasisGame dans le [Discord Developer Portal](https://discord.com/developers/applications).

## Aperçu local

Depuis la racine du dépôt, lance :

```sh
python3 -m http.server 8772 --bind 127.0.0.1 --directory site-loasis/dist
```

Ouvre ensuite `http://127.0.0.1:8772/`.
