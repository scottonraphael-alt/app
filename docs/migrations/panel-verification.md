# Vérifications OasisBot : fonctionnement retenu et intégration future

Préparation validée avec l'utilisateur le 28 octobre 2026. Branche de travail :
`codex/botghost-migration`. La dernière branche publiée a été récupérée et vérifiée :
`origin/security/audit-fixes` pointe sur `c89520af4b6fe068f9e33b7be63804cc8fcaf94f`.
Cette fiche prépare le développement et l'intégration ultérieure, sans activer une
nouvelle commande, importer les archives ou modifier la branche du site.

## Fonctionnement observé

La commande `/panel verification` est réservée aux rôles Responsable et Administrateur.
Elle actualise le panneau existant dans le salon `1081957992418783296`, message
`1453063484542685369`. Le bouton public « Remplir le Formulaire » ouvre `verifmodal` :

| Champ | Règle actuelle |
| --- | --- |
| Nom (`name`) | Obligatoire, maximum 40 caractères |
| Tranche d'âge (`age`) | Obligatoire : 13–15, 16–17, 18–25, 26 ans et plus |
| Motif de venue (`raison`) | Obligatoire, 50 à 250 caractères |
| Avis sur la psychiatrie (`avis`) | Obligatoire, 120 à 1 000 caractères |
| Règlement (`regl`) | Acceptation obligatoire, non cochée par défaut |

Chaque envoi incrémente le compteur personnel, confirme l'envoi au membre et alimente
un fil privé de vérification. Une nouvelle tentative réutilise le fil existant.
Le message de suivi est publié dans `1425589415165558825` avec prise en charge.
Le menu permet validation, refus, ticket, approfondissement ou clôture.

La validation attribue Membre et le rôle d'âge, puis retire Non validé. Après clôture,
un message d'accueil est envoyé dans `1081957994125860905` : le même texte accompagne
**quatre GIF différents**, sélectionnés avec une probabilité de 25 % chacun.

Le refus demande un motif, une case bannissement et une case moins de 13 ans.
Le bannissement coché est prioritaire ; sinon le membre est expulsé. Les deux parcours
d'expulsion ont des logs distincts. Les notifications en MP précèdent la sanction
effective, laquelle arrive actuellement après archivage. Les logs utilisent les
destinations de modération déjà connues d'Iris.

Le ticket crée un salon `🎫・｜vérif-{formusername}` dans Contact Staff, avec accès du
membre, et initialise `ticketv3_userid`, `ticketv3_msg`, `ticketv3_auth` pour le salon.
La gestion générale de ces tickets peut dépendre d'autres commandes, non étudiées ici.

La clôture recopie les fiches de formulaire dans un fil privé d'archives sous
`1226848987559100458`, puis supprime le fil actif et son suivi et réinitialise les
références du dossier ouvert. Ce mécanisme n'établit pas une archive complète de
toutes les conversations du fil.

## Choix explicitement retenus

- Tous les membres ayant le rôle Staff peuvent prendre en charge et décider.
- « Clore / sans réponse » archive, sans expulsion ; le membre reste non validé.
- Un approfondissement demande de refaire **tout le formulaire**.
- Discord reste une interface complète de traitement, avec arrivée du formulaire,
  notification, prise en charge et décisions, sans passage obligatoire par le site.
- Iris conserve le dossier, toutes les tentatives et les décisions et propose une
  interface plus détaillée. Les actions des deux interfaces utilisent le même état.
- Le préavis IA est court sur Discord et détaillé sur Iris. Il reste indicatif :
  aucune décision d'admission, expulsion ou bannissement automatique par l'IA.
- Le préavis arrive après le formulaire et ne bloque ni sa notification ni son traitement.
- Les anciens fils du salon d'archives sont une source d'import, à lire sans les modifier.

## Corrections de conception à prévoir

- Annonce de clôture à 10 secondes et attente à 5 secondes : harmoniser les deux.
- Deux cases d'approfondissement cochées : envoyer une demande couvrant les deux sujets.
- Adresser l'approfondissement au membre ; la configuration examinée semble répondre
  seulement au staff qui choisit le menu.
