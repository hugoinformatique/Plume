Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

Write-Host "Plume - Windows build"

param(
    # The OpenVINO model conversion needs optimum-intel (torch, multi-GB) and
    # takes several minutes. Skip it for a quick local build -- the resulting
    # installer then has no NPU/iGPU support, which the app reports honestly
    # instead of failing at load.
    [switch]$SkipOpenVino
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt

if (-not $SkipOpenVino) {
    Write-Host "Installing the OpenVINO runtime (bundled: NPU / iGPU profiles)"
    python -m pip install -r requirements-openvino-runtime.txt

    # The reuse marker records the *precision*, not just "a model is there":
    # a whisper-small left over from the int8 era looks identical on disk and
    # would silently ship instead of the FP16 build the engine is validated on.
    $marker = "models\openvino\whisper-small\.plume-precision"
    if ((Test-Path "models\openvino\whisper-small\openvino_tokenizer.xml") -and
        (Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq "fp16")) {
        Write-Host "OpenVINO FP16 model already converted, reusing it"
    } else {
        Write-Host "Converting whisper-small to OpenVINO FP16 (isolated venv, slow)"
        # Same OpenVINO version as the bundled runtime: it refuses IR produced
        # by a newer release.
        $ov = python -c "import importlib.metadata as m; print(m.version('openvino'))"
        python -m venv .convert
        .\.convert\Scripts\python.exe -m pip install --upgrade pip
        .\.convert\Scripts\python.exe -m pip install "optimum-intel[openvino]>=1.21" "nncf>=2.14" "openvino==$ov"
        # FP16: the precision the shipping iGPU engine is validated on.
        .\.convert\Scripts\optimum-cli.exe export openvino `
            --model openai/whisper-small --weight-format fp16 `
            models\openvino\whisper-small
        foreach ($f in @("openvino_encoder_model.xml", "openvino_decoder_model.xml",
                         "openvino_tokenizer.xml", "openvino_detokenizer.xml")) {
            if (-not (Test-Path "models\openvino\whisper-small\$f")) {
                throw "OpenVINO export is incomplete: $f is missing"
            }
        }
        Set-Content -Path $marker -Value "fp16"
        Remove-Item -Recurse -Force .convert
    }
    $env:PLUME_REQUIRE_OPENVINO = "1"
}

Write-Host "Generating icon assets"
python scripts\make_icons.py

if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}

python -m PyInstaller --noconfirm "packaging\pyinstaller\Plume.spec"

$Iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($null -eq $Iscc) {
    $DefaultIscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $DefaultIscc) {
        $Iscc = $DefaultIscc
    }
}

if ($null -eq $Iscc) {
    Write-Host "Inno Setup not found. Skipping installer build."
    Write-Host "Portable app folder is available in dist\Plume"
    exit 0
}

New-Item -ItemType Directory -Force -Path "dist\installer" | Out-Null
& $Iscc "packaging\inno\Plume.iss"

Write-Host "Build complete."
Write-Host "Portable folder: dist\Plume"
Write-Host "Installer: dist\installer"
