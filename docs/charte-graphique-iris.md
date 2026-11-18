# Charte graphique et UX d’Iris

Référence pour toute création ou mise à jour de l’interface Iris. Version du 18 novembre 2026, fondée sur le dashboard et l’harmonisation des pages métier validés. Toute évolution visuelle doit prolonger cette base et mettre ce document à jour si une règle commune change.

## 1. Intention

Iris est un espace de travail accueillant, calme et lisible. La hiérarchie vient de la typographie, de l’espace et de surfaces simples. Les couleurs apportent des repères ponctuels ; elles ne doivent pas recouvrir toute l’interface.

- Conserver un fond neutre, des cartes sobres et des contrastes lisibles.
- Utiliser les cinq accents : lavande, sauge, framboise, pêche et bleu.
- Éviter une dominante sauge systématique, les grands dégradés décoratifs, les effets lumineux et les ombres lourdes.
- Garder la navigation supérieure, les favoris et la recherche. Ne pas réintroduire une barre latérale sans nouvelle décision produit.
- Conserver les fonctions, les données réelles et les accès par rôle dans toute refonte.

Cette charte couvre les pages Iris, la connexion et leurs fenêtres. OasisGame et les autres activités ont leur propre identité. Les aperçus de messages Discord conservent le rendu Discord.

## 2. Sources dans le code

| Source | Responsabilité |
| --- | --- |
| [theme.css](../frontend/src/theme.css) | Tokens globaux et thème sombre |
| [IrisRefresh.css](../frontend/src/IrisRefresh.css) | Palette validée, dashboard, navigation et motion commune |
| [IrisPages.css](../frontend/src/IrisPages.css) | Harmonisation des pages métier et fenêtres |
| [IrisBrand.jsx](../frontend/src/components/brand/IrisBrand.jsx) et [IrisBrand.css](../frontend/src/components/brand/IrisBrand.css) | Logo floral et mot-symbole |
| [AppShell.jsx](../frontend/src/components/AppShell.jsx) | Structure commune et périmètre de l’interface |
| [useMotionPreference.js](../frontend/src/hooks/useMotionPreference.js) | Préférence d’animation et synchronisation |
| [Motion.jsx](../frontend/src/components/motion/Motion.jsx) | Primitives d’animation |

Les valeurs ci-dessous décrivent le thème clair courant. Pour implémenter une page, utiliser les variables CSS : ne pas recopier les valeurs hexadécimales dans chaque composant. Les sources CSS définissent les variantes sombres.

## 3. Palette

### Surfaces et texte

| Usage | Token | Valeur claire |
| --- | --- | --- |
| Fond de page | `--iris-bg` | `#faf9f7` |
| Carte et fenêtre | `--iris-surface` | `#ffffff` |
| Surface secondaire | `--iris-surface-2` | `#f7f5f8` |
| Texte principal | `--iris-text` | `#302b35` |
| Texte secondaire | `--iris-text-muted` | `#706979` |
| Texte discret | `--iris-text-soft` | `#82798b` |
| Bordure | `--iris-border` | `#e8e4eb` |
| Bordure renforcée | `--iris-border-strong` | `#cec2d8` |

### Accents

| Accent | Token | Encre claire | Fond doux |
| --- | --- | --- | --- |
| Lavande | `--iris-violet` | `#795c96` | `--iris-violet-soft` : `#eee7f5` |
| Sauge | `--iris-sage` | `#55715b` | `--iris-sage-soft` : `#eaf0e9` |
| Framboise | `--iris-raspberry` | `#9e4e71` | `--iris-raspberry-soft` : `#f7e9ef` |
| Pêche | `--iris-clay` | `#946a53` | `--iris-clay-soft` : `#f7eae1` |
| Bleu | `--iris-info` | `#577b9c` | `--iris-info-soft` : `#e9f0f8` |

L’accent général utilise aussi `--iris-accent` (`#745a89`), `--iris-accent-strong` (`#695079`) et `--iris-accent-soft` (`#efe7f5`). Garder ces rôles distincts des couleurs d’alerte.

Employer les fonds doux sur une icône, une pastille, un onglet sélectionné ou un petit regroupement. La majorité des grandes cartes doit rester neutre. Ne pas attribuer une couleur différente à chaque élément sans signification.

