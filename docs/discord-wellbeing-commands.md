# Commandes privées d’information et d’aide

Les commandes `/infos-troubles` et `/crise` sont accessibles aux membres du serveur `DISCORD_GUILD_ID`. Elles partagent le client et l’enregistrement de `/sanction`. Chaque commande est enregistrée individuellement : aucune synchronisation globale ne supprime les autres commandes du bot.

## Parcours

- `/infos-troubles` affiche le catalogue et un bouton ouvrant un formulaire obligatoire. Après recherche Anthropic, trois messages Components V2 privés présentent le trouble, ses symptômes et les prises en charge. Les textes sont informatifs et renvoient aux sources institutionnelles ; aucun diagnostic personnel ni dosage médicamenteux n’est demandé.
- `/crise` affiche un exercice de respiration et le GIF embarqué dans `backend/assets/crisis-breathing.gif`, envoyé comme pièce jointe Discord. Il ne dépend plus de l’expiration du lien fourni initialement.
- Son formulaire demande **ville et pays**, partout dans le monde. La région peut être précisée dans le champ ville pour les homonymes. La recherche vise jusqu’à cinq structures publiques ou associatives reconnues, avec nom, adresse, téléphone et lien vers la source. Elle ne garantit ni une liste exhaustive ni une distance exacte. Les adresses et téléphones doivent apparaître littéralement dans les citations renvoyées par la recherche web ; les résultats incomplets ou sans citation sont écartés.
- Le **3114 est toujours affiché pour `/crise`**, explicitement comme ressource française, y compris si la recherche échoue ou ne donne aucun résultat. Il n’est pas présenté comme numéro international.

Les vues sont éphémères et leurs composants sont réservés à leur auteur et au serveur configuré. Les formulaires expirent après dix minutes.

## Configuration et exploitation

Clé existante : `ANTHROPIC_API_KEY`. `WELLBEING_AI_MODEL` peut sélectionner un modèle Anthropic prenant en charge la recherche web ; à défaut, `TICKET_SUMMARY_MODEL` est réutilisé. La recherche web Anthropic doit être disponible pour le compte et le modèle. Elle est facturée par Anthropic en plus des tokens. Voir la [documentation de la recherche web](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool).

`WELLBEING_LOG_CHANNEL_ID` vaut par défaut `1523966083344629810`. Ce doit être le **post du forum**, sur le serveur configuré, accessible au bot ; les permissions sur les fils sont contrôlées. Les fils archivés/verrouillés réutilisent la gestion déjà en place pour les logs de modération.

Chaque saisie est journalisée avant l’appel IA avec l’auteur, le contenu et la référence de l’interaction. Aucune mention n’est déclenchée dans ces logs. Si la journalisation échoue, aucune requête IA n’est envoyée. L’utilisateur est informé de cette journalisation et de la transmission à Anthropic avant de soumettre le formulaire. Le post doit être réservé aux personnes habilitées à lire ces informations sensibles.

Le registre technique MongoDB conserve les demandes pendant 30 jours via un index TTL (la suppression effective dépend du passage de MongoDB). Cela **ne supprime pas les messages du forum**, dont la conservation reste indépendante. Les identifiants d’interaction empêchent les doubles traitements. Les recherches sont limitées à dix par membre et par heure, espacées d’au moins trente secondes ; trois recherches simultanées maximum dans le processus du bot. L’exercice reste disponible indépendamment de ces limites et de la configuration IA.

Déployer les fichiers backend, y compris le dossier `assets`, puis redémarrer le backend/bot. Les nouvelles commandes sont enregistrées au démarrage. Aucun changement frontend n’est nécessaire.

## Vérification

Tests hors ligne dans `backend/tests/test_wellbeing_commands.py` : confidentialité, restrictions des interactions, formulaires, fichier GIF, envoi des trois réponses, journalisation avant IA, limites persistantes, recherche mondiale et rejet des coordonnées absentes des citations. Le test d’enregistrement `/sanction` vérifie également l’ajout des deux commandes sans remplacement global.

Les tests n’appellent ni Discord ni Anthropic et ne vérifient donc pas les permissions réelles du post ni l’activation de la recherche web sur le compte de production.
