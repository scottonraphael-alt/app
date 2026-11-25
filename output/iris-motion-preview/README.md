# Iris — étude UX inspirée d’UiZZe

Preview autonome de l’interface IRIS, avec ses fixtures locales et son bundle prêt à servir. Référence visuelle : https://uizze.com/ consultée le 22 novembre 2026. Aucun actif propriétaire récupéré ; surfaces, rayons et interactions sont dessinés en CSS.

Ouvrir http://127.0.0.1:8876/ . Le sélecteur en bas compare les styles actuels et proposés. L’accueil, Projets et Ressources permettent d’explorer les composants ; les autres parcours ne sont pas simulés. Toutes les données et opérations sont fictives et locales. Recharger réinitialise la démonstration.

Évolution proposée : navigation en capsules, boutons légèrement en relief et retour de pression, cartes plus arrondies, titres plus affirmés, repères pastel localisés et apparitions courtes. Navigation supérieure et dashboard personnalisable conservés. Thème sombre et réduction des animations disponibles.

Passe motion : micro-animations différenciées sur les surfaces réelles d’IRIS — symbole du prochain relais qui respire, demande qui arrive comme un message, agenda révélé par étapes, panneaux et cartes qui montent, progression qui se remplit. Les interactions ajoutent un transfert visuel de la demande vers Aurélie, un déplacement de projet entre colonnes, une conversation locale avec bulles et réponse, un détail d’événement dépliable et une coche animée pour confirmer une résolution. Les animations s’arrêtent avec la préférence de mouvement réduit, dans le navigateur comme dans le contrôle de preview.

Interactions vérifiées manuellement : prise de relais, déplacement de projet, réponse locale dans une conversation, dépliage d’événement et confirmation de résolution. La préférence de mouvement réduit désactive aussi le déplacement animé des projets.

Pour relancer le serveur :

```sh
python3 -m http.server 8876 --bind 127.0.0.1 --directory output/iris-motion-preview
```

Sources : `entry.jsx`, `reinvention.css`, `mock-api.js`. Reconstruction locale : `node build.cjs` (nécessite esbuild dans `/private/tmp/iris-preview-builder`). Le bundle compilé est inclus pour ouvrir la preview sans reconstruire.


## Nouvelle piste — composition repensée

L’entrée principale présente désormais un prototype de composition : accueil asymétrique avec prochain relais et agenda, cartes de dossiers, tableau de projets par étapes et bibliothèque de ressources. Le logo existant et les cinq accents sont conservés. Cette version ne reproduit pas encore tous les accès et modules métier ; elle sert à valider la direction avant intégration. L’aperçu précédent reste accessible par `v1.html`.

Les interactions de création d’idée, déplacement d’un projet, prise de relais et ordre des blocs sont simulées en mémoire. La recherche, les catégories, les dialogues, le thème et la réduction du mouvement fonctionnent localement. Source graphique de cette piste : `reinvention.css`.
