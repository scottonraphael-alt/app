# Accueil personnalisable, notifications et brouillons

## Blocs de l’accueil

« Personnaliser » ouvre un mode édition. Un appui long de 550 ms sur une zone non interactive d’un bloc ouvre aussi ce mode ; le défilement ou un mouvement supérieur à 8 px annule l’appui long. Les liens et champs ne déclenchent pas l’édition.

- Déplacement à la souris ou au doigt par la poignée. Le bloc cible est encadré et le déplacement est appliqué au relâchement. Annuler le geste ne change pas l’ordre.
- Flèches dans les outils ou sur la poignée au clavier pour réordonner.
- Largeurs Petite, Moyenne, Large et Pleine (4, 6, 8 ou 12 colonnes). Sous 1000 px, une seule colonne conserve l’ordre et les tailles préférées pour l’ordinateur.
- Replier un bloc ou le masquer. « Ajouter un bloc » permet de retrouver les blocs masqués. Seuls les modules autorisés pour les rôles actuels sont proposés.
- « Terminer » enregistre explicitement sur le compte via `/profile/me/dashboard-layout`. « Annuler » conserve la disposition précédente. « Réinitialiser » restaure les valeurs par défaut dans l’éditeur, à enregistrer ensuite.

Les configurations sont indépendantes entre comptes et disponibles sur plusieurs appareils après chargement. Si le chargement échoue, les blocs autorisés restent affichés et l’édition est désactivée pour ne pas remplacer une configuration inconnue. En cas d’échec d’enregistrement, les modifications restent ouvertes. Les nouveaux blocs autorisés sont ajoutés en fin de disposition. Deux éditions simultanées suivent le dernier enregistrement réussi.

L’édition rend le contenu des blocs inerte pour éviter les navigations involontaires. Les blocs utilisent les composants de production et leurs données réelles, sans copie de la maquette. Les transitions de déplacement respectent la réduction des animations.

## Notifications regroupées

La cloche et la page Notifications regroupent les activités chargées d’un même lien exact et d’un même jour UTC. Un groupe affiche la dernière activité et le nombre réel d’éléments non lus. Les crises, passations urgentes et éléments explicitement urgents restent individuels.

La cloche marque comme lus les éléments chargés du groupe ouvert. La page Notifications permet de déplier chaque groupe et conserve les actions individuelles. Les compteurs globaux et la pagination restent ceux du serveur ; les regroupements ne portent que sur les notifications déjà chargées. Cela ne modifie pas les envois Web Push ni leur fréquence.

## Brouillons personnels de suivi

Les champs Points de vigilance, Compte-rendu d’échange et État du suivi disposent d’une copie de récupération privée sur Iris. Ils sont protégés après 1 seconde sans frappe, ou au maximum après 5 secondes de frappe continue. Les écritures sont sérialisées ; la fermeture d’une vue demande aussi l’enregistrement de la dernière copie connue. Une fermeture brutale, une perte réseau ou l’arrêt du navigateur peut empêcher la transmission des derniers caractères : l’état de protection est affiché et un avertissement de fermeture est demandé quand des changements ne sont pas protégés.

Les copies sont séparées du dossier partagé et exclues de la transcription et des entrées IA. Elles sont liées au compte authentifié et au ticket. L’API exige les droits habituels d’accès au suivi et vérifie aussi l’identifiant de session déclaré lors d’une écriture, pour éviter une écriture tardive sous un autre compte.

À la réouverture, « Reprendre le brouillon » est une action explicite. Si le dossier partagé a changé, un avertissement invite à vérifier les différences. Si du texte a déjà été modifié localement, son remplacement demande confirmation. « Enregistrer » reste nécessaire pour publier les champs dans le dossier partagé et efface la copie devenue inutile, tout en préservant une modification plus récente.

Les protections existantes du composeur d’annonces et de l’éditeur de réunions sont conservées. Aucun contenu de suivi n’est ajouté à `localStorage` par ce dispositif.

## Déploiement

Aucune dépendance de production supplémentaire. Reconstruire backend et frontend :

```bash
cd /home/iris/app
git pull --ff-only origin codex/botghost-integration
docker compose up -d --build --no-deps backend frontend
```

Les collections de profils et de brouillons sont créées à la première écriture. Aucun changement des accès métiers ni migration des dossiers existants.
