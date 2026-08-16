<#
.SYNOPSIS
    Authenticode-sign a Plume build artefact.

.DESCRIPTION
    Used by .github/workflows/windows-installer.yml for both the app exe and
    the installer, and usable by hand for a local build.

    The certificate comes from two environment variables so it never lands in
    the repository:

      WINDOWS_CERT_PFX_BASE64  the .pfx file, base64-encoded
      WINDOWS_CERT_PASSWORD    its password

    In CI these are repository secrets. To produce the first one from a .pfx:

      [Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx")) | Set-Clipboard

    Signing is what removes the "unknown publisher" SmartScreen warning and
    takes most of the heat off antivirus heuristics -- see
    CONTRIBUTING.md#code-signing for how to obtain a certificate.
#>
param(
    [Parameter(Mandatory = $true)][string]$Path,
    # RFC 3161 timestamp authority. Timestamping is what keeps a signature
    # valid after the certificate itself expires; without it every build goes
    # untrusted the day the cert lapses.
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

if (-not $env:WINDOWS_CERT_PFX_BASE64) {
    throw "WINDOWS_CERT_PFX_BASE64 is not set: nothing to sign with."
}

$files = @(Get-ChildItem -Path $Path -File)
if ($files.Count -eq 0) { throw "No file matches $Path" }

# Newest SDK first: older signtool builds predate /tr (RFC 3161) support.
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -like "*\x64\*" } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if (-not $signtool) { throw "signtool.exe not found (install the Windows SDK)" }

$pfx = Join-Path ([IO.Path]::GetTempPath()) "plume-signing-$PID.pfx"
try {
    [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_CERT_PFX_BASE64))
    foreach ($file in $files) {
        Write-Host "Signing $($file.FullName)"
        & $signtool.FullName sign /f $pfx /p $env:WINDOWS_CERT_PASSWORD `
            /fd sha256 /tr $TimestampUrl /td sha256 $file.FullName
        if ($LASTEXITCODE -ne 0) { throw "signtool sign failed for $($file.Name)" }

        & $signtool.FullName verify /pa $file.FullName
        if ($LASTEXITCODE -ne 0) { throw "signtool verify failed for $($file.Name)" }
    }
}
finally {
    # The key material must not outlive the signing step, even on failure.
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}
