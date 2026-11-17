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
