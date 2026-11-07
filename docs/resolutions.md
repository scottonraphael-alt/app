# Résolutions du serveur

Toute nouvelle suggestion `/suggestion` est enregistrée pour ouvrir une résolution dans le salon `1528506172145930381`. Les suggestions antérieures à cette fonctionnalité ne sont pas reprises automatiquement.

Le rôle Conseil `1321630788898258955` peut voter **Pour** ou **Contre**, puis changer son vote pendant les 3 jours de consultation. Un seul avis par membre est comptabilisé. Le rôle `DISCORD_RESPONSABLE_ROLE_ID` est le seul autorisé à **Approuver** ou **Rejeter**, y compris avant la fin des 3 jours. Un Responsable doit également avoir le rôle Conseil pour émettre un avis consultatif. Aucune majorité n'entraîne de décision automatique. À la fin des 3 jours, les avis sont fermés ; la résolution attend toujours la décision d'un Responsable. Une décision finale ferme tous les boutons et conserve son auteur et sa date.

Les panneaux suivent le modèle de référence : numéro annuel, demandeur, compteurs, titre, explications, Vote du Conseil, Acceptation Responsable et fil de discussion. La numérotation commence à 01 pour chaque année (Europe/Paris) ; elle ne reprend pas les numéros de l'ancien bot. Les rôles sont relus depuis Discord à chaque action. Les enregistrements et les votes survivent aux redémarrages. Le traitement de fond actualise les panneaux sous environ 5 secondes et reprend les échecs de livraison. Le bot nécessite les permissions Voir le salon, Envoyer des messages, Lire l'historique, Créer des fils publics et Envoyer des messages dans les fils.

Configuration facultative : `DISCORD_RESOLUTION_CHANNEL_ID` et `DISCORD_COUNCIL_ROLE_ID` remplacent les identifiants par défaut.

## Réutiliser le module

Depuis un service interne autorisé :

```python
from services.resolutions import create

resolution = await create(
    source_kind='suggestion',
    source_id=suggestion['_id'],  # stable et unique dans cette famille
    title=suggestion['title'],
    explanation=suggestion['explanation'],
    author_id=suggestion['author_id'],
    source_url='https://discord.com/channels/...',
    avatar_url='https://cdn.discordapp.com/...',
)
```

Le couple famille/source est idempotent. La publication est effectuée par le worker `resolutions` indépendant de la commande. La décision de gouvernance est enregistrée dans `resolutions.status` (`open`, `approved`, `rejected`) avec `decided_by` et `decided_at`. Les suggestions n’exécutent aucune action métier. Les résolutions de type `permanent_ban` approuvées sont traitées par le worker de bannissement décrit ci-dessous ; les autres familles restent consultatives. Ne transmettre au panneau que les informations adaptées aux personnes ayant accès au salon des résolutions.


## Journal et archives web

Après décision d'un Responsable, le résultat est publié une seule fois dans le journal `1525041331993448559` (surcharge : `DISCORD_RESOLUTION_JOURNAL_CHANNEL_ID`). Le message reprend le numéro, l'état Approuvée/Rejetée, l'auteur, les totaux d'avis, le titre, les explications et le décideur. Il ne contient pas de boutons de vote. La livraison utilise les reçus idempotents Discord et reprend les échecs. Les résolutions déjà décidées dans la base sans reçu de journal sont également publiées.

Le registre Iris est accessible à `/staff/resolutions`, via le lien Résolutions du tableau de bord de l'équipe. Il conserve toutes les résolutions de cette base, y compris celles en attente, propose une recherche, des filtres, une pagination et le détail des votes (identifiant Discord, avis, date), ainsi que des liens vers Discord. L'accès exige une session Iris et un rôle Conseil, Staff, Helper ou Responsable. Il ne migre pas l'historique de l'ancien bot.

Les Responsables disposent d'un formulaire pour choisir le prochain numéro de l'année courante. Pour continuer après `2026-24`, saisir `25` avant de créer la prochaine résolution. Le compteur ne peut pas revenir sur un numéro réservé et les références existantes ne changent jamais. Les modifications sont journalisées et un contrôle de concurrence refuse une mise à jour si une nouvelle résolution ou un autre Responsable a changé le compteur entre-temps. La nouvelle année dispose de sa propre séquence.


## Commande /résolution

La commande serveur `/résolution` propose deux choix, puis ouvre un formulaire privé :

- **Suggestion Staff** : titre et explications. Aucun message de vote public n’est créé.
- **Bannissement définitif** : titre, explications et sélection d’un membre **ou** identifiant Discord d’un compte absent. Si les deux sont renseignés, ils doivent désigner le même compte.

La création est réservée aux rôles Staff, Conseil, Responsable et Administrateur configurés. Les rôles sont revérifiés à l’envoi du formulaire.

Les deux types utilisent le compteur annuel, le panneau Components V2, les votes consultatifs du Conseil, le fil de discussion et le journal des résolutions existants. Le Responsable peut décider avant la fin des trois jours. Les votes et la décision restent dans le registre IRIS. Les créations, votes et décisions alimentent également les logs d’IRIS.

### Bannissement après approbation

Le bouton **Approuver et bannir** réserve l’exécution. Un vote du Conseil ou un rejet ne bannit personne. Le worker applique le bannissement définitif, sans suppression de messages, sous le verrou de sanction partagé du compte ciblé.

Avant l’exécution, le rôle Responsable du décideur, la permission de bannissement du bot, les hiérarchies et les protections existantes des membres Staff sont vérifiés. Un compte déjà banni n’est pas modifié. Pour un membre absent, Discord accepte le bannissement par son identifiant.

La sanction est inscrite au casier avec la référence de résolution et publiée dans les journaux de modération configurés. L’approbation de gouvernance et l’application effective du ban sont affichées séparément dans Discord et IRIS. Le casier est lié depuis l’archive.

Une interruption réseau après l’envoi entraîne une vérification de la raison d’audit unique du ban, sans nouvel envoi automatique. Les écritures du casier et les journaux reprennent indépendamment de la sanction native. Les blocages de permissions avant l’envoi sont revérifiés périodiquement.

Les contrôles de la commande distincte `/sanction` restent inchangés.

### Déploiement

Les destinations utilisent les réglages existants `DISCORD_RESOLUTION_CHANNEL_ID`, `DISCORD_RESOLUTION_JOURNAL_CHANNEL_ID`, `DISCORD_COUNCIL_ROLE_ID`, `DISCORD_RESPONSABLE_ROLE_ID` et les journaux de modération. Aucun secret ou service supplémentaire n’est nécessaire.

Reconstruire backend et frontend avec MongoDB démarré. La commande `/résolution` est enregistrée individuellement au démarrage d’OasisLink, sans écraser les autres commandes.
