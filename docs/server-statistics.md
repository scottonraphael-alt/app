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

## Bloc 2 : graphiques Apache ECharts (livré)

- Apache ECharts 6.1.0, imports des seuls graphiques/composants utilisés, rendu SVG.
- Courbe avec zoom glissant et regroupement heure/jour/semaine/mois/année ; semaines
  commençant le lundi. Les heures répétées d'automne gardent un décalage UTC distinct.
- Heatmap lundi–dimanche × 24 heures, profil horaire, distribution des quatre tranches de
  longueur, moyenne en caractères et classements membres/salons/catégories.
- Filtres API supplémentaires : `channel_id`, `member_id`, `category_id`, `weekday` (0=lundi),
  `hour`, `granularity`, `compare`. Les clics filtrent tous les graphiques et indicateurs.
  Les fils restent regroupés dans leur salon parent. Version tableau avec boutons clavier
  pour chaque interaction, graphiques adaptatifs et respect du mouvement réduit.
- Comparaison avec les N jours calendaires précédents, mêmes filtres. Lorsque la période
  inclut aujourd'hui, les variations s'arrêtent à la dernière heure **complète** sur les deux
  périodes : les agrégats horaires ne permettent pas une comparaison à la minute fiable.
  Les totaux de la page incluent l'heure en cours ; la différence de fenêtre est indiquée.
- Les pourcentages demandent au moins 98 % de temps de connexion couvert sur chaque
  fenêtre et aucune erreur de collecte connue affectant ces données. Base zéro : aucun
  pourcentage infini. Une base insuffisante ne dessine pas une fausse courbe précédente.
- Les courbes des périodes précédentes sont alignées par jour calendaire, sans comparer
  artificiellement les heures manquantes/répétées des changements d'heure. En vue horaire,
  la comparaison est limitée aux indicateurs et n'ajoute pas de seconde courbe ambiguë.
- Couverture reconstituée à partir des connexions (fusion des fenêtres qui se chevauchent) ;
  arrêts sans fin confirmée arrêtés au dernier signal. Les données sans connexion observée
  apparaissent comme manquantes ; les contributions effectivement reçues restent visibles.
  Cette mesure décrit la connexion, pas une garantie de livraison de chaque événement.
- Pas de bibliothèque distante/CDN, aucun contenu des messages transmis à ECharts.


## Bloc 3 : membres et rétention (livré)

- Onglet **Membres et fidélisation**. Calcul demandé avec `include_members=true` afin de
  ne pas alourdir les lectures de l'onglet Activité. Accès responsables inchangé.
- Annuaire humain initial via Gateway `guild.chunk`, sans historique de messages. Lecture
  en tâche de fond avec délai maximal de 180 s et nouvelle tentative après une minute.
  Un nouvel annuaire est vérifié après reconnexion ; l'IA et la projection restent indépendantes.
- `on_member_join` et `on_raw_member_remove` (départ même sans membre en cache).
  Les événements sont sérialisés par processus ; séjours identifiés par membre/date d'arrivée,
  arrivées/départs dédupliqués. Les membres du premier annuaire ne deviennent pas de faux
  nouveaux membres. Un ancien participant déjà identifié dans les agrégats ne rejoint pas
  une cohorte de nouveaux membres à sa réarrivée. Un retour connu ne crée pas une nouvelle cohorte.
- Collections `statistics_memberships` (séjours/accueil/participation) et
  `statistics_membership_events` (arrivées/départs), sans contenu. Métadonnées de présence
  dans `statistics_members`. Dates de disponibilité propres à cette collecte.
- Effectif en fin de période ou au dernier instant connu ; le ratio d'actifs ne compte au
  numérateur que les participants encore présents à cet instant. Bots exclus partout.
  Les effectifs/arrivées/départs sont globaux ; les filtres d'activité s'appliquent à la
  participation, régularité et rétention d'activité. Le périmètre est rappelé dans la page.
- Croissance nette = effectif final − effectif initial vérifiés ; taux rapporté à l'effectif
  initial. Pas de taux si l'effectif initial ou la couverture sont inconnus. Comparaison avec
  la fenêtre précédente de même nombre de jours, jusqu'à la même heure de Paris si nécessaire.
