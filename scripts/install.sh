#!/usr/bin/env bash
# Installe les dépendances Python pour top8er_bot.py (Linux/macOS).
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 introuvable. Installe Python 3 (python.org ou le gestionnaire de paquets de ta distro) puis relance ce script." >&2
    exit 1
fi

python3 -m pip install --user requests beautifulsoup4 openpyxl

echo
read -r -p "Installer aussi playwright (nécessaire pour l'option --review) ? [o/N] " reponse
if [[ "$reponse" =~ ^[oOyY] ]]; then
    python3 -m pip install --user playwright
    echo "playwright installé. --review pilote le Google Chrome déjà installé sur la machine (pas besoin de 'playwright install')."
fi

echo
echo "Installation terminée. Exemple d'utilisation :"
echo "  python3 src/top8er_bot.py \"<lien start.gg>\" --background fond.png --logo logo.png --startgg-token <token>"
