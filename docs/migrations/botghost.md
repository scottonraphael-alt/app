# Préparation de la migration BotGhost

La préparation se fait dans la branche `codex/botghost-migration`, dans une copie
Git séparée du site. Base publiée utilisée : `c89520af4b6fe068f9e33b7be63804cc8fcaf94f`.
L'intégration dans la branche du site est prévue après stabilisation de ses modifications.

## État de l'analyse

La commande `/panel verification` d'OasisBot a été examinée dans le tableau de bord
connecté, par lecture des blocs, connexions, messages et paramètres. Le compte rendu
et les choix validés pour sa migration figurent dans `panel-verification.md`.
La préparation comprend désormais l'archivage Iris et son raccordement futur à la
vue membre 360°. Aucune commande migrée n'est encore branchée sur le bot.

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
- Vue membre 360° : `backend/services/member_360.py`,
  `backend/routers/member_360.py`, `frontend/src/pages/Member360Page.jsx`.
- Envois et rappels de l'agenda : `backend/services/agenda_discord.py` et
  `backend/services/agenda_reminders.py`.

Les modules préparés ne seront pas branchés sur le démarrage du bot pendant cette
phase. La logique sera testée hors ligne avant intégration ; aucun test ne devra
déclencher la commande en production ni modifier sa version BotGhost.