Les pages métier disposent de `--ui-accent` et `--ui-soft` : lavande par défaut, bleu pour l’agenda et les statistiques, sauge pour l’accompagnement et l’équipe, pêche pour les ressources et tâches, framboise pour la modération. Garder les correspondances existantes de chaque module.

### États sémantiques et thème sombre

- Erreur, danger et suppression : `--iris-danger` et `--iris-danger-soft`.
- Attention : `--iris-warn` et `--iris-warn-soft`.
- Ne jamais remplacer une alerte par un accent décoratif. Une framboise de catégorie ne signifie pas « erreur ».
- Les catégories du calendrier gardent leurs repères propres.
- Accompagner la couleur d’un texte, d’une icône ou d’un état accessible.
- Le thème sombre est activé par `html[data-theme="dark"]`. Réutiliser ses tokens plutôt que des fonds blancs ou noirs fixes.
- Sur les actions à fond pastel en thème sombre, utiliser `--iris-on-accent` pour une encre sombre. Vérifier le contraste des textes, icônes, survols et sélections.

## 4. Logo, typographie et rédaction

Réutiliser `IrisBrand`, avec la fleur et le mot-symbole `iris.`. Le point lavande et l’espacement serré font partie de l’identité. Dans la navigation, le logo renvoie à l’accueil.

| Élément | Règle |
| --- | --- |
| Mot-symbole | Manrope, graisse 600, 36 px sur ordinateur, 30 px sur petit écran ; approche `-.075em` |
| Titre de page | Manrope, graisse 500, 30 à 44 px, interligne 1.2, approche `-.04em` |
| Titre de carte | Manrope, généralement 18 à 23 px, graisse 500, approche légère `-.025em` |
| Texte courant | IBM Plex Sans, généralement 13 à 14 px ; interligne confortable de 1.6 à 1.8 |
| Surtitre | Environ 10 px, graisse 500, espacement `.12em`, texte secondaire |
| Compteurs et heures | Chiffres tabulaires quand leur comparaison le demande |

Écrire des titres concrets, des libellés courts et des actions verbales : « Enregistrer », « Nouveau projet », « Réessayer ». Les instructions et erreurs doivent expliquer la prochaine action utile. Réserver les capitales aux petits surtitres, pas aux paragraphes.

## 5. Mise en page et cartes

- Largeur de contenu : dashboard jusqu’à 1320 px ; pages métier jusqu’à 1440 px, centrées. Les espaces de travail spécialisés gardent leur géométrie.
- Espacement des pages métier : 40 px en haut, 20 à 48 px sur les côtés selon la largeur, 60 px en bas. Sur mobile, base de 28 / 18 / 44 px.
- Construire le rythme sur des multiples proches de 4 px ; privilégier des espacements de 12, 16, 20, 24 et 32 px selon la densité.
- Cartes principales : fond `--iris-surface`, bordure fine `--iris-border`, rayon de 14 px, généralement sans ombre. Les raccourcis compacts peuvent utiliser 8 à 10 px.
- Hiérarchiser : titre et description, actions, puis contenu. L’action principale doit se distinguer des outils secondaires.
- Une carte statique ne doit pas se soulever au survol. Réserver cet effet aux cartes réellement navigables.
- Les blocs déplaçables du dashboard restent personnalisables via leur mode édition et leur poignée. Conserver les commandes clavier, l’enregistrement explicite et les retours d’état.
- Ne pas changer les positions des éléments déplaçables, du calendrier ou des graphiques avec une animation de décoration.

## 6. Composants et états

### Boutons, onglets et champs

- Boutons et onglets : rayons proches de 8 px. Champs : 9 px.
- Actions principales : accent du contexte ; secondaires : surface neutre et bordure discrète ; destructives : danger explicite.
- Préserver les états normal, survol, actif, sélectionné, chargement, désactivé et erreur.
- Base des boutons de page : hauteur minimale de 40 px, 42 px sur mobile. Prévoir des cibles tactiles confortables, idéalement 44 px, pour les nouvelles commandes.
- Un bouton désactivé reste reconnaissable et ne prend pas d’effet de survol ou de déplacement.
- Les champs gardent leur libellé. Le placeholder ne remplace pas le libellé.
- Focus clavier visible : contour lavande de 3 px, décalé de 2 à 4 px. Les erreurs gardent le repère danger.
- Sur mobile, les champs de saisie utilisent 16 px pour éviter le zoom automatique et préserver la lisibilité.

