# Commande privée `/sanction`

La commande est enregistrée sur le serveur `DISCORD_GUILD_ID` par le bot Iris au démarrage du backend. L’enregistrement utilise un upsert de cette seule commande : aucune synchronisation globale ne supprime les autres commandes de l’application. Installer les dépendances mises à jour (`discord.py>=2.7.1,<3`) pour les modals avec upload natif.

## Parcours

1. Le rôle Staff est contrôlé dès le lancement ; un modal demande le **code personnel de 6 caractères**. Après validation, l’exécuteur reçoit un message V2 **éphémère**, avec un sélecteur d’utilisateur.
2. Après vérification des accès, ce premier message est supprimé et remplacé par un résumé privé du casier : compteurs des cinq types, fiches S actives, liste paginée des sanctions, dates de Paris, durées, motifs et indication des fiches S actives ou clôturées.
3. Le choix d’un type ouvre directement son modal : motif (1 000 caractères), explication interne (4 000), un à cinq justificatifs uploadés, durée pour mute/ban et choix de suppression des messages pour un ban. **Tous les champs affichés sont obligatoires**, dans Discord et côté serveur. Choisir « permanent » pour un ban définitif et « Ne supprimer aucun message » pour conserver les messages.
4. Une confirmation privée récapitule les effets avant application. Aucun changement Discord, rôle temporaire ou sanction du casier n’est appliqué lors de la simple préparation.
5. Après confirmation : contrôle des rôles, rôle temporaire, action Discord, retrait du rôle, enregistrement du casier et publication d’un log V2 dans le salon configuré pour ce type.

Le rappel à l’ordre et l’avertissement ajoutent une entrée au casier. Le mute applique un timeout Discord (durée positive, 28 jours maximum). Le kick expulse le membre. Le bannissement est définitif ou temporaire, de 1 minute à 365 jours. Pour le ban, les suppressions proposées sont aucune, dernière heure, 24 heures ou 7 jours. Les suppressions de messages sont irréversibles ; la confirmation les indique.

Les justificatifs acceptent les formats du casier : PNG, JPG/JPEG, GIF, WebP, PDF et TXT. Limite `CASIER_UPLOAD_MAX_BYTES` (10 Mo par défaut), validation du contenu et de l’extension existante du casier. Ils sont d’abord stockés temporairement sous `iris/sanction-commands/`, puis attachés à la sanction et conservés sous `iris/casiers/`. L’explication devient une information complémentaire de la sanction. Un abandon ou une annulation supprime les fichiers de préparation. Les délais et contrôles de confidentialité sont vérifiés côté serveur.

## Codes personnels et page Responsable

La page **Responsable → Codes d’accès modération** (`/responsable/acces-sanctions`) permet de définir, remplacer et révoquer les codes du staff. La liste garde les anciens membres ayant un accès pour permettre sa révocation. Les responsables peuvent générer un code dans le navigateur, l’afficher et le copier dans la fenêtre d’édition ; il disparaît à la fermeture et n’est pas conservé en stockage local. La communication du code au membre reste une action manuelle du responsable.

Le code contient **exactement 6 lettres ASCII ou chiffres**, sans distinction de casse. Il est personnel au compte Discord et ne remplace pas le rôle Staff. Seuls des hachages scrypt salés et liés au serveur et au membre sont stockés ; le code existant ne peut pas être relu. Les réponses de gestion, les logs et les messages Discord ne réaffichent aucun code. Les modals Discord ne disposent pas d’un champ de mot de passe masqué : saisir uniquement le code Iris, jamais son mot de passe Discord.

Cinq tentatives sont autorisées par fenêtre de quinze minutes, avec réservation atomique des tentatives entre processus. Une connexion réussie ouvre une session privée de dix minutes liée au compte, au serveur et à la version du code. Chaque étape sensible, y compris avant le rôle temporaire et juste avant l’action native, revérifie cette session. La rotation ou la révocation du code invalide donc les parcours déjà ouverts. Le travail de finalisation d’une sanction Discord déjà appliquée continue même si l’accès est ensuite révoqué.

La gestion des codes est protégée côté API par le rôle Responsable, utilise une garde de version et ne journalise jamais les données soumises contenant un code. Les dates de gestion sont renvoyées en UTC explicite puis affichées en heure de Paris. Les sessions expirées sont supprimées par l’index TTL MongoDB.

## Rôles et sécurité

Accès : le rôle Staff **`1081957992401997830`** est obligatoire dès le lancement, même pour un admin ou le propriétaire du serveur. Il est revérifié à chaque étape sensible et ne peut pas être remplacé par les permissions natives administrateur. La variable optionnelle `SANCTION_REQUIRED_STAFF_ROLE_ID` permet de déplacer cette configuration. Les permissions natives ordinaires ne sont pas requises sur le rôle staff de base. Chaque interaction reste liée à l’exécuteur et au serveur. Un staff ne peut sanctionner **aucun autre staff**, y compris depuis un compte Responsable : sont protégés les rôles d’équipe configurés, les rôles de modération, les bots et le propriétaire du serveur. Le membre doit être présent ; la commande ne permet pas de bannir arbitrairement un ID externe.

