# Spec fonctionnelle — Automatisation Top8er (SSBU)

## Objectif

Générer automatiquement un visuel "Top 8" sur https://www.top8er.com/old/ssbu à partir :
1. d'un lien de tournoi (start.gg / challonge / tonamel / parry.gg) pour les noms de joueurs et placements,
2. des personnages **réellement joués** par chaque joueur pendant le tournoi (API start.gg, comptage game par game — voir section dédiée), pour décider quels persos afficher,
3. d'un fichier de référence des skins (`Skins des joueurs et joueuses.xlsx`) pour la couleur de chaque perso retenu, quand elle est connue,
4. éventuellement d'une police custom, et de couleurs configurables en arguments CLI.

Le site ne propose pas d'API JSON : c'est une app Django classique, formulaire HTML → POST multipart avec jeton CSRF. L'automatisation se fait par requêtes HTTP (pas besoin de navigateur headless). Pour l'usage réel des personnages, une requête supplémentaire est faite vers l'API GraphQL de start.gg (`api.start.gg/gql/alpha`), qui nécessite un token d'authentification.

## Entrées

| Entrée | Valeur / emplacement |
|---|---|
| Lien de tournoi | fourni par l'utilisateur à chaque exécution (CLI arg)<br>ex. testé : `start.gg/tournament/la-tea-party-50/event/ultimate-singles/brackets/2458265/3533671` |
| Preset d'événement | option CLI `--event` : `tea_party`, `saucismash` ou `sauria` (facultative) |
| Fichier skins | `data/skin.xlsx` (format triplet, colonnes : Joueur, Perso, skin — voir plus bas) |
| Police custom | option CLI `--font` (facultative) ; preset `tea_party` : `data/tea_party/Basteleur-Bold.ttf` |
| Main Color | argument `--main-color` (défaut `#f1c4ee`) → champ `lcolor1` |
| Highlight Color | argument `--highlight-color` (défaut `#cecece`) → champ `lcolor2` |
| Background image | option CLI `--background` (facultative, chemin de fichier image) → champ `background` si fournie |
| Logo | option CLI `--logo` (facultative, chemin de fichier image) → champ `logo` si fourni |
| Presets d'images | `data/tea_party/logo_tea_party.png`, `data/tea_party/background_tea_party.png`, `data/logo_sauria.png` et `data/background_sauria.png` |
| Token API start.gg | fourni par l'utilisateur à chaque exécution (argument CLI `--startgg-token`), généré sur developer.start.gg → Developer Settings → Create new token |

Le fichier de skins devra être placé dans le dossier du projet (`top8er-automation/data/`). La police custom, si elle est utilisée, et les images background/logo peuvent être fournies avec leurs arguments CLI, sans être committées dans `data/`.

Le preset `tea_party` utilise `#f1c4ee` / `#cecece`, son logo, son background et la police
`data/tea_party/Basteleur-Bold.ttf` ;
`saucismash` utilise `#182A45` / `#204d74` sans image ; `sauria` utilise ces deux dernières
couleurs avec son logo et son background. Les options de police, de couleurs et d'images
données explicitement sur la ligne de commande remplacent les valeurs correspondantes du preset.

## Flux d'exécution (2 requêtes POST successives, même session)

1. **GET** `https://www.top8er.com/old/ssbu` → récupérer le cookie de session Django + la valeur de `csrfmiddlewaretoken` (champ hidden dans le HTML).
2. **POST** vers la même URL avec le formulaire `form2` (`enctype=multipart/form-data`) :
   - `csrfmiddlewaretoken`
   - `event` = lien du tournoi
   - → La réponse est une page HTML contenant le formulaire `form1` **pré-rempli** par Top8er (noms de joueurs importés + perso principal deviné automatiquement). Il faut parser cette réponse HTML (BeautifulSoup) pour extraire, pour chaque `playerN_*`, la valeur courante (`value=` pour les inputs, `selected` pour les `<select>`), ainsi que le nouveau `csrfmiddlewaretoken` (il peut changer).
3. **Transformation** : interroger l'API start.gg pour l'usage réel des personnages, sélectionner les persos à afficher par joueur, puis appliquer la couleur depuis le xlsx (ou la couleur par défaut) sur les champs extraits à l'étape 2 (voir section "Sélection des personnages à afficher").