### Tableaux, listes, fenêtres et éditeurs

- Tableaux : en-tête discret, séparateurs fins, survol léger de ligne. Garder les intitulés de colonnes et le défilement horizontal local si nécessaire.
- Listes : conserver une hiérarchie claire entre titre, détails, date et actions. Distinguer les éléments non lus et urgents sans dépendre de la couleur seule.
- Fenêtres : surface neutre, rayon de 16 px et ombre commune `--iris-shadow`. Les tiroirs latéraux gardent leur bord ancré ; ils peuvent occuper tout l’écran sur mobile.
- Préserver le piège de focus, la fermeture clavier, le retour du focus au déclencheur et les protections contre la perte d’une saisie.
- Ne pas écraser les couleurs du contenu riche, les graphiques ni les aperçus Discord avec une règle globale de texte ou de fond.
- Prévoir les états chargement, vide et erreur avec une explication utile et une action de reprise quand elle existe.

## 7. Motion design

Chaque animation doit aider à percevoir une arrivée, une action ou un changement d’état. Aucun contenu ne doit attendre une animation pour être accessible.

| Interaction | Référence |
| --- | --- |
| Arrivée de page | 220 ms, opacité et translation verticale de 6 px vers 0 |
| Survol de contrôle ou onglet | 140 à 180 ms, couleur de fond, bordure ou texte |
| Carte navigable | Environ 180 ms, translation maximale de 2 px vers le haut et ombre légère |
| Pression | Effet bref et discret, sans déplacement de la mise en page |
| Courbe commune | `--iris-ease` : `cubic-bezier(.22,1,.36,1)` |

Éviter les rebonds appuyés, les boucles décoratives, les délais cumulés et les animations de hauteur qui déplacent les commandes pendant une saisie. Réutiliser les primitives de motion existantes ; ne pas appliquer de `transform` générique à un élément déjà animé ou déplaçable.

Respecter à la fois `prefers-reduced-motion: reduce` et `html[data-motion="reduced"]`. La préférence système de réduction reste prioritaire. Le choix manuel est conservé dans `iris.motion`. Utiliser le hook et les primitives existants pour les effets JavaScript ; prévoir aussi la réduction des transitions CSS, y compris dans les fenêtres rendues sur `body`.

## 8. Responsive et accessibilité

- Vérifier au minimum une largeur mobile de 390 px et une largeur ordinateur de 1280 px, ainsi que les points de rupture propres à la page.
- Replier les actions et les grilles ; ne pas réduire tout le contenu pour le faire rentrer.
- Éviter le débordement horizontal de page. Un tableau ou un outil spécialisé peut défiler dans son propre conteneur.
- Garder les textes essentiels visibles et les fenêtres accessibles sur toute leur hauteur.
- Utiliser des éléments natifs, des libellés accessibles pour les icônes seules et un ordre de tabulation logique.
- Viser les contrastes WCAG AA : 4.5:1 pour le texte courant, 3:1 pour le grand texte et les repères de contrôle concernés.
- Vérifier les thèmes clair et sombre, la navigation clavier, les états d’erreur et les animations réduites.

## 9. Règles d’intégration et maintenance

1. Réutiliser les tokens et composants existants avant d’ajouter une nouvelle variante.
2. Garder les styles communs dans les feuilles communes et la géométrie spécifique dans le module concerné.
3. Limiter les règles au périmètre Iris : `.app-shell.iris-ui` et ses pages. Les portails s’appuient sur `body.iris-ux-active` pendant le montage d’`AppShell`.
4. Les anciennes variables de famille (`--cz-*`, `--ag-*`, `--pj-*`, etc.) sont reliées à la palette sur la racine de la page ou de la fenêtre. Vérifier le résultat après un chargement différé de route.
5. Utiliser des classes explicites. Éviter les sélecteurs globaux par fragment de nom, les couleurs fixes recopiées et les `!important` ajoutés pour contourner la cascade.
6. Ne pas fusionner une refonte graphique avec une modification implicite des permissions, du parcours OAuth, des données ou du comportement d’enregistrement.
7. Garder les données fictives et les outils de preview hors du code de production.
8. Si une décision visuelle commune évolue, modifier cette charte et les tokens ensemble. Une exception locale doit être documentée avec sa raison.

