Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "Plume - installation Windows"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' introuvable. Installe Python 3.12 depuis https://www.python.org/downloads/windows/"
}

if (-not (Test-Path ".venv")) {
    # `py -3.12 ...` doesn't throw a catchable PowerShell error when 3.12
    # isn't installed -- the launcher just prints a message to stderr and
    # exits non-zero, so a try/catch here silently does nothing and leaves
    # .venv missing. Check the exit code explicitly instead.
    py -3.12 -m venv .venv 2>$null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path ".venv\Scripts\python.exe")) {
        Write-Host "Python 3.12 indisponible, fallback sur le Python par defaut du launcher."
        py -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Impossible de creer l'environnement virtuel. Installe Python 3.12 depuis https://www.python.org/downloads/windows/"
        }
    }
}

.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "L'installation des dependances a echoue. Si l'erreur mentionne ctranslate2 ou un autre paquet sans wheel disponible pour ta version de Python, installe Python 3.12 specifiquement (py -3.12, voir https://www.python.org/downloads/windows/) et relance ce script -- il utilisera 3.12 automatiquement si present."
}

Write-Host ""
Write-Host "Installation terminee."
Write-Host "Lancement :"
Write-Host "python plume.py"
