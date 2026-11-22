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

## Raffinements de lecture et d’interaction

En-têtes et densité harmonisés, silhouettes de chargement sur les projets, dossiers de soutien, ressources et notifications, indicateurs d’onglet animés sur les projets, confirmations adaptées au thème et retours de pression discrets. Les formulaires de projet sont regroupés en sections, avec leurs actions fixes pendant le défilement et les erreurs reliées aux champs. Les fenêtres partagées de projet acceptent les tailles `sm`, `md` et `lg` ; les formulaires longs prennent tout l’écran mobile.

`PageMemoryProvider`, monté dans l’interface du compte, conserve les filtres des principales listes et la pagination des projets et familles de dossiers. Le retour navigateur restaure le défilement et, lorsque possible, le lien sélectionné après chargement. Une intervention de l’utilisateur interrompt cette restauration. La mémoire ne contient pas les données des dossiers et n’utilise ni `localStorage` ni `sessionStorage`.

## Confort supplémentaire

Dates et statuts mieux alignés, lecture des textes longs limitée en largeur, séparation des actions d’archivage et de suppression, aides accessibles sur les icônes communes et cibles tactiles de 44 px. Les marges de sécurité du téléphone sont prises en compte dans les barres d’action. La base de flex des en-têtes empilés est corrigée pour éviter une hauteur vide sur mobile.

Pendant l’enregistrement du brief d’un projet, les nouvelles modifications ne sont plus perdues à la fermeture de l’éditeur : celui-ci reste ouvert si la saisie a continué depuis l’envoi. Un échec conserve aussi le texte avec une indication près de l’éditeur. Les champs des formulaires partagés sont temporairement verrouillés pendant leur envoi et réactivés après une erreur.

## Repères d’état et mouvements localisés

Les statuts des dossiers et projets ainsi que la synchronisation des suivis utilisent un retour visuel local. Les boutons d’enregistrement partagés et le formulaire de projet réservent leurs libellés pour éviter les changements de largeur. Les tableaux de dossiers et de statistiques, la discussion des tâches et le panneau de suivi disposent de repères de débordement lorsque nécessaire.

Les sections de tâche se déplient avec des contrôles accessibles. Le dashboard replie ses blocs sans démonter leur contenu. La fermeture des fenêtres partagées revient discrètement vers leur déclencheur, sans déplacement sur les fenêtres plein écran et avec les durées et protections existantes. Les primitives sont documentées dans la section 13 de la charte.


## Composition éditoriale — 22 novembre 2026

L’accueil, les projets et la bibliothèque reprennent la seconde direction validée : titres avec accent typographique, destinations sous forme de cartes, vues Cartes/Liste et document réel mis en avant. Les contrôles communs et les en-têtes métier prolongent cette direction. Les données, rôles, filtres, pagination, actions et disposition enregistrée du dashboard sont conservés. Voir la section 14 de la charte pour les règles et les limites du prototype.

Aucune migration ni dépendance supplémentaire. Reconstruction du frontend uniquement pour cette évolution visuelle.