## 10. Vérification avant livraison

- [ ] La page utilise la palette, le logo et la hiérarchie typographique communs.
- [ ] Les cartes restent majoritairement neutres et les couleurs d’état gardent leur sens.
- [ ] Les contrôles fonctionnent avec leurs états de chargement, d’erreur et de désactivation.
- [ ] Les vues mobile et ordinateur, les thèmes clair et sombre et les fenêtres ont été inspectés.
- [ ] Le clavier, les focus visibles et le mode d’animations réduites sont utilisables.
- [ ] La personnalisation du dashboard et les gestes métier restent fonctionnels si concernés.
- [ ] Les tests pertinents et la compilation passent ; les limites de vérification sont signalées.
- [ ] Un aperçu des composants réels et des captures permettent de relire le rendu avant publication.

Voir aussi [le compte rendu de l’harmonisation UX](iris-ux-refresh.md) et [les comportements du dashboard, des notifications et des brouillons](dashboard-widgets-notifications-drafts.md).

## 11. Raffinements de lecture et de navigation

Les composants de [Refinements.css](../frontend/src/components/ux/Refinements.css), [LoadingSkeleton](../frontend/src/components/ux/LoadingSkeleton.jsx) et [PageMemory](../frontend/src/components/ux/PageMemory.jsx) prolongent ces règles :

- Aligner les en-têtes sur un même ordre de lecture. Les actions secondaires restent visibles et se replient sur plusieurs lignes ; ne pas masquer une commande utile pour simplifier artificiellement la page.
- Garder les données déjà affichées pendant une actualisation lorsque c’est possible. Utiliser les silhouettes pour le chargement initial, avec un statut accessible et sans pulsation en mode d’animations réduites.
- Au retour navigateur, restaurer la position quand le contenu a chargé. L’intervention de l’utilisateur au clavier, à la molette ou au toucher interrompt la restauration. Le lien retrouvé peut recevoir un repère bref et le focus sans défilement supplémentaire.
- Conserver les filtres des listes prises en charge en mémoire dans la session d’interface : projets, ressources, notifications, familles de dossiers et archives. Conserver aussi la pagination des projets et dossiers. Cette mémoire est réinitialisée au changement de compte et au démontage de l’interface ; aucun contenu de dossier n’est enregistré dans le stockage du navigateur par ce mécanisme.
- Pour les formulaires longs, regrouper les champs avec des titres de section et garder les actions accessibles pendant le défilement. Le composant `Field` des projets relie les indications et erreurs au champ avec `aria-describedby` et garde son libellé accessible indépendant du texte d’aide.
- Choisir une taille de fenêtre explicite : petite pour une confirmation, moyenne pour un réglage, grande pour une rédaction ou un formulaire long. Les grandes fenêtres de projet occupent le mobile en plein écran ; leur en-tête et leurs actions restent accessibles.
- Réutiliser `MotionNav` pour les indicateurs d’onglet qui glissent. Ne pas doubler le fond actif avec un second marqueur. Les pressions de boutons et les confirmations doivent rester brèves, avec les couleurs du thème.

## 12. Confort de lecture, actions et saisie

[Comfort.css](../frontend/src/components/ux/Comfort.css) précise les règles suivantes :