- Une absence découverte après coupure n'invente pas un départ à une date précise :
  intervalle incertain depuis la dernière présence vérifiée, ancien effectif inconnu dans
  cet intervalle, effectif actuel corrigé. Les départs observés restent distincts des ajustements.
- Cohortes quotidiennes des premières arrivées observées depuis l'activation. À J+7/J+30 :
  présence à la fin de cette journée calendaire parisienne, activité = au moins un message
  dans cette journée avec les filtres courants. La journée doit être terminée. Dénominateurs
  propres aux mesures ; couverture insuffisante ou recul insuffisant => valeur inconnue.
- Première participation : envoi observé sous 24 h / 7 × 24 h / 30 × 24 h après arrivée.
  Accueil : mention/réponse explicite humaine reçue dans les sept premiers jours, nombre
  d'accueillants distincts. Ces faits d'envoi sont conservés même si le message disparaît
  ensuite ; ils ne recopient aucun texte. Traitement idempotent en fond à partir du registre.
- Régularité : jours actifs et part des jours de la période, classement et distribution.
  Renouvellement : participants communs, nouveaux sur cette période (pas forcément nouveaux
  sur le serveur), et absents par rapport à la précédente. Premiers participants = première
  activité connue dans les agrégats, sans supposer l'activité antérieure à la collecte.
- Retours : au moins 30 jours de silence sur **tous** les salons, pas seulement dans le
  filtre courant. Marge conservatrice d'une heure liée à la précision des agrégats ; pas
  de retour inféré si le mois de silence n'est pas suffisamment couvert.
- Les données anciennes ne sont jamais fabriquées. Les cohortes J+7/J+30 apparaissent
  progressivement après déploiement. Les métriques dépendant des observations en attente
  restent signalées, sans masquer les cohortes anciennes pour des messages récents sans lien.
  Pendant une nouvelle vérification de l’annuaire, l’effectif reste celui du dernier snapshot
  vérifié et est signalé comme ancien. La disponibilité de l'annuaire et de son dernier signal est affichée.


## Bloc 4 : interactions et équilibre (livré)

- Onglet **Interactions et équilibre**, calcul demandé avec `include_interactions=true`.
  Les filtres communs restent appliqués ; le focus sur un membre inclut aussi les signaux reçus.
- Signaux = mentions directes + réponses avec auteur identifié. Le même message peut fournir
  deux signaux vers une personne ; ce n'est pas un compte de discussions uniques. Interlocuteurs
  distincts = union dédupliquée des contacts envoyés/reçus, classement indépendant du volume.
- Réciprocité = paires ayant des signaux dans les deux sens / paires distinctes. Les auto-liens
  et les bots sont exclus. Mentions/réponses envoyées et reçues sont détaillées par membre.
- Concentration : part du top 1/5/10 avec nombre réel de contributeurs, courbe cumulée et
  contributeurs effectifs `1 / somme(parts²)`. Ce sont des descriptions, pas des prédictions
  de l'activité qui resterait après un départ.
- Indice descriptif = moyenne de volume logarithmique normalisé, jours actifs / jours éligibles,
  et interlocuteurs distincts / maximum du filtre, chacun sur 100. Composantes et formule
  accessibles. Indice inconnu sans interaction ou couverture suffisante ; non comparable
  directement entre deux filtres différents.
- Matrice des participants actifs en commun entre catégories. Couleur = part des membres
  de la catégorie en ligne également actifs dans la catégorie en colonne. Quinze catégories
  les plus fréquentées représentées, nombre total rappelé ; aucune conversation supposée.
- Cercles restreints : composantes de 2 à 5 personnes, au moins 3 signaux, une catégorie
  connue et aucune liaison extérieure dans le périmètre observé. Pourcentage des **signaux**,
  pas des discussions réelles. Estimation conservatrice ; dix groupes au maximum détaillés.
