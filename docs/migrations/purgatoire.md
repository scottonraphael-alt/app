# Purgatoire — fonctionnement expliqué par l'utilisateur

Précision utilisateur du 28 octobre 2026, après la lecture de `/panel moderation`.
Le système BotGhost n'était pas terminé : l'absence de suite sur ses boutons est
attendue. Cette fiche conserve la règle métier ; la commande `/purgatoire` et son
éventuelle configuration de rôle n'ont pas encore été examinées.

## Entrée et sortie

Le Purgatoire est une restriction temporaire d'accès au serveur, distincte d'un ban
ou d'une expulsion : le membre reste présent.

À l'entrée : mémoriser durablement son rôle d'accès antérieur (Membre ou Non validé),
retirer ce rôle et attribuer Purgatoire. L'accès attendu est limité à ses convocations
et à ses Contacts Staff. Les autres rôles conservés et leurs overwrites ne doivent
pas permettre d'élargir involontairement cette visibilité.

À la sortie : retirer Purgatoire et restituer le rôle d'accès mémorisé. Une nouvelle
activation pendant un Purgatoire existant ne doit pas remplacer cet état initial par
un état déjà restreint. Prévoir des actions idempotentes et une reprise sûre en cas
d'échec partiel d'attribution/retrait des rôles.

Entrées et sorties doivent être journalisées avec acteur, date, contexte et résultat.
Ne pas déduire que trois jours sans réponse à une convocation imposent un Purgatoire :
l'utilisateur a choisi une alerte au Staff suivie d'une décision humaine.

## Points à confirmer lors de l'analyse de la commande

ID du rôle Purgatoire, personnes autorisées à l'entrée et à la sortie, protection des
cibles Staff, paramètres/motif et éventuelle durée, règles de notification, ainsi que
les permissions effectives des salons et catégories. Aucun ID ni automatisme de sortie
n'est inventé à ce stade. Aucun code ni changement de rôles Discord n'est effectué.