- Remplacer la référence de bannissement `banverif.motif` par le motif du refus.
- Vérifier le rôle Staff sur les interactions ; les composants examinés sont sur Anyone.
- Prévoir une prise en charge atomique et empêcher les décisions concurrentes.
- Isoler les échecs de MP, de log, d'archivage et d'action Discord pour ne pas annoncer
  un succès sans confirmation ni laisser une panne intermédiaire bloquer tout le dossier.
- Préserver l'identité du demandeur et celle du décideur dans chaque action.

## Intégration à la vue membre 360°

Points vérifiés dans le code actuel :

- Agrégation : `backend/services/member_360.py::build_member_360`.
- Endpoint : `GET /api/members/{discord_id}/360` dans `backend/routers/member_360.py`.
- Affichage : `frontend/src/pages/Member360Page.jsx` et `frontend/src/Member360.css`.
- La frise est paginée, du plus récent au plus ancien. Elle filtre les sources selon
  les droits avant toute lecture en base ; ses consultations sont journalisées.
- La vue est une synthèse : elle ne renvoie notamment pas le contenu des tickets.
- Côté interface, la route 360° est actuellement réservée à Opérateur/Responsable
  (`canSeeOperateur`). Le module de vérification autonome sera accessible au Staff ;
  son ajout ne doit pas ouvrir automatiquement toute la vue 360° à d'autres rôles.

Les formulaires doivent devenir une catégorie **Vérification / admission** avec des
événements neutres : formulaire envoyé, pris en charge, approfondissement demandé,
nouvelle tentative, validation, refus, ticket ouvert et clôture sans réponse.
Les actions de modération effectives conservent leurs événements de sanction propres.

Un encart « Arrivée et vérification » donne accès au premier formulaire connu, à la
date de validation quand elle existe, au nombre de tentatives, au statut actuel et
au dossier détaillé. Les événements sont également ajoutés à leur date dans la frise
existante. Ne pas assimiler la première date de formulaire connue à une date d'arrivée
Discord ni inventer une date lorsque l'archive n'en donne pas.

La vue 360° expose seulement les métadonnées utiles et un lien vers le dossier ; les
réponses complètes et les préavis détaillés sont consultés dans le module de vérification.
L'accès aux formulaires est réservé au Staff, sans élargir les accès existants aux
tickets ou aux casiers. Un utilisateur sans accès aux formulaires ne doit recevoir
ni leurs réponses, ni leurs compteurs, ni une indication de leur existence. Cette
catégorie doit être incluse dans l'audit des consultations autorisées.

## Historique, import et exemples pour l'IA

Conserver un dossier par membre et serveur, des tentatives distinctes et des événements
datés avec acteur, origine Discord/Iris et référence de message/fil lorsque disponible.
Prévoir des références de livraison pour maintenir les messages Discord liés au dossier.
Les traitements d'une même interaction doivent être idempotents.

L'import historique doit identifier les auteurs des archives, les membres, les fiches
et leurs décisions explicites. Il doit couvrir les fils archivés et actifs accessibles,
éviter les doublons et conserver les liens sources. Un dossier incomplet ou ambigu
reste signalé comme tel. Une clôture sans réponse n'est jamais étiquetée refus.

L'amélioration du préavis repose d'abord sur des exemples de référence validés par un
humain, avec motifs et règles d'admission explicites. L'ensemble des archives ne doit
pas être transformé automatiquement en exemples d'acceptation ou de refus. Préserver
les décisions contradictoires ou corrigées dans l'historique et exclure les références
invalidées. Limiter les données personnelles transmises à celles nécessaires à l'analyse.

## État de réalisation

L'analyse et les choix ci-dessus sont documentés. Aucun code de migration fonctionnel
n'est encore écrit, aucun import exécuté et aucun raccordement au démarrage du bot ni
à l'API de production n'a été ajouté.
