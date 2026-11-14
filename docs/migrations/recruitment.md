# Recrutement natif

Dans le salon public souhaité, un Administrateur ou un Responsable lance :

```text
/recrutement datedefindurecrutement:22/11/2026 20:00
```

La date suit le format `JJ/MM/AAAA HH:MM`, heure de Paris. Les dates passées,
impossibles ou ambiguës lors du changement d’heure sont refusées.

Le panneau reprend les textes, couleurs et organisation des captures fournies :
trois boutons de candidature, quatre fiches privées (Opérateur, Helper, Animateur,
engagement Staff) et un lien vers le Contact Staff. Les liens internes des fiches
ont été retirés à la demande de la propriétaire. Les pictogrammes utilisent les
équivalents Unicode ; les identifiants des emojis personnalisés des captures
n’étaient pas fournis. L’affichage final dépend du client Discord.

Les rôles sont ceux déjà configurés : `DISCORD_OPERATEUR_ROLE_ID`,
`DISCORD_HELPER_ROLE_ID`, `DISCORD_ANIMATEUR_ROLE_ID`, `DISCORD_COUNCIL_ROLE_ID`
et le rôle Administrateur de la politique existante. Si le rôle d’un poste n’est
pas configuré, son nom s’affiche sans mention. Le bouton support utilise
`CASEWORK_CONTACT_PANEL_CHANNEL_ID`, alimenté par les réglages existants d’Iris.

| Question | Opérateur | Helper | Animateur |
| --- | --- | --- | --- |
| Présentation | Publique | Publique | Publique |
| Motivations | Publiques | Publiques | Publiques |
| Pourquoi vous et pas un autre ? | Privée | — | Privée |
| Point de vue sur l’aide | — | Public | — |
| Disponibilité | Privée | Privée | Privée |

Chaque réponse est obligatoire et limitée à 550 caractères UTF-16, pour conserver
les quatre réponses intégrales dans le message de résolution existant sans dépasser
les limites Discord. Les formulaires annoncent clairement le caractère public ou
privé de chaque question. Aucun texte n’est tronqué.

La candidature publique contient la mention du candidat, le poste, son avatar,
sa date d’arrivée et uniquement les réponses publiques. Le dossier complet est
enregistré comme résolution `recruitment`, dans `DISCORD_RESOLUTION_CHANNEL_ID`,
avec un lien vers la candidature publique. Il utilise le vote consultatif de trois
jours du Conseil, la décision du Responsable et le journal existants. Ces salons
doivent conserver leurs accès privés habituels : les réponses privées sont aussi
conservées dans les archives des résolutions. Aucun rôle n’est attribué automatiquement.

Une candidature par membre, par poste et par campagne est autorisée. Les réservations
reposent sur une clé MongoDB unique, y compris en cas d’envois simultanés. Une campagne
et ses candidatures sont enregistrées avant leur publication. Le traitement de fond
`recruitment` reprend les envois avec le système existant de reçus Discord et crée
une seule résolution par candidature. Une panne après publication publique ne provoque
pas un deuxième message public à la reprise.

Les boutons sont restaurés au redémarrage. À l’échéance, les boutons de candidature
sont désactivés au prochain cycle (environ cinq secondes), et le contrôle de date
à la soumission bloque immédiatement les anciens formulaires encore ouverts.
Les candidatures acceptées avant la fermeture continuent d’être traitées après.

Validation : tests hors ligne du parcours panneau/formulaire, des dates, de la
confidentialité, des limites Discord, des doublons et des reprises sur panne, plus
les tests existants des résolutions. Aucun message de test n’est envoyé au serveur.
