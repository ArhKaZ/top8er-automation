# Installe les dépendances Python pour top8er_bot.py (Windows).
# Lancer depuis PowerShell : .\scripts\install.ps1
# (si l'exécution de scripts est bloquée : powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1)

$ErrorActionPreference = "Stop"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "python introuvable. Installe Python 3 depuis https://python.org (coche 'Add python.exe to PATH' pendant l'installation) puis relance ce script."
    exit 1
}

python -m pip install --user requests beautifulsoup4 openpyxl

Write-Host ""
$reponse = Read-Host "Installer aussi playwright (necessaire pour l'option --review) ? [o/N]"
if ($reponse -match '^[oOyY]') {
    python -m pip install --user playwright
    Write-Host "playwright installe. --review pilote le Google Chrome deja installe sur la machine (pas besoin de 'playwright install')."
}

Write-Host ""
Write-Host "Installation terminee. Exemple d'utilisation :"
Write-Host '  python src\top8er_bot.py "<lien start.gg>" --background fond.png --logo logo.png --startgg-token <token>'
