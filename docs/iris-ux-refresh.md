# Iris — palette et motion validés

Les règles à suivre pour les prochaines évolutions sont regroupées dans la [charte graphique et UX d’Iris](charte-graphique-iris.md).

L’accueil garde sa structure actuelle, ses données et ses contrôles de rôles. La barre latérale n’est pas réintroduite. Les prototypes et leurs données fictives restent hors du code livré.

## Présentation

- Surfaces claires neutres, texte lisible et accents ponctuels lavande, sauge, framboise, pêche et bleu.
- Logo typographique `iris.` avec symbole floral dans la barre supérieure. Le lien ramène à l’accueil.
- Favoris, recherche, statut, notifications, profil et déconnexion conservés.
- Blocs Ma journée, équipe, dossiers, responsable, helper, animateur et engagements conservés selon les accès réels.
- Cartes de dossiers neutres, repères colorés par famille, outils responsable organisés en trois groupes.
- Grilles adaptées au mobile, thèmes clair et sombre conservés.

## Interactions

Les transitions durent généralement 160 à 240 ms et portent sur l’arrivée de page, les survols, pressions et changements d’état. Les panneaux, listes animées et la palette de recherche existants restent utilisés. Les contenus ne dépendent pas d’une animation pour être visibles.

Un bouton Accessibilité dans la barre supérieure permet de réduire les animations. Le choix est conservé dans `iris.motion`, synchronisé entre contrôles et onglets. Il fonctionne pour les effets CSS et les animations JavaScript des lignes/messages. La préférence système de réduction est toujours prioritaire. Si le stockage navigateur est refusé, le réglage fonctionne pour la session ouverte.

## Vérification

Tests ciblés : préférence motion et synchronisation, réduction système, absence de délai sur les lignes sortantes en mode réduit, listes et messages existants, dossiers, annonces, outils responsable et thème. Vérification visuelle des composants de production avec réponses API fictives locales, en desktop et mobile, clair et sombre. Aucun envoi externe réalisé pendant la vérification.

## Déploiement

```bash
cd /home/iris/app
git pull --ff-only origin codex/botghost-integration
docker compose up -d --build --no-deps frontend
```

Recharger Iris après le déploiement. Aucune migration, dépendance ou variable d’environnement supplémentaire.

## Extension aux pages métier

`IrisPages.css` reprend les tokens du dashboard sur les pages de dossiers, tickets, agenda, projets, équipe, bien-être, profil, ressources, tâches, notifications, statistiques et outils responsable. Le périmètre est limité à `AppShell.iris-ui` et aux portails de fenêtres ouverts dans cette interface. OasisGame garde sa présentation propre.

Les anciennes variables de chaque famille sont reliées à la palette commune sur leur racine, pour rester cohérentes même lorsque leur feuille de style est chargée par une route différée. Les cartes, titres, champs, onglets, tableaux et boutons utilisent des surfaces neutres et des accents ponctuels. Les catégories du calendrier et les états urgents, erreurs et suppressions gardent une couleur sémantique distincte. Les actions pastel utilisent une encre sombre dans le thème sombre pour garder un contraste lisible.

Les animations d’arrivée durent 220 ms, les transitions de contrôle 140 à 180 ms. Le déplacement au survol concerne uniquement les cartes navigables. Le déplacement des widgets, les positions du calendrier, les graphiques et les rendus Discord restent gérés par leur fonctionnalité. Les préférences de réduction des animations continuent de s’appliquer.

La connexion reprend le logo typographique et les surfaces communes. Le parcours OAuth reste inchangé. Vérification visuelle locale des véritables composants avec données fictives : projets, fenêtre de création, agenda, ressources, notifications et connexion ; desktop et mobile, thèmes clair et sombre. Cet aperçu ne se connecte pas au serveur.
