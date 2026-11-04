# Revue formulaires et tickets — 4 novembre 2026

Branche : `codex/botghost-integration`, worktree `iris-botghost-integration`.

## Périmètre examiné

Formulaires d'admission : soumission et déduplication, prise en charge, décision humaine, tâches à effets Discord, publication du panneau et du formulaire dans un fil, nettoyage, préavis IA indépendant.

Tickets : demandes natives Contact Staff, Soutien, Convocation, Bulle et Vérification ; réservations par membre, autorisations et confidentialité, création de salons, attribution, menus persistants, notifications, import des suivis Helper, synchronisation des messages et des fichiers, suspension/restriction, clôture et archivage. Routes et interfaces de consultation associées.

## Défauts corrigés

1. **Une demande lente bloque les suivantes.** Les passages traitaient les dossiers l'un après l'autre. Les formulaires et les demandes natives utilisent maintenant trois consommateurs au maximum, avec une file bornée. Chaque dossier reste séquentiel ; les erreurs d'un dossier sont isolées et l'arrêt annule aussi les traitements enfants.
2. **La maintenance des anciens salons retarde les nouvelles demandes.** La mise à jour des panneaux publics et des salons existants a sa propre tâche supervisée, toutes les 15 secondes. Le traitement prioritaire des nouvelles demandes conserve son réveil immédiat et son contrôle périodique toutes les 5 secondes. L'import Helper d'un soutien ouvert est repris par la maintenance plutôt que d'allonger la création du salon.
3. **Les changements d'accès attendent la découverte et l'import historique.** Un worker dédié exécute les opérations de permissions après un réveil à la demande, avec un contrôle de secours toutes les 5 secondes. Les baux atomiques restent communs avec le cycle de secours existant. Les reprises manuelles d'ouverture réveillent également le worker immédiatement.
4. **Une panne temporaire avant la création d'un salon fige la demande en “incertain”.** Une erreur réseau ou serveur pendant les contrôles préalables est réessayée après 30 secondes. Dès que le checkpoint de création du salon a été écrit, un résultat ambigu reste soumis à la reprise contrôlée existante : aucune nouvelle création automatique n'est tentée.
5. **Une notification privée échouée n'est jamais réessayée.** Les erreurs temporaires sont maintenant reprises, au plus une tentative par minute. Un refus explicite Discord (403/404) n'est pas bouclé. Un envoi ambigu est réconcilié avec son reçu avant toute répétition.
6. **Une activité reçue pendant une synchronisation peut être effacée.** Chaque événement incrémente la révision d'activité et la révision du dossier. Une activité arrivée pendant le snapshot conserve `sync.due`; une collision à l'enregistrement déclenche une reprise rapide au lieu d'une attente de dix minutes. La comparaison atomique empêche un événement arrivé entre lecture et écriture d'être perdu.
7. **Un panneau ou formulaire supprimé manuellement peut rester bloqué sur le reçu de l'ancien message.** Le remplacement utilise une référence stable dérivée du message supprimé. Les tests vérifient la recréation unique du panneau et du formulaire dans le fil, puis les mises à jour sans doublons.
8. **Coût de balayage inutile.** Les formulaires finaux déjà nettoyés ne sont plus chargés à chaque cycle. Des index couvrent les files de demandes, les contrôles de délai et les opérations de tickets en attente.

## Validation

- 427 tests backend passent : tickets, formulaires, intégration BotGhost, permissions, confidentialité, pièces jointes, archives, clôtures, rappels, routage, panneaux, gouvernance et nouveaux tests de régression.
- 28 tests des pages Vérifications, Dossiers et Espace ticket passent.
- Les nouveaux tests reproduisent : panne préalable, création ambiguë, requête prioritaire, notification temporairement impossible, activité concurrente pendant et à la fin d'un snapshot, panneau/formulaire supprimé, réveil immédiat des opérations, limitation à trois traitements et annulation des sous-tâches.
- Les tests UI signalent un avertissement existant sur un `span` injecté dans un `option` par l'instrumentation de développement. Aucune modification du balisage de l'espace ticket n'est incluse.

## Limites et suivi après déploiement

Validation locale avec Discord et MongoDB simulés. Aucun salon réel n'a été ouvert ou supprimé, aucune sanction n'a été exécutée. Aucun gain chiffré en production n'est revendiqué : les limites Discord, le nombre de pièces jointes et les délais réseau doivent être mesurés après déploiement. Le parallélisme est plafonné à trois par file et les protections contre les duplications et suppressions sans archive complète restent en place.

La compilation générale du frontend était déjà bloquée par l'absence locale de `echarts/core`, sans rapport avec ces changements backend. Les pages du périmètre sont validées par leurs tests existants.

Contrôler les tâches `native_ticket_delivery`, `ticket_maintenance`, `ticket_operations`, `ticket_closures` et `verification_delivery`. Tester une soumission réelle et sa livraison, une prise en charge de soutien, une notification, puis une clôture avec pièce jointe. Les états “incertain” déjà présents ne sont pas relancés en masse : ils conservent le parcours de reprise explicite dans Iris.
