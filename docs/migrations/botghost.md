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

## Système de tickets

L'événement central `When a channel is created` a fait l'objet d'une première
cartographie en lecture seule (118 blocs / 134 liaisons rendus). Voir
[ticket-system.md](ticket-system.md) pour les cinq familles, les droits, les archives,
les limites constatées et les décisions utilisateur. Les commandes productrices
restent à examiner avant d'écrire le nouveau moteur de tickets.


Le producteur convocation/bulle `/panel moderation` est maintenant décrit dans
[panel-moderation.md](panel-moderation.md), avec ses contrôles, sa consultation du
casier, sa notification distincte de la création et les choix utilisateur à appliquer.

Le producteur public `/panel contact-staff` est décrit dans
[panel-contact-staff.md](panel-contact-staff.md). Le fonctionnement métier du
Purgatoire, expliqué par l'utilisateur mais encore inachevé dans BotGhost, est
consigné séparément dans [purgatoire.md](purgatoire.md).