- Tendances : trois fenêtres de sept jours complets finissant à la fin de période sélectionnée
  (aujourd'hui exclu tant qu'incomplet), dates explicites. Variation de la dernière par rapport
  à la précédente ; hausse/baisse à ±20 %, reprise si hausse après baisse sur la fenêtre plus
  ancienne. Comparaison désactivable ; référence insuffisante ou zéro ne fabrique pas de taux.
- Silences inhabituels : zéro message sur une heure/journée **complètement observée** ;
  comparaison aux mêmes jours/heures des 28 jours précédant la période. Au moins trois
  références couvertes, moyenne ≥3 messages/heure ou ≥20 messages/jour. Pas d'alerte pour
  une nuit habituellement calme, une coupure, une heure incomplète ou une projection en attente.
  Trente créneaux au maximum détaillés, total exact. Aucune notification Discord ajoutée.
- Réponses : ajout du seul `reply_message_id` au registre temporaire. La première connexion
  après mise à jour fixe `reply_tracking_at`. Réponse non résolue en cache : auteur récupéré
  dans le registre, sans requête Discord ni stockage de contenu.
- Délai médian de première réponse **observée**, réponses à soi-même exclues. Pourcentage
  sans réponse explicite sous 24 h seulement parmi les messages dont les 24 h sont terminées
  et suffisamment couvertes. Tous les messages humains mesurables sont candidats, y compris
  les réponses : il ne s'agit pas d'affirmer qu'ils nécessitaient une réponse.
- Les mesures de réponse sont limitées aux 30 jours du registre et à leur propre date de
  disponibilité. Messages supprimés, réponses supprimées et références absentes ne sont
  pas reconstitués. Pas de faux historique pour les anciens messages.


## Vérification et livraison convenues

Tests ciblés par bloc, sans screenshots. Commit prêt à push après chaque bloc. Test global
uniquement après le bloc 4. Ne pas poursuivre automatiquement le bloc suivant avant le feu
vert de l'utilisateur. Les données du bloc 1 continuent à s'accumuler entre les livraisons.

Vérification ciblée des configurations graphiques réelles : depuis `frontend`,
`npm run test:statistics-charts` (SVG en mémoire, sans navigateur ni screenshot).

## Interface : lecture progressive (livrée)

- Navigation globale masquée seulement pendant le montage de la page ; restauration à la
  sortie, sur le même principe que le casier. En-tête, police, palette, boutons et onglets
  réutilisent les classes et jetons du casier.
- Trois grandes vues, chacune découpée en questions : activité, parcours des membres,
  interactions. Une seule analyse est montée à la fois ; les graphiques des autres sujets
  ne sont pas instanciés. Changement de sujet sans nouvelle requête API.
- Classements ouverts en tableau, choix explicite Graphique / Tableau pour chaque carte.
  Colonnes complémentaires repliables pour la diversité ; toutes les métriques restent accessibles.
- Définition visible pour chaque indicateur et carte, aide « Comprendre » ou « Comment lire
  ces données » avec interprétation, unités et limites. Quatre repères au premier niveau ;
  indicateurs supplémentaires, filtres avancés et détails de collecte à la demande.
- Navigation des analyses au clavier (flèches, début/fin), tableaux avec légendes, états de
  sélection explicites et défilement horizontal des onglets sur les petits écrans.
- Vérification ciblée de l’interface : 10 tests (dont masquage/restauration de la navigation,
  une seule analyse montée, lecture au clavier et conservation des filtres) ; build frontend.
  Aucun screenshot et aucune modification des calculs backend.

### Vérification globale après le bloc 4

- 1 180 tests backend hors ligne réussis sur 25 modules : quatre blocs statistiques,
  tickets, rôles/sessions, casiers, fichiers, imports, rappels et contrôles de sécurité.
- 18 tests frontend réussis sur les cinq suites disponibles.
- 16 configurations rendues par le vrai moteur ECharts en mémoire, sans screenshot.
- Build frontend de production réussi.
- Les dix anciens modules visant une preview externe ou un checkout `/app` ne sont pas
  exécutés contre un déploiement tiers. Cette vérification ne vaut pas test en production.
