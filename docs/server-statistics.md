# Statistiques du serveur — livraison en quatre blocs

## Bloc 1 : collecte et premiers indicateurs (livré)

- Accès responsables uniquement : `/responsable/statistiques`, lien dans le NewDashboard.
- API : `GET /api/responsable/statistics?start=AAAA-MM-JJ&end=AAAA-MM-JJ&exclude_categories=ID,ID`.
- Périodes inclusives en **Europe/Paris**, 366 jours maximum ; heures UTC stockées pour gérer
  correctement les journées de 23/25 heures. Aucune collecte d'historique Discord.
- Totaux, participants distincts, salons actifs, pièces jointes ; tableaux quotidiens et
  classements des 20 premiers membres/salons. Filtres communs aux indicateurs.
- Les catégories Contact staff `1081957992896942166`, Staff `1321632937502052424` et
  Soutien `1499495158469758976` sont **collectées**. Toutes les catégories sont affichées par
  défaut ; une commande permet de masquer ces trois espaces. Les préférences de masquage
  sont locales au navigateur. Aucune exclusion de catégorie par l'IA n'affecte la collecte.
- Humains uniquement, messages normaux et réponses, avec ou sans texte et avec pièces jointes.
  Bots, webhooks, messages système, messages privés et autres serveurs sont ignorés.
- Les fils sont regroupés sous leur salon parent ; catégorie conservée au moment du message.
- La longueur compte les caractères du contenu brut, sans télécharger les fichiers ni conserver
  leur nom/URL. Tranches : 0–40, 41–160, 161–500, plus de 500. Mentions directes humaines uniques
  par message, hors auto-mentions ; destinataire de réponse lorsqu'il est fourni par Discord.

### Déploiement et stockage

Fonction active par défaut avec `DISCORD_GUILD_ID` et le bot existant. Pour la désactiver :
`SERVER_STATISTICS_ENABLED=false` dans l'environnement backend, puis redémarrer le backend.
Aucune clé IA supplémentaire et aucune migration manuelle. Index créés au démarrage.
MongoDB >= 4.2 est nécessaire pour les mises à jour par pipeline (pas de replica set requis).

Collections :

- `statistics_journal` : une contribution par ID de message, version, dimensions, longueurs,
  nombres, IDs de mentions/réponse, expiration **30 jours** (index TTL BSON).
  Aucun contenu, extrait, pièce jointe ou prompt IA.
- `statistics_buckets` : compteurs par heure UTC, membre, salon ; liens d'interaction numériques
  déjà agrégés pour le bloc 4. Les contributions temporaires servent de reçus idempotents.
  Un nettoyage horaire retire ces reçus lorsque l'heure entière est hors rétention.
  Les compteurs numériques restent conservés, même après expiration du registre.
- `statistics_channels` : noms/catégories et 30 dernières modifications observées à réception
  d'un message. `statistics_members` : dernier nom affiché connu des contributeurs.
- `statistics_meta` et `statistics_sessions` : début de collecte, calcul, erreurs et connexions.

Le collecteur s'exécute parallèlement à l'automodération, avant ses filtres. Ses erreurs ne
bloquent pas le traitement IA. Un traitement Mongo reprend les contributions en attente par
lots de 200, toutes les cinq secondes (rattrapage accéléré si un lot est plein). Chaque compteur
et son reçu sont écrits atomiquement ; un rejeu ne recompte pas le message. Une version plus
ancienne ne remplace pas une version récente. Les événements bruts couvrent aussi les
modifications/suppressions de messages absents du cache Discord, et les suppressions groupées.
La page recharge les agrégats toutes les minutes ; signal de connexion toutes les 30 secondes.

### Limites explicites

- Une correction après expiration du registre ne modifie pas les anciens totaux.
- Une déconnexion/perte d'événement n'est pas compensée par un téléchargement du passé.
  Les connexions récentes, le signal du bot et les échecs de collecte sont affichés : absence
  de collecte et absence d'activité ne doivent pas être confondues.
- Un arrêt brutal laisse une fin de session non confirmée ; le signal devient périmé après 90 s.
- Les noms ne constituent pas une synchronisation complète de l'annuaire Discord.
- Une réponse dont l'auteur n'est pas fourni ne crée pas de lien d'interaction supposé.

## Bloc 2 : graphiques Apache ECharts (à réaliser)

Courbes heure/jour/semaine/mois/année, comparaison de périodes de même durée (journée en
cours comparée jusqu'à la même heure), heatmap jours/heures, salons/catégories, membres,
distribution des longueurs. Graphiques cliquables, filtres communs, transitions discrètes,
mobile, tableaux accessibles et couverture de collecte. Une seule bibliothèque principale.

## Bloc 3 : membres et rétention (à réaliser)

Arrivées/départs/effectif/croissance, ratio actifs/effectif, premier message, accueil des nouveaux,
cohortes J+7/J+30 (présence et participation séparées), régularité, retours après 30 jours et
renouvellement des participants. Les métriques dépendantes des événements membres auront
leur propre date de disponibilité ; elles ne seront pas inventées à partir de l'historique absent.

## Bloc 4 : interactions et équilibre (à réaliser)

Mentions et réponses, diversité et réciprocité, participation entre catégories, estimation des
cercles restreints, concentration chez les 1/5/10 premiers contributeurs, indice explicable
(volume/régularité/diversité), déclin/reprise et périodes inhabituellement calmes.
Délai de réponse et messages sans réponse uniquement avec une définition explicite de
l'interaction et une couverture suffisante : aucune conversation supposée entre voisins.

## Vérification et livraison convenues

Tests ciblés par bloc, sans screenshots. Commit prêt à push après chaque bloc. Test global
uniquement après le bloc 4. Ne pas poursuivre automatiquement le bloc suivant avant le feu
vert de l'utilisateur. Les données du bloc 1 continuent à s'accumuler entre les livraisons.
