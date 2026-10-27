# Composeur d’annonces Discord V2

Accès : **NewDashboard → Responsable → Composer une annonce Discord** (`/responsable/annonces`). Les routes et les fichiers du module sont réservés aux responsables, y compris côté API. La page reprend la charte du casier sans barre latérale globale.

## Composition

- Panneaux indépendants, encadrés ou libres, couleur d’accent et spoiler.
- Texte Markdown et barre d’outils ; sections avec un à trois textes et une vignette ou un bouton de lien ; galeries d’images/vidéos avec descriptions alternatives ; séparateurs ; lignes de boutons de lien ; fichiers joints.
- Réorganisation, duplication et suppression des blocs ; édition d’un bloc à la fois avec un sommaire défilant.
- Aperçu indicatif sombre/clair et largeur mobile. Discord reste la référence pour le rendu final, en particulier les syntaxes Markdown imbriquées et les médias externes.
- Téléversement direct depuis les blocs galerie, vignette et fichier joint : stockage sur Iris, ajout à la bibliothèque et sélection automatique. Les liens externes restent disponibles dans un volet secondaire. Un échec ne remplace pas le média précédent.
- Brouillons et modèles partagés, recherche, pagination, trames de départ, duplication, récupération locale des modifications non enregistrées et protection des versions concurrentes.
- Export/import du document Iris ; export du payload Discord pour inspection. L’import passe par le schéma serveur et ne permet pas d’envoyer un payload arbitraire.

## Distribution et historique

Choisir un salon textuel ou d’annonces du serveur configuré. Les mentions sont **désactivées par défaut** ; une mention ne peut notifier que si elle figure dans le texte et dans les autorisations de distribution. `@everyone`/`@here` demandent une option explicite. L’envoi discret utilise le drapeau Discord de suppression des notifications push.

La publication présente une confirmation avec le salon, la version et les mentions. Les textes sont compilés par le serveur en composants V2 avec `IS_COMPONENTS_V2` ; aucun champ `content` ou `embeds` n’est envoyé.

La programmation utilise **Europe/Paris** et stocke une date UTC. Les heures inexistantes ou ambiguës du changement d’heure sont refusées. Le planificateur du backend vérifie les publications toutes les quinze secondes. Il doit rester démarré ; après un arrêt, il reprend les publications arrivées à échéance. La version programmée est figée, même si le brouillon change ensuite. Une publication encore programmée peut être annulée.

L’historique conserve les versions, le statut, l’auteur, le salon et le lien Discord. Il permet de réutiliser une version et de modifier un message publié depuis le même brouillon dans le même salon. Une modification remplace les composants et les pièces jointes actives et ne réautorise aucun ping. Les messages envoyés par d’autres outils ne sont pas modifiables ici.

Chaque demande a une clé d’idempotence et un nonce Discord. Une programmation est réservée atomiquement avant son exécution. Une erreur de transport, une réponse serveur Discord incertaine ou un processus interrompu pendant l’envoi donne un statut **à vérifier** : aucun renvoi automatique, pour éviter les doublons. Vérifier le salon avant un nouvel envoi. Le rôle Responsable de l’auteur est revérifié au moment de l’exécution avec le mécanisme d’autorisation existant.

## Fichiers et limites

Bibliothèque privée sur le stockage persistant `IRIS_STORAGE_ROOT`, sous `iris/announcements/`. Les identifiants des pièces jointes sont résolus côté serveur ; aucun chemin de stockage fourni par le navigateur n’est accepté. HTML, SVG, XML et JavaScript sont servis comme téléchargements binaires.

Limites du composeur : 40 composants au total, 4 000 unités UTF-16 de texte cumulé, 10 fichiers et 10 Mo cumulés par annonce. Les sections acceptent trois textes maximum, les galeries dix médias et les lignes cinq boutons. Les URL doivent être HTTP(S) publiques, HTTPS pour les médias. Le serveur ne télécharge pas les médias externes ; le navigateur et Discord les chargent. Les interactions de bot, formulaires et sélecteurs ne sont pas inclus : les boutons du composeur sont des liens.

Les fichiers restent conservés après suppression d’un brouillon pour permettre la consultation et la réutilisation de l’historique. Leur sauvegarde suit celle du stockage persistant existant. Aucune nouvelle variable d’environnement n’est nécessaire : le module réutilise le token du bot et le serveur Discord configurés. Le bot doit avoir les droits de voir le salon, publier et joindre les fichiers.

## Journalisation et validation

Les créations, sauvegardes avec versions avant/après, suppressions, vérifications, fichiers, demandes de publication, résultats, annulations et consultations sont journalisés dans les logs Iris, catégorie **Annonces**. Les interactions d’interface sont identifiées comme déclarées par le client ; elles complètent les événements métier produits par le serveur. Les modifications de champs sont enregistrées avec leur longueur ou la sélection, sans recopier chaque frappe. Les contenus enregistrés sont présents dans les versions du brouillon et dans les détails de sauvegarde.

Tests hors ligne : schémas et limites, contrôle des droits, liens dangereux, brouillons, conflits de versions, mentions, fichiers, transport multipart simulé, idempotence, modification sans ping, programmation et transitions d’heure, annulation, rôle révoqué, envoi incertain et audit. Les tests d’interface couvrent la composition et la confirmation explicite. Aucun message Discord réel n’est envoyé pendant ces tests et aucune capture de rendu n’est réalisée.

Références : [composants Discord](https://docs.discord.com/developers/components/reference), [utilisation des composants V2](https://docs.discord.com/developers/components/using-message-components), [API des messages](https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx).