> **Validé en conditions réelles** avec le lien de test ci-dessus : l'étape 2 fonctionne, Top8er a importé 8 joueurs (`ECR BLS | Slacker`, `KamaGi`, `CTR | SimonF`, `E0 | PINGU | Ana`, `MPT | J44J`, `Tap Tap Tap | Kensi1313`, `Djacky`, `NES | Gwermasterking`) avec un perso deviné pour chacun (Palutena, Min Min, Falco, Mii Brawler, Wolf, Fox, Sora, Min Min). Les noms start.gg peuvent contenir un tag d'équipe avant `|` et plusieurs segments ; pour rapprocher le joueur du xlsx, seul le dernier segment (après le dernier `|`) est comparé.
4. **POST** vers la même URL avec le formulaire `form1` complet (tous les champs `playerN_*` + options globales), en incluant uniquement les fichiers fournis (`font_file`, `background`, `logo`).
   - → La réponse contient le visuel généré (probablement une image, embarquée au niveau de l'ancre `#result` dans le HTML — à confirmer à l'implémentation : image inline en base64, ou URL vers un fichier statique généré côté serveur). Le script doit sauvegarder cette image en local.

## Mapping des champs form1 (rappel du schéma réel du site)

Pour chaque joueur `N` de 1 à 8 :
- `playerN_name` (texte)
- `playerN_twitter` (texte, optionnel)
- `playerN_char` (select — roster SSBU complet, valeurs exactes listées dans le `<select>` de la page, ex. `"Pac-Man"`, `"ROB"`, `"King Dedede"`, `"Mr Game & Watch"`, `"Rosalina & Luma"`, `"Pyra and Mythra"`, `"Zero Suit Samus"`…)
- `playerN_color` (select `0`–`7`)
- `playerN_extra1` / `playerN_extra_color1` (perso secondaire + couleur, optionnels)
- `playerN_extra2` / `playerN_extra_color2` (perso tertiaire + couleur, optionnels)
- `playerN_flag`, `playerN_portrait`, `playerN_custom_flag` : **non gérés par cette automatisation** — laisser la valeur renvoyée par Top8er après l'étape 2 (généralement `"None"` / vide), sauf évolution future demandée.

Options globales à fixer dans toutes les générations :
- `lcolor1` = valeur de `--main-color` (défaut `#f1c4ee`, format `#RRGGBB`)
- `lcolor2` = valeur de `--highlight-color` (défaut `#cecece`, format `#RRGGBB`)
- `font_file` = upload du fichier passé avec `--font`, si fourni
- `fontt` = laisser la valeur par défaut (`auto`) ; **hypothèse à vérifier à l'implémentation** : un `font_file` uploadé est-il prioritaire sur la valeur de `fontt` ? Si le rendu final n'utilise pas la police custom, il faudra tester les 3 valeurs de `fontt` en combinaison.
- `background` = upload de l'image passée en argument CLI `--background`, si fournie
- `logo` = upload de l'image passée en argument CLI `--logo`, si fourni
- Reste des options (`ttext`, `btext`, `url`, `darken_bg`, `blacksquares`, `charshadow`, `prmode`, `fcolor1/2`, `fscolor1/2`) : garder les valeurs par défaut du formulaire (non spécifiées par l'utilisateur).

## Sélection des personnages à afficher

**Règle** (remplace l'usage brut du perso deviné par Top8er) : pour chaque joueur, on détermine les personnages à afficher à partir de leur usage réel pendant tout le tournoi (pools + bracket), pas seulement depuis le xlsx ou la devinette de Top8er :

1. Récupérer, via l'API start.gg, le nombre de **games** joués par personnage pour chaque joueur, sur l'ensemble de l'event (tous les sets du joueur dans l'event dont provient le lien, pas seulement le bracket top8 final).
2. Ne retenir que les personnages joués sur **au moins 2 games**.
3. Trier par nombre de games décroissant, garder les **3 premiers** → perso principal, secondaire, tertiaire dans cet ordre.
4. Si un joueur a moins de 3 personnages qui qualifient, les slots restants ne sont pas remplis (perso Top8er par défaut conservé, généralement vide pour secondaire/tertiaire).
5. Cas particulier : une sélection `"Random Character"` côté start.gg n'est **pas** un vrai perso affichable (le site ne l'accepte même pas en secondaire/tertiaire) → elle est exclue du classement, sans bloquer la sélection des autres personnages du joueur.
6. Un nom de personnage renvoyé par start.gg qui ne matche aucune valeur du roster Top8er (même après alias) est logué et exclu, sans bloquer la génération.

> **Validé en conditions réelles** sur `la-tea-party-50` : contrairement à ce que laissait supposer le xlsx (qui indiquait Wario comme perso "MAIN" de Slacker), les données game par game montrent que Slacker a surtout joué Palutena (8 games), Pokemon Trainer (4) et Jigglypuff (3) sur le tournoi — ce sont donc ces 3 personnages qui sont affichés, dans cet ordre.

