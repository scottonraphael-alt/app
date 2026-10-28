> Mise à jour : le raccordement au site est désormais développé. Voir [activation-iris.md](activation-iris.md) pour l’état actuel, les réglages et les limites du lot. Le document ci-dessous conserve l’état de la préparation.

# Vérifications : état du code préparé et raccordement à venir

Branche isolée : `codex/botghost-migration`, base `c89520a`. Aucun module ci-dessous
n'est chargé par le démarrage du bot, `server.py` ou le routeur React. Ce lot est une
**base de développement testée hors ligne**, pas un remplacement déjà opérationnel
de BotGhost. Aucun formulaire réel n'a été importé et aucun effet Discord exécuté.

## Fichiers préparés

- `backend/models/verification.py` : contrats stricts, cinq réponses obligatoires,
  requêtes versionnées et identifiants d'idempotence.
- `backend/services/verification_service.py` : dossier serveur/membre, tentatives,
  prise en charge atomique, second avis, plans d'action, formation, suppression réelle
  d'une tentative et qualification humaine des références IA.
- `backend/routers/verifications.py` : API Staff, opérations Responsable ; les
  consultations et opérations sont raccordées au service d'audit d'Iris.
- `backend/services/verification_jobs.py` : exécuteur à bail, étapes persistées,
  reprise après confirmation, réconciliation obligatoire d'un effet incertain.
- `backend/services/verification_discord.py` : panneau V2, formulaire à cinq champs,
  panneau Staff et confirmation privée des actions. Aucun enregistrement de commande.
- `backend/services/verification_archive.py` : lecture conservatrice de snapshots
  de messages/Components V2 et normalisation. Ni réseau ni import automatique.
- `backend/services/verification_advisory.py` : analyse Anthropic explicable,
  non décisionnelle, à la demande ; exemples sélectionnés par un Responsable,
  citations du candidat vérifiées, refus des références inventées. Non exposée à l'API.
- `backend/services/verification_timeline.py` : source de métadonnées pour la vue
  360°, sans lecture Mongo si le droit Staff n'est pas accordé.
- `frontend/src/pages/VerificationPages.jsx` et `Verifications.css` : liste paginée
  attente/archives, dossier, tentatives repliables, actions avec confirmation,
  historique et outils Responsable. Charte Casier, sans navbar, clair/sombre.

## Garanties déjà testées

Le remplacement Mongo conditionné par la révision arbitre les prises en charge
concurrentes. Les effets ne partent jamais dans la transaction HTTP : une décision
prépare un job, puis le worker confirme les effets séparément. Un formulaire en cours
ne peut pas être remplacé par un nouvel envoi non demandé ; un import historique ne
peut pas devenir la cible d'une décision sur le formulaire courant.

Les décisions Discord sont limitées à prise en charge, validation, ticket, clôture.
L'origine est définie par le serveur, jamais acceptée dans un corps de requête.
Refus, kick, ban et approfondissement passent par Iris. Les droits sont relus depuis
Discord, y compris avant les étapes d'exécution. Un ban définitif exige le rôle
administrateur de sanction actuel.

Les MP sont facultatifs pour terminer une action. Une étape obligatoire dont le
résultat est inconnu place le dossier en « Action à terminer » ; elle n'est jamais
répétée aveuglément. Le bail est renouvelé avant les étapes, avec nonce déterministe.

Formation = simulation sans effets Discord. Un passage ultérieur en mode réel ne
rejoue pas les effets simulés et ne rend pas ces décisions éligibles aux références IA.
La suppression efface les réponses et événements de la tentative, ses jobs et son
préavis embarqué ; les sources supprimées restent bloquées pour éviter leur réimport.
Elle ne supprime aucun ticket ou sanction distinct, ni les archives Discord.

Une archive sans date d'envoi garde une date inconnue : l'horodatage de sa copie
Discord n'est pas présenté comme celui du formulaire. Une décision ambiguë reste
inconnue. Le normaliseur est volontairement limité aux champs explicitement reconnus ;
il doit être confronté à des snapshots représentatifs des vrais fils avant import.

## Raccordements indispensables avant activation

1. Reprendre la dernière branche Iris, vérifier les évolutions de l'authentification,
   du bot, du casier, des tickets, des logs et de la vue 360°. Garder le module coupé
   jusqu'à la validation du parcours complet. Initialiser les index au démarrage.
2. Implémenter l'adaptateur Discord et le worker durable. Contrat :
   `authorize(job, step)`, `perform(step, payload, nonce) -> {confirmed: true}` et
   `reconcile(step, payload, nonce) -> applied | not_applied | unknown`.
   Aucun adaptateur de production n'est fourni dans ce premier lot.
