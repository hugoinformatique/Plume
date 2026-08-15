# Changelog

Versions correspond to `v*` git tags, each built and published by
`.github/workflows/windows-installer.yml`. See
[CONTRIBUTING.md#releasing](CONTRIBUTING.md#releasing) for the release
process.

## v0.4.9

- Add a temporary in-app "Bench" tab: record one reference clip, run it
  through every backend/device/model/compute combination, see results and a
  live log in the app, export to CSV. Marked for removal once no longer
  needed.
- Fix the benchmark sweep hanging with no feedback and no way to relaunch if
  it hit an unexpected error; add a scrolling progress log.

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
