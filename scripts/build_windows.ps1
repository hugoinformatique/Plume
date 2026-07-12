Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

Write-Host "ScribeLocal - Windows build"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt

if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}

python -m PyInstaller --noconfirm "packaging\pyinstaller\ScribeLocal.spec"

$Iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($null -eq $Iscc) {
    $DefaultIscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $DefaultIscc) {
        $Iscc = $DefaultIscc
    }
}

if ($null -eq $Iscc) {
    Write-Host "Inno Setup not found. Skipping installer build."
    Write-Host "Portable app folder is available in dist\ScribeLocal"
    exit 0
}

New-Item -ItemType Directory -Force -Path "dist\installer" | Out-Null
& $Iscc "packaging\inno\ScribeLocal.iss"

Write-Host "Build complete."
Write-Host "Portable folder: dist\ScribeLocal"
Write-Host "Installer: dist\installer"