### Appel API start.gg

- Endpoint : `POST https://api.start.gg/gql/alpha`, header `Authorization: Bearer <token>`.
- Le slug d'event (`tournament/<t>/event/<e>`) s'extrait directement du lien de tournoi fourni en entrée (même lien que pour l'import Top8er).
- Requête : `event(slug) { sets(page, perPage) { nodes { slots { entrant { id name } } games { selections { selectionType entrant { id } character { name } } } } } }`, paginée.
- **Limite de complexité de l'API** : un `perPage` trop élevé déclenche une erreur `"query complexity is too high"` (observé dès 60) ; `perPage: 25` passe de manière fiable sur le tournoi testé (~43 participant.e.s).
- Le nom d'entrant (`entrant.name`) correspond au même `playerN_name` que celui importé par Top8er (même source de données start.gg), donc le même matching par segments `|` (cf. règle de matching ci-dessous) s'applique pour relier usage et xlsx.

## Résolution de la couleur (skins) depuis le xlsx

Une fois les personnages à afficher déterminés (section précédente), le xlsx sert uniquement à fournir la **couleur** : pour chaque (joueur, personnage retenu), si le xlsx a un skin connu pour CE personnage précis chez ce joueur, on applique sa couleur ; sinon, **couleur par défaut = `0`**.

### Format du fichier source (v2 — triplet)

Une ligne = un triplet `Joueur | Perso | skin` (plus de colonnes MAIN/SECONDARY/TERTIARY) : un joueur ayant plusieurs persos connus a simplement plusieurs lignes. `Perso` et `skin` sont des listes déroulantes (roster SSBU complet / 0-7) alimentées par une feuille annexe "Listes", pour éviter les fautes de saisie en amont. Un joueur qui a plusieurs persos connus a donc plusieurs lignes (même nom dans la colonne `Joueur`, répété autant de fois que de persos). Fichier d'exemple avec les listes : `data/skin.example.xlsx` (à copier/renommer en `data/skin.xlsx`, le chemin par défaut attendu par le script).

**Migration depuis l'ancien format** : `src/migrate_skins_format.py <ancien.xlsx> <nouveau.xlsx>` convertit automatiquement les colonnes MAIN/SECONDARY/TERTIARY en lignes triplet (colonnes repérées par leur en-tête, pas par position fixe, pour tolérer des colonnes réordonnées/ajoutées). Les cellules ambiguës de l'ancien format ne sont pas migrées automatiquement (cf. liste ci-dessous) : elles sont listées en sortie du script pour être recomplétées à la main dans le fichier généré.

**Doublons** : si plusieurs lignes donnent un skin différent pour le même (joueur, perso) — par exemple après des mises à jour successives —, on garde le skin le plus bas qui n'est pas `0` ; `0` seulement s'il n'y a pas d'autre valeur.

### Règles de normalisation requises

1. **Matching du nom de joueur avec le xlsx** : partir de `playerN_name` (= `entrant.name` start.gg), ne garder que la partie après le dernier `|` (ex. `"Deer | Dickium Monstruosus"` → `"Dickium Monstruosus"`, `":3 | Alexandre*"` → `"Alexandre*"`), puis comparer au nom du xlsx sans tenir compte de la casse ni des espaces de début/fin. Les suffixes `*` en fin de nom doivent être ignorés pour le matching.
2. **Résolution du nom de perso** : mapper la valeur de la colonne `Perso` vers la valeur exacte attendue par le `<select>` de Top8er via une **table d'alias** à construire, incluant au minimum les cas observés jusqu'ici (utile surtout pour la migration depuis l'ancien format, où les noms étaient en texte libre) :
   - `"R.O.B"` → `"ROB"`
   - les points sont ignorés lors de la comparaison des noms : `"Bowser Jr"` et `"Bowser Jr."` désignent le même perso ; le libellé officiel du roster Top8er est conservé
   - `"Pac Man"` → `"Pac-Man"`
   - `"Palu"` / `"palu"` → `"Palutena"`
   - `"Dadidou"` → `"King Dedede"`
   - `"Pyra & Mythra"` → `"Pyra and Mythra"` (ordre non précisé, "Pyra and Mythra" pris par défaut)
   - `"Random Character"` (libellé API start.gg) → `"Random"` (valeur Top8er) — mais exclu du classement des persos affichés, cf. règle 5 de la section précédente
   - (table à compléter si d'autres surnoms apparaissent)
3. **Lignes non résolubles automatiquement** — ne **pas** deviner, logguer un avertissement explicite, la couleur retombe alors sur la valeur par défaut (`0`) :
   - perso non reconnu même après la table d'alias ;
   - skin non numérique ou hors plage 0-7 (ne devrait plus arriver avec la liste déroulante, mais reste possible en cas de collage de valeur brute) ;
   - ligne avec nom de joueur illisible (ex. la ligne dont le nom est juste `` ` ``).
4. **Rapport de synthèse** : à chaque exécution, produire un résumé texte listant, par joueur : les personnages retenus (avec nombre de games et source de la couleur, xlsx ou défaut), les personnages non reconnus ou exclus (Random), et séparément les lignes du xlsx ignorées (avec la raison).

## Mode revue (`--review`)

Option qui bloque avant la génération finale (étape 4) : au lieu du POST final via `requests`, elle pilote un vrai navigateur (Playwright, Chrome système via `channel="chrome"`, profil isolé dédié pour ne pas interférer avec le Chrome personnel de l'utilisateur) qui :

1. navigue sur le site, importe le tournoi (reproduit l'étape 2 depuis le navigateur, avec sa propre session/CSRF) ;
2. remplit le formulaire `form1` avec les valeurs calculées par le script (skins + persos joués + couleurs/police, avec background et logo uniquement s'ils sont fournis) ;
3. laisse la fenêtre ouverte, sans cliquer sur "Generate" : l'utilisateur relit/modifie à la main, puis clique lui-même quand il est prêt. Le script rend la main quand la fenêtre est fermée.

> **Pièges rencontrés et corrigés en conditions réelles** : plusieurs sections du formulaire sont repliées par défaut (`display:none`) et doivent être dépliées par un clic avant de pouvoir y écrire quoi que ce soit : l'onglet "Enter tournament link" (`button.sggform`) pour révéler `form2`, "+ Layout Options" (`span.togglelayopt`, contient `lcolor1`/`lcolor2`) et "+ Font Options" (`span.togglefontopt`, contient `fontt`/`font_file`), ainsi qu'un bouton "+" (`span.showextra`) **par joueur** (8 au total) pour révéler les champs perso secondaire/tertiaire (`extra1`/`extra2`).

Dépendance additionnelle, uniquement pour cette option : `playwright` (pip), en s'appuyant sur un Google Chrome déjà installé sur la machine plutôt que sur un téléchargement de navigateur dédié.

## Sorties attendues

- L'image générée, sauvegardée dans `top8er-automation/output/<timestamp>-<slug_tournoi>.png` (ou extension correspondant au vrai type renvoyé par le serveur).
- Le rapport de synthèse (overrides appliqués / ignorés), affiché en console et sauvegardé en `.log` ou `.md` à côté de l'image.

## Hors-périmètre (pour cette première version)

- Gestion des drapeaux et portraits custom par joueur.
- Interface graphique ou mode interactif de résolution des cas ambigus (pour l'instant : log + défaut Top8er).
- Support d'autres jeux que SSBU (`/old/ssbu` uniquement).
- Gestion multi-tournoi en lot (une exécution = un lien de tournoi).

## Stack technique proposée

Python + `requests` (gestion cookies/session native, + appel GraphQL start.gg) + `beautifulsoup4` (parsing HTML du formulaire pré-rempli et extraction du résultat) + `openpyxl` (lecture xlsx). Pas de navigateur headless nécessaire (confirmé : aucun appel AJAX/fetch côté client, formulaire POST classique protégé par CSRF Django).

## Points validés / restants

1. ✅ Format de la réponse après le POST final : image embarquée en base64 (`<img src="data:image/png;...base64,...">`), à extraire parmi de nombreux autres `<img>` non liés au résultat présents ailleurs sur la page.
2. ✅ Police custom (`font_file`) bien appliquée visuellement au rendu final, sans besoin de changer `fontt`.
3. ✅ start.gg confirmé comme format de lien d'entrée (testé avec succès : `la-tea-party-50`).
4. ✅ Sélection des persos joués + résolution de couleur testées de bout en bout avec un vrai token start.gg sur `la-tea-party-50` (43 participant.e.s).
5. ⏳ Vérifier qu'il n'y a pas de contrainte serveur sur le format/poids des images `background`/`logo` (testé en `.png` et `.webp`, tous deux acceptés sans erreur).
6. ⏳ Valider avec l'utilisateur la table d'alias de personnages au fur et à mesure que de nouveaux cas apparaissent dans le xlsx ou dans les données start.gg.
7. ⏳ `perPage: 25` sur la requête start.gg est un choix empirique (60 dépasse la limite de complexité de l'API) ; à re-vérifier sur des tournois beaucoup plus gros (centaines de participant.e.s, beaucoup de sets).
