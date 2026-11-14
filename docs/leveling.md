# Guilde des aventuriers

OasisLink gère l’XP sur le serveur L’Oasis. Les rôles F à SSS fournis sont attribués selon le niveau. Un membre garde un seul rôle de rang. Ses autres rôles sont conservés.

## Progression

Passer du niveau `n` au niveau `n + 1` demande `100 + 20*n + 3*n²` XP. Le niveau 0 commence à 0 XP. La progression continue au-delà du rang SSS.

| Rang | Niveau minimum | XP totale minimum | Rôle Discord |
| --- | ---: | ---: | --- |
| F | 0 | 0 | 1453835191067082793 |
| E | 3 | 375 | 1453835377235333365 |
| D | 8 | 1 780 | 1453835417328681011 |
| C | 15 | 6 645 | 1453835496777056421 |
| B | 25 | 23 200 | 1453835520923799552 |
| A | 40 | 81 220 | 1453835540872036547 |
| S | 60 | 252 030 | 1453835569875521822 |
| SS | 85 | 683 230 | 1453835592914698384 |
| SSS | 110 | 1 443 805 | 1453835618013679636 |

À partir de 1 000 XP gagnées chaque jour, le rang S demande environ 8 mois, SS environ 23 mois et SSS environ 4 ans. Ces repères dépendent de l’activité et des bonus. Les récompenses futures appellent le même moteur.

## Gains d’activité

- Un message normal ou une réponse avec du texte ou une pièce jointe donne 20 XP au maximum toutes les 60 secondes par membre, tous salons confondus.
- Une minute complète en vocal donne 5 XP avec au moins deux participants humains éligibles. Le salon AFK, les membres assourdis et les auditeurs de scène sont exclus. Couper son microphone ne supprime pas l’XP.
- Le rang F multiplie les gains par 2 et le rang E par 1,5. Les gains sont des entiers, arrondis vers le bas.
- Un boost du serveur actif multiplie les gains par 2, cumulable avec le bonus du rang. Le gain d’un message est donc de 80 XP en F, 60 XP en E et 40 XP à partir de D pour un booster. Le nombre de boosts personnels ne change pas ce multiplicateur.
- Les bots, webhooks et messages système ne reçoivent aucune XP. Les éditions de messages ne donnent aucun gain supplémentaire. Les minutes de déconnexion d’OasisLink ne sont pas récompensées.

## Reprise de BotGhost

L’export du 14 novembre 2026, `bg_leveling_xp-3.csv`, est livré dans `backend/assets/leveling/botghost.csv`. Au premier démarrage connecté à L’Oasis, le moteur importe les **1 081 soldes de membres**, puis calcule leurs niveaux et rangs avec la nouvelle courbe. La ligne de valeur par défaut est ignorée. Le solde négatif est conservé, avec niveau 0, progression à 0 % et déficit dans l’XP restante.

Chaque version du CSV possède une empreinte et chaque solde possède un événement d’import unique. Une interruption ou une relance conserve les gains déjà obtenus. Un nouvel export applique la différence avec le solde BotGhost précédemment importé, y compris les baisses, tout en conservant les gains obtenus dans Iris. Le premier format d’import est repris automatiquement. Les bonus ne s’appliquent pas à l’import. Les membres partis gardent leur solde pour leur retour et sont exclus du classement.

Au déploiement, désactiver les gains et l’attribution des rangs de l’ancien système BotGhost. Placer le rôle d’OasisLink au-dessus des neuf rôles de rang et lui accorder **Gérer les rôles**. Le bot utilise les intents membres, messages et états vocaux déjà présents dans Iris. Le rattrapage initial des rôles s’effectue en arrière-plan.

## Commandes

`/carte` affiche sa propre carte. `/carte membre` affiche celle du membre choisi. Le message Components V2 comprend le nom affiché, l’avatar, le niveau, le rang, le total d’XP, le montant restant jusqu’au niveau suivant, le pourcentage et la position au classement. Il joint l’image originale du rang fournie dans `CardLV`.

`/classement` affiche 10 membres par page. L’option `page` ouvre directement une page. Les boutons précédent/suivant permettent de parcourir le registre pendant 15 minutes. Leur utilisation est réservée à l’auteur de la commande. Les égalités sont départagées par l’identifiant du membre.

## Utiliser le moteur depuis une autre fonctionnalité

```python
from services.leveling import grant

receipt = await grant(
    member_id,
    100,
    source='quest',
    event_id=f'quest-completed:{quest_id}',
)
```

`source` identifie la fonctionnalité. `event_id` doit être stable et unique pour une récompense donnée. Réessayer cet appel retourne le même reçu et attribue une seule récompense. Le moteur accepte les corrections négatives.

Les bonus d’activité s’appliquent avec `boost=True`. Le code appelant peut aussi transmettre `server_booster=member.premium_since is not None` depuis un membre Discord authentifié. Par défaut, une récompense de quête utilise exactement le montant fourni.

`services.leveling.progress(xp)` calcule les informations d’une carte. Les collections `leveling_accounts` et `leveling_events` stockent le solde et les reçus avec source, événement, montant et date. Le solde et son reçu de reprise sont écrits atomiquement dans le compte avant l’acquittement du journal. Cette procédure fonctionne avec le MongoDB standalone existant. Les changements de rang sont réconciliés par OasisLink, y compris les récompenses attribuées depuis d’autres fonctionnalités.