- Dans les listes, aligner les dates et compteurs avec des chiffres tabulaires, réserver une place cohérente aux statuts et garder des espacements réguliers entre les lignes. Sur petit écran, libérer les largeurs minimales des dates pour permettre le repli.
- Pour les textes longs, viser environ 72 caractères par ligne et un interligne proche de 1.8. Conserver les titres, paragraphes et listes du contenu ; ne pas inventer de sous-titres dans un texte utilisateur ni tronquer les informations essentielles. Les tableaux, images et blocs de code gardent leur espace propre.
- Séparer les actions sensibles des actions courantes par un espacement ou un séparateur. Le groupe d’enregistrement se termine par l’action principale. Ne pas placer une suppression au contact immédiat d’un bouton d’enregistrement.
- Réutiliser [IconHint](../frontend/src/components/ux/IconHint.jsx) pour les boutons à icône qui demandent une explication. Le texte doit être court, disponible au focus clavier, refermable avec Échap et rester dans la fenêtre visible. Un bouton doit toujours garder son propre libellé accessible. Ne pas ajouter une infobulle sur chaque bouton avec texte.
- Sur écran tactile, les petites commandes ciblées font au moins 44 × 44 px. Tenir compte de `safe-area-inset-*` dans les barres fixes et fenêtres plein écran, sans ajouter de marge inutile sur ordinateur.
- Préserver l’instance de l’éditeur, son texte et son curseur lors des mises à jour ordinaires. Une réponse d’enregistrement ne doit pas fermer un brief qui a été modifié depuis l’envoi. Expliquer que les nouveaux ajouts restent à enregistrer. En cas d’erreur, garder le texte ouvert et permettre une nouvelle tentative.
- Dans les formulaires de fenêtres, désactiver temporairement les champs natifs pendant leur envoi pour ne pas fermer ensuite sur une saisie différente de celle enregistrée. Réactiver les champs après une erreur. Le rendu riche d’une tâche est également verrouillé pendant son envoi.
- L’en-tête mobile ne doit pas hériter d’une hauteur vide provenant d’un `flex-basis` prévu pour un alignement horizontal.

Ces règles complètent les protections de brouillon existantes ; elles n’introduisent pas de nouvel enregistrement automatique du contenu.

## 13. Repères de changement et hiérarchie du mouvement

[StateMotion.css](../frontend/src/components/ux/StateMotion.css) regroupe les durées et styles de ces interactions : pression 100 ms, retour de contrôle 180 ms, ouverture de section ou surface 220 ms, fermeture de fenêtre 160 ms. Le repère de changement local disparaît sur 400 ms. Le délai JavaScript de démontage de `Modal` doit rester synchronisé avec sa fermeture de 160 ms.

- [ChangeCue](../frontend/src/components/ux/ChangeCue.jsx) marque brièvement une valeur qui change, sans animation au montage ni sur une valeur identique. Ne pas réanimer toute une liste pour un seul changement de statut. Une préférence d’animations réduites annule aussi un effet en cours.
- À la fermeture d’une fenêtre partagée, un déplacement limité vers son déclencheur conserve le lien spatial avec la page. Les coordonnées sont relues à la fermeture ; le mouvement reste plafonné à 72 px horizontalement et 48 px verticalement. Sans déclencheur encore présent, ou pour une fenêtre plein écran, utiliser un retrait neutre. Conserver la gestion du focus et les protections de fermeture pendant l’envoi.
- [StableLabel](../frontend/src/components/ux/StableLabel.jsx) réserve la largeur des libellés possibles d’un bouton. La réserve n’ajoute pas de texte au libellé accessible, au texte DOM réel ou aux journaux d’interaction. Les compteurs utilisent des chiffres tabulaires et une place minimale adaptée à leur contexte ; ne pas tronquer un nombre pour tenir dans cette réserve.
- [ScrollEdges](../frontend/src/components/ux/ScrollEdges.jsx) indique les bords où du contenu reste à lire. Les repères répondent au défilement, au redimensionnement et aux changements de contenu ; ils disparaissent à l’extrémité. Ils ne capturent aucun clic. Un tableau qui déborde horizontalement est accessible au clavier avec un nom de région.
- [Disclosure](../frontend/src/components/ux/Disclosure.jsx) conserve un déclencheur stable, un état `aria-expanded` et un contenu inactif pendant sa fermeture. Les champs dont la saisie doit survivre au repli gardent leur état dans le composant parent. Les commentaires de tâche conservent leur chargement à l’ouverture.
- Les blocs du dashboard utilisent une transition de grille, gardent leur contenu monté et rendent le contenu replié inactif et masqué aux technologies d’assistance. Leurs poignées et commandes de réorganisation restent indépendantes de cette animation.

Tous ces mouvements respectent le réglage système et le réglage manuel de réduction. Les ombres de défilement restent de simples repères ; la lecture et la saisie ne déclenchent pas d’animation décorative continue.
