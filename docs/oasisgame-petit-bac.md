# Petit Bac dans OasisGame

Le menu ouvre un carnet multijoueur pour 2 à 12 joueurs, avec spectateurs, dans la charte sombre et pastel d’OasisGame.

## Préparation et manches

L’hôte choisit 3, 5 ou 10 manches, une durée de 60, 90, 120 ou 180 secondes, et de 4 à 8 catégories parmi 12 : prénom, ville ou pays, animal, métier, objet, fruit ou légume, sport, célébrité, film ou série, marque, vêtement et plante.

Chaque manche tire une lettre française parmi `ABCDEFGHIJKLMNOPRSTV`, sans répétition pendant la partie. Les rôles de participants sont fixés après le lancement. Les réponses, limitées à 60 caractères, sont enregistrées après 350 ms sans frappe et à la sortie d’un champ. Un envoi STOP contient aussi le dernier brouillon. Pendant l’écriture, seul le joueur reçoit ses propres réponses ; ni l’hôte ni les spectateurs ne reçoivent celles des autres.

Après 15 secondes, un joueur ayant rempli toutes les catégories avec la bonne lettre peut dire STOP. Le chrono arrête également la manche à son expiration. Le temps est contrôlé par le serveur.

## Correction et points

Les réponses sont alors publiques. Les réponses vides ou avec une mauvaise initiale valent automatiquement 0. Pour la pertinence et l’orthographe, les joueurs se corrigent entre eux : chaque participant peut contester une réponse d’un autre joueur. Une majorité stricte des autres participants est nécessaire pour la refuser. À deux joueurs, le vote de l’autre joueur suffit. Sans majorité contre, la réponse est acceptée. Il n’y a pas de dictionnaire catégoriel ni de validation par IA.

Un joueur peut retirer sa contestation avant de confirmer sa correction. La confirmation verrouille ses votes. La correction se clôt quand tous les participants confirment, ou automatiquement après 90 secondes, même si quelqu’un est absent.

Une réponse acceptée unique rapporte 10 points ; une réponse identique à celle d’un autre joueur accepté rapporte 5 points ; une réponse refusée vaut 0. La comparaison ignore casse et accents, et normalise les ligatures œ et æ. Les scores s’additionnent entre les manches. Les égalités finales sont conservées.

## Reconnexion

Le chrono continue pendant les déconnexions. Les brouillons déjà reçus par le serveur restent présents et reviennent à la reconnexion. Les caractères non transmis ne peuvent pas être récupérés. Les joueurs absents restent dans la partie jusqu’à son terme. L’hôte peut lancer la lettre suivante ou revenir au menu pour arrêter la partie. Les parties restent en mémoire et ne survivent pas à un redémarrage du backend.

## Déploiement

Aucune nouvelle dépendance ou variable d’environnement.

```bash
cd /home/iris/app
git pull --ff-only origin codex/botghost-integration
docker compose up -d --build --no-deps backend frontend
```

Fermer puis relancer OasisGame. Vérifier avec deux comptes la confidentialité pendant l’écriture, le STOP, la contestation d’une réponse et le calcul des doublons.
