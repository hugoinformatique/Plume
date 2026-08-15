# Contributing

## Dev setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python plume.py
```

Optional, only needed to touch the OpenVINO backend:

```powershell
python -m pip install -r requirements-openvino.txt
```

There is no automated test suite yet. Validate changes by running the app
(`python plume.py`) through the manual flow in
[TESTING_WINDOWS.md](TESTING_WINDOWS.md) / [GUIDE_TEST.md](GUIDE_TEST.md), and
`python -m py_compile <file>.py` at minimum before committing. If you touch
`ui/*.html`, there's no build step — just reload the app (the HTML is loaded
from disk on window creation, not compiled).

## Where things live

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module map before
making non-trivial changes — in particular, note that `plume.py` (pywebview)
is the shipped product and `tray_app.py` (Tk) is a legacy test harness; don't
add product features to the latter.

## Conventions observed in this codebase

- **Lazy heavy imports.** `backends.py` imports `faster_whisper` /
  `openvino_genai` inside `load()`, not at module scope, so importing the
  module never fails just because one optional dependency isn't installed.
  Keep following this pattern for new backends.
- **New engine backend?** Implement the `Transcriber` protocol in
  `backends.py` (`load()` + `transcribe(path, hotwords=None,
  initial_prompt=None) -> TranscriptionResult`), register it in `BACKENDS`,
  and it's automatically available to `dictate.py`, `benchmark.py`, and
  `plume.py` via `create_backend()`.
- **Config changes.** Add new settings to `config.DEFAULTS` with a sane
  default so existing `config.json` files upgrade without migration code.
  Document the key in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
- **UI <-> Python bridge.** Python only ever calls `window.plume.*` on the JS
  side (see `PlumeApp._js` in `plume.py`); the JS side only ever calls
  `window.pywebview.api.*` (an `Api` method). Don't invent a third channel.
  Every `Api` method goes through `@_api_call`: it is traced in `debug.log`
  and returns `{ok, error}` so a failure is visible in the UI instead of
  vanishing into a dropped promise.
- **Everything stays local.** No feature should require a network call except
  the optional update check and the (documented, one-time-per-model)
  Hugging Face download in `faster-whisper`. This is a hard product
  requirement for the enterprise/offline positioning — see README
  ["Privacy Positioning"](README.md#privacy-positioning).
- **Temporary/throwaway code** should be wrapped in clearly labeled markers
  (`BEGIN/END <NAME> (temporary, remove after X)`) and land in its own
  commit, so it can be found and reverted cleanly later. (An in-app
  benchmark tab was tried this way and later removed wholesale when the
  pywebview JS bridge turned out not to expose it reliably on packaged
  builds — the marker convention made that removal a clean, mechanical
  diff instead of an archaeology dig.)

## Releasing

Releases are tag-triggered: pushing a `v*` tag runs
`.github/workflows/windows-installer.yml` on `windows-latest`, which builds
the PyInstaller app + Inno Setup installer and publishes a GitHub Release
with `Plume-Setup-<version>.exe` attached.

1. Bump the version in every place it's hardcoded:
   - `plume.py` — `APP_VERSION`
   - `packaging/inno/Plume.iss` — `MyAppVersion`
   - Any `Plume-Setup-X.Y.Z.exe` mentions in `README.md`, `GUIDE_TEST.md`,
     `INSTALLER_WINDOWS.md`
2. Commit (`build: bump release to X.Y.Z`).
3. Tag and push:
   ```powershell
   git tag vX.Y.Z
   git push origin vX.Y.Z
   git push origin <branch>
   ```
4. Watch the run: `gh run list --repo hugoinformatique/Plume --limit 3` or the
   **Actions** tab. On success the installer appears under **Releases**.

`main` is the only active branch — it was fast-forwarded to the tip of
`feat/plume-pluggable-backends` and all work (commits, tags, releases)
happens there from now on. `feat/plume-pluggable-backends` is kept around
for now as a historical pointer but should not receive new commits; it may
be deleted later.

## Code signing (reducing SmartScreen/antivirus warnings)

The installer isn't signed, so Windows shows an "unknown publisher" warning
and some antivirus/EDR software scrutinizes it more heavily on first run —
this is a real friction point for the enterprise deployment target, not
cosmetic. A [LICENSE](LICENSE) (MIT) alone doesn't fix this; **only a code
signing certificate does.** Two paths, in order of preference:

1. **Free, for open source projects**: [SignPath.io](https://signpath.io)
   signs open source releases at no cost. Requirements this repo already
   meets or now meets: public repository, OSI-approved license (MIT, added).
   Still needed: apply on signpath.io, get approved, wire their CI action
   into `.github/workflows/windows-installer.yml` to sign
   `dist/installer/*.exe` before it's attached to the release. This requires
   an account and approval from a human maintainer — not something to
   automate blindly.
2. **Paid certificate**: an OV (~$100-400/year) or EV
   (~$300-500/year, near-instant SmartScreen reputation) Authenticode
   certificate from any CA (DigiCert, SSL.com, etc.), then sign
   `dist/installer/*.exe` in CI with `signtool sign /a /fd sha256
   /tr <timestamp-url> /td sha256 dist\installer\Plume-Setup-*.exe` as a
   build step, using a certificate stored as a GitHub Actions secret.

Either way, expect the *first* unsigned or newly-signed builds to still get
flagged by some engines until reputation builds up — that's normal and not
something a single fix resolves overnight.
