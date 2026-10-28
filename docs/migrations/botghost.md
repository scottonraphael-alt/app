# Préparation de la migration BotGhost

La préparation se fait dans la branche `codex/botghost-migration`, dans une copie
Git séparée du site. Base publiée utilisée : `c89520af4b6fe068f9e33b7be63804cc8fcaf94f`.
L'intégration dans la branche du site est prévue après stabilisation de ses modifications.

## État de l'analyse

L'accès au tableau de bord demande une connexion utilisateur. Aucune commande privée
BotGhost n'a encore été examinée et aucun comportement ne doit être déduit des
exemples publics du site. Le bot et la première commande restent à identifier.

Pour chaque commande accessible, relever ses options, conditions, branches,
variables persistantes, messages, boutons, formulaires, délais et effets Discord.
Le code pourra simplifier les blocs répétés en conservant les comportements observés.
Les choix d'intégration encore inconnus seront explicités dans la fiche de la commande.

## Points d'intégration repérés dans Iris

- Client Discord partagé : `backend/services/moderation_bot.py`.
- Arbre de commandes existant et enregistrement individuel :
  `backend/services/sanction_command.py::install`. Une intégration ultérieure doit
  réutiliser cet arbre et préserver les autres commandes du bot.
- Exemples de parcours Components V2 privés et de formulaires :
  `backend/services/wellbeing_commands.py` et `backend/services/sanction_command.py`.
- Historique Iris : `backend/services/audit_service.py` ; audit des tickets :
  `backend/services/ticket_audit.py`.
- Import des dossiers Discord : `backend/services/ticket_import.py`.
- Envois et rappels de l'agenda : `backend/services/agenda_discord.py` et
  `backend/services/agenda_reminders.py`.

Les modules préparés ne seront pas branchés sur le démarrage du bot pendant cette
phase. La logique sera testée hors ligne avant intégration ; aucun test ne devra
déclencher la commande en production ni modifier sa version BotGhost.
