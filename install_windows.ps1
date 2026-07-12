Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "STTLocal - installation Windows"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' introuvable. Installe Python 3.12 depuis https://www.python.org/downloads/windows/"
}

if (-not (Test-Path ".venv")) {
    try {
        py -3.12 -m venv .venv
    } catch {
        Write-Host "Python 3.12 indisponible, fallback sur le Python par defaut du launcher."
        py -m venv .venv
    }
}

.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host ""
Write-Host "Installation terminee."
Write-Host "Lancement conseille :"
Write-Host "python tray_app.py --model base --language fr"
