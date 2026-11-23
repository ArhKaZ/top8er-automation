# Top8er Automation (SSBU)

Génère automatiquement un visuel "Top 8" sur [top8er.com/old/ssbu](https://www.top8er.com/old/ssbu)
à partir d'un lien de tournoi start.gg, de l'usage réel des personnages en jeu, et d'un
fichier de skins de référence.

Voir [`SPEC.md`](./SPEC.md) pour le détail des règles fonctionnelles.

## Installation

```bash
pip install --user requests beautifulsoup4 openpyxl
```

Pour le mode `--review` (facultatif, voir plus bas), il faut en plus :

```bash
pip install --user playwright
```

Un Google Chrome déjà installé sur la machine suffit (le script le pilote via
`channel="chrome"`) — pas besoin de `playwright install`.

## Données locales requises

Ce repo ne versionne pas les données spécifiques à un contexte (pseudos réels de joueurs,
police avec licence non vérifiée). À placer soi-même avant de lancer le script :

- `data/Skins des joueurs et joueuses.xlsx` — colonnes `Nom | MAIN | SECONDARY | TERTIARY`,
  une cellule perso = `"<Personnage> <couleur 0-7>"`.
- `data/Basteleur-Bold.ttf` (ou une autre police, en passant `--font`).

## Utilisation

```bash
python3 src/top8er_bot.py "<lien de tournoi start.gg>" \
  --background <image.png/webp> \
  --logo <image.png/webp> \
  --startgg-token <token API start.gg>
```

Le token API start.gg se génère gratuitement sur
[developer.start.gg](https://developer.start.gg) → Developer Settings → Create new token.

### Arguments

| Argument | Obligatoire | Rôle |
|---|---|---|
| `tournament_link` (positionnel) | oui | Lien start.gg du bracket |
| `--background` | oui | Image de fond du visuel |
| `--logo` | oui | Logo (remplace le texte en haut à gauche) |
| `--startgg-token` | oui | Token API start.gg |
| `--skins` | non | Chemin du xlsx de skins (défaut : `data/Skins des joueurs et joueuses.xlsx`) |
| `--font` | non | Chemin de la police (défaut : `data/Basteleur-Bold.ttf`) |
| `--outdir` | non | Dossier de sortie (défaut : `output/`) |
| `--review` | non | Bloque avant la génération finale : ouvre un vrai navigateur (profil Chrome isolé, dédié à cet usage) avec le formulaire déjà pré-rempli par nos calculs (skins + persos joués), pour relecture/modification manuelle. Rien n'est généré automatiquement : c'est à toi de cliquer sur "Generate" dans le navigateur. Le script rend la main quand tu fermes la fenêtre. |

### Sortie

- `output/<timestamp>-<slug>.png` — l'image finale
- `output/<timestamp>-<slug>.response.html` — réponse brute du site (debug)

Le script affiche aussi en console, pour chaque joueur, les personnages retenus (avec leur
nombre de games joués et la source de leur couleur) ainsi que les lignes du xlsx ignorées
car ambiguës.
