# Changelog

Versions correspond to `v*` git tags, each built and published by
`.github/workflows/windows-installer.yml`. See
[CONTRIBUTING.md#releasing](CONTRIBUTING.md#releasing) for the release
process.

## v0.4.15

- `private_mode=True` (v0.4.14) made no difference — `window.pywebview.api`
  is still completely empty (`Object.keys(...)` -> `[]`), not just missing
  the benchmark methods. Reverted it (no evidence it helped, only added
  risk). This is now a bigger issue than the benchmark tab: the JS<->Python
  bridge appears non-functional for *every* Api method in this build.
  Root cause still open — see `docs/BENCH_BRIDGE_DEBUG.md` for what's ruled
  out and the next diagnostic step (run `python plume.py` from source to
  isolate whether this is a PyInstaller packaging issue or a pywebview/
  WebView2 environment issue).

## v0.4.14

- Found it (via devtools console, added in v0.4.13): `window.pywebview.api`
  was missing `bench_record_start`/`bench_record_stop`/`run_benchmark`
  entirely, even with a byte-for-byte fresh install (exe and `ui/index.html`
  same timestamp). Root cause suspected at the time: WebView2 keeps a
  persistent browser profile across app versions. `webview.start(...,
  private_mode=True)` forced a clean profile every launch — turned out not
  to fix it (see v0.4.15).

## v0.4.13

- Still no `benchmark-inapp.log` created after a clean reinstall + relaunch
  (ruled out a stale locked process from a previous version). Since the
  Python-side logging added in v0.4.12 never fires, the failure must be on
  the JS side of the bridge, invisible until now: `webview.start(...,
  debug=True)` — enables right-click "Inspect"/"Afficher les outils de
  developpement" so real JS console errors are finally visible instead of
  failing completely silently.

## v0.4.12

- Root-caused v0.4.11's "nothing happens, 0% CPU/network" report: the log
  file never existed, meaning `run_benchmark()` was returning immediately
  because the reference clip wasn't found — the record-clip step was
  failing silently with no error surfaced. `bench_record_start`/`_stop` now
  log every step (mic open, capture stop, file save) and report real errors
  instead of a generic "too short", so a microphone failure is visible
  instead of indistinguishable from a hang.
- The log file is append-only across the whole session now (previously the
  benchmark run truncated it, erasing the record-step history that would
  have explained this).

## v0.4.11

- Benchmark log is now also written to `%APPDATA%\Plume\benchmark-inapp.log`
  on disk, live, independently of the in-app UI panel — so progress is
  visible even if the JS bridge update doesn't render for some reason.
- Set `HF_HUB_DOWNLOAD_TIMEOUT` before a sweep so a stalled connection while
  downloading an uncached model fails fast instead of hanging indefinitely;
  log whether each faster-whisper model is already cached locally before
  attempting to load it, so a pending download is obvious upfront.

## v0.4.10

- Fix the in-app benchmark sweep hanging with no feedback and no way to
  relaunch if it hit an unexpected error; add a scrolling, timestamped
  progress log so a slow (e.g. first-time model download) run is visibly
  different from a stuck one.
- Add `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, `docs/BENCHMARKING.md`,
  `CONTRIBUTING.md`, `CHANGELOG.md`; README now indexes all documentation.

## v0.4.9

- Add a temporary in-app "Bench" tab: record one reference clip, run it
  through every backend/device/model/compute combination, see results and a
  live log in the app, export to CSV. Marked for removal once no longer
  needed.

## v0.4.8

- Tune the `faster-whisper` CPU backend for reliability/speed: pin
  `cpu_threads` to the machine's core count instead of the default (avoids
  Windows scheduling work onto Intel hybrid low-power cores), expose
  hallucination-reduction thresholds.
- Add `perflog.py` to summarize/tail the `metrics.csv` performance history
  the app already writes per dictation.
- Accessibility/motion polish on the glass UI: visible keyboard focus rings,
  `prefers-reduced-motion` support, keyboard-operable settings toggles.
- Reserve the glass/blur treatment for the hero (mic button) card only;
  flatten secondary cards for a calmer visual hierarchy.

## v0.4.7

- Add an in-app update flow (check GitHub Releases, download and launch the
  new installer from within the app).

## v0.4.6

- Remove duplicate window controls; use a monochrome tray/window icon.

## v0.4.5

- Fix history list horizontal overflow in the main window.

## v0.4.4

- Rework hotkey capture and settings window controls.

## v0.4.3

- Harden the global hotkey and window scrolling behavior on Windows.

## v0.4.2 / v0.4.1

- UI polish pass on the desktop app and hotkey capture flow.

## v0.4.0

- Package the app with `pywebview` (replacing the Tk-only UI as the primary
  product surface): `plume.py` entry point, bundle the `ui/` folder,
  `clr_loader`/`pythonnet` for the Windows EdgeChromium backend.
- Add dictation history and spoken punctuation commands (`apply_spoken_commands`
  in `sttlocal.py`).
- Web-glass UI, correction dictionary (`vocabulary.py`), configurable hotkey.

## v0.3.1

- UI/window design polish; voice-reactive listening bubble.

## v0.3.0

- Generate the app icon programmatically; publish the installer as a GitHub
  Release asset on tag push (CI).
- Rename the product from **ScribeLocal** to **Plume**.
- Add pluggable STT backends (`backends.py`): `faster-whisper` (CPU baseline)
  and `openvino` (CPU/GPU/NPU on Intel Core Ultra), replacing the earlier
  CPU-only engine.

## Before v0.3.0 (ScribeLocal MVP)

- Local Whisper dictation MVP (`faster-whisper`, CPU): global hotkey,
  clipboard paste, text cleanup.
- Windows tray test app, testing procedure docs, Windows installer packaging.