3. Cet adaptateur doit relire le membre ciblé, interdire la sanction d'un Staff,
   appliquer les protections propriétaire/bot/hiérarchie et réutiliser les baux de
   rôles temporaires du module sanction. Les logs et le casier doivent suivre le
   parcours existant, sans créer de doublon à la reprise. Les sanctions réelles
   demeurent distinctes des formulaires supprimables.
4. Définir les effets `member_access`, `welcome`, `archive`, `create_ticket`,
   `notify_ticket`, `notify_closed`, `notify_clarification`, `notify_refusal`, `kick`,
   `ban`, `moderation_log`. Leur payload contient acteur, membre, formulaire, action,
   motif public, explication interne, thèmes, âge et indicateur de formation.
   Une action ambiguë doit pouvoir être réconciliée et réparée depuis Iris.
5. Raccorder l'arrivée du formulaire à une **outbox durable de notification Staff**,
   créer/réutiliser le fil privé, publier/actualiser le suivi, enregistrer les IDs de
   livraison. Recréer les vues persistantes au redémarrage. Les panneaux préparés
   seuls ne publient pas la notification Staff. Ne pas activer leur publication avant
   que cette livraison et le worker soient disponibles.
6. Raccorder `/panel verification` au sous-groupe existant, publication Responsable/
   Admin, sans synchronisation globale destructrice des autres commandes. Ne pas
   modifier les commandes BotGhost avant bascule convenue. Configurer les IDs des
   rôles Membre, Non validé et âges ; valider les permissions et destinations. Les
   quatre URL de GIF restent à extraire/configurer, sans en inventer.
7. Inclure l'API et les routes React derrière le droit Staff ; passer
   `responsable={isResponsable}` au détail. Ajouter l'accès au dashboard approprié.
   La route de détail attend `:memberId`. Les opérations administratives restent
   protégées côté API même si leur affichage est forcé dans le navigateur.
8. Brancher la source 360° après vérification Staff, conserver le garde existant
   Opérateur/Responsable de la page 360° et ses autres droits par source. Fusionner,
   trier et paginer les événements ; ajouter compteur, premier formulaire connu et
   statut d'admission. Ne pas confondre cette date avec l'arrivée Discord.
9. Préparer le collecteur des fils actifs **et archivés privés** du salon d'archives,
   avec pagination, auteur bot autorisé, rattachement au serveur et sauvegarde des
   références. Faire un inventaire à blanc des fiches reconnues/ambiguës, puis
   adapter les libellés du parseur sur des exemples réels. Import idempotent ; aucun
   ancien dossier ne devient automatiquement une référence d'acceptation/refus.
10. Raccorder le préavis après notification Staff, avec règles d'admission enregistrées
    et éditables par les Responsables, orchestration asynchrone, audit et message V2
    court. Le générateur utilise le plafond du modèle (`VERIFICATION_AI_MODEL`, sinon
    `TICKET_SUMMARY_MODEL`) et ne touche pas au plafond de modération à 3 000 tokens.
    Il ne persiste actuellement aucun résultat : avant cache/affichage durable,
    ajouter une invalidation fondée sur les références lors de suppression/retrait.
    Il retire les noms/champs d'identité structurés du contexte ; cela ne garantit pas
    l'anonymisation des informations librement saisies dans les réponses.
11. Finir les fonctions d'exploitation : reprise/réconciliation des effets dans Iris,
    réattribution Responsable en cas d'absence, sollicitation et notification du
    second avis, recherche/filtres avancés, qualification des archives historiques
    comme références après vérification humaine, suppression guidée d'un dossier
    entier, libellés et filtres des événements dans le journal Responsable.
12. Tester une fois le parcours bout en bout sur un environnement de test, puis
    rédiger le **manuel de formation PDF et sa fiche courte** correspondant au
    fonctionnement final. Ils ne sont pas encore produits pour éviter de documenter
    des écrans ou effets qui changeront lors du raccordement.

## Vérification de ce lot

Tests ciblés hors ligne, sans screenshots, sans appel Anthropic et sans serveur Discord :

```sh
# Depuis backend, avec l'environnement de test déjà installé
python -m pytest -q -n 0 tests/test_verification_preparation.py
# Depuis frontend, avec les dépendances de la branche
CI=true node node_modules/react-scripts/scripts/test.js --watch=false --runInBand --testPathPattern VerificationPages.test.jsx
```

L'import de `security_harness` remplace Mongo et Discord avant les modules applicatifs.
Les tests React simulent l'API et ne montent aucune page en production. Aucun test global
de l'application ni build production n'est revendiqué pour ces routes encore non montées.