Les rôles et hiérarchies sont relus depuis Discord lors de la sélection, de la soumission, de la confirmation et après l’élévation temporaire. Le bot doit avoir les permissions natives pour les actions, `Gérer les rôles`, un rôle supérieur au rôle temporaire et à la cible, et pouvoir écrire dans les salons de logs.

Valeurs configurées par défaut, correspondant aux IDs demandés :

| Usage | Rôle |
| --- | --- |
| Accès temporaire, toutes les sanctions sauf ban définitif | `1550298577098514482` |
| Accès temporaire, ban définitif | `1550298773635211305` |
| Autorisation obligatoire pour le ban définitif | `1321630097744199721` |

Les variables optionnelles `SANCTION_TEMP_ROLE_ID`, `SANCTION_PERMANENT_BAN_ROLE_ID` et `SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID` permettent de déplacer cette configuration. Aucun nouvel env n’est nécessaire avec ces IDs.

L’obligation de retirer le rôle est enregistrée **avant** son attribution. Le retrait est tenté immédiatement après l’action puis dans un `finally`, même si Discord refuse la sanction. Un échec est persisté et repris par la maintenance du backend ; une nouvelle sanction de cet exécuteur est bloquée jusqu’au nettoyage. Après un arrêt du processus, les élévations non terminées sont retirées à la reprise ; un rôle temporaire n’est donc pas assorti d’une expiration native Discord. Un rôle que l’exécuteur possédait déjà n’est pas retiré. L’élévation automatique réduit la durée d’exposition des permissions ; elle ne remplace pas l’authentification et la protection du compte staff autorisé à appeler `/sanction`.

## Logs

Les destinations sont celles de `DISCORD_MODERATION_CHANNELS` : salons textuels, salons d’annonces ou **IDs des posts d’un forum** (fils de discussion), avec les cinq clés existantes (`avertissement`, `rappel_a_lordre`, `mute`, `kick`, `bannissement`). Un type sans destination configurée ne peut pas être appliqué. Pour un forum, renseigner l’ID de chaque post, pas l’ID du forum parent. Le bot doit avoir `Envoyer des messages dans les fils de discussion`. Un post archivé non verrouillé se réactive à l’envoi ; un post archivé verrouillé est réactivé avant publication si le bot a `Gérer les fils`, sans retirer le verrouillage. La simple préparation ne modifie pas les posts. Les logs V2 séparent l’exécuteur, le motif, la durée, l’explication et les justificatifs en sections distinctes. Motif et explication utilisent chacun leur propre bloc de texte encadré. Les noms des justificatifs et un lien vers le casier Iris complètent le message. Aucune mention ne notifie. Les justificatifs complets restent consultables sur Iris ; ils ne sont pas rediffusés dans Discord.

Une livraison de log interrompue est reprise avec un nonce stable. La sanction Discord n’est jamais réappliquée pour réparer un log. Les messages portent la référence de la commande pour que l’import automatique des salons ne crée pas une deuxième sanction dans le casier. La reprise d’un log après une longue interruption et une réponse perdue peut produire un log en double si la fenêtre d’idempotence Discord est dépassée ; la référence protège l’entrée du casier.

Les étapes, refus, annulations, uploads, élévations, retraits, erreurs et résultats sont aussi journalisés dans **Iris → Responsable → Logs → Casiers**, avec l’exécuteur, la cible, la commande et le rôle concerné.

## Reprise et limites

Une validation répétée ou concurrente ne répète pas une sanction. L’action est persistée avec un identifiant unique ; les verrous par exécuteur et membre empêchent les chevauchements pendant l’application. Un échec de base après une action Discord confirmée reprend uniquement l’écriture du casier et des fichiers. Les mises en sourdine existantes ne sont pas remplacées/raccourcies.

Un résultat Discord incertain n’est pas renvoyé automatiquement. Un ban peut être confirmé par sa raison native unique et finalisé sans le réappliquer ; les autres résultats incertains demandent une vérification humaine des logs et de Discord. Les preuves d’une action incertaine restent conservées pour cette vérification.

La maintenance vérifie les bannissements temporaires toutes les 30 secondes et les lève à échéance, y compris après redémarrage. Avant chaque levée, elle vérifie que la raison native du bannissement est toujours exactement celle de cette commande : un bannissement remplacé par un autre modérateur est conservé. Le backend doit rester actif pour la reprise des logs, les retraits de rôles et les levées de ban.

Validation : tests hors ligne uniquement, avec faux membres, fausses permissions et faux appels Discord. Aucun rôle n’est réellement donné et aucun membre n’est sanctionné lors des tests.
