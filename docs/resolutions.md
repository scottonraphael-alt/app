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

Le couple famille/source est idempotent. La publication est effectuée par le worker `resolutions` indépendant de la commande. La décision de gouvernance est enregistrée dans `resolutions.status` (`open`, `approved`, `rejected`) avec `decided_by` et `decided_at`. Le module n'exécute aucune sanction ni autre effet métier : les futures fonctionnalités devront traiter explicitement la décision selon leurs propres règles. Ne transmettre au panneau que les informations adaptées aux personnes ayant accès au salon des résolutions.
