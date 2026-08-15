# Architecture

How Plume is put together, for anyone picking up the code cold.

## Big picture

Plume is a Windows-first, local-only voice dictation app. There is no
server and no cloud API: audio capture, speech-to-text, text cleanup and
paste-into-active-app all happen on the machine running the app.

```
 mic  ->  Recorder (sttlocal.py)  ->  wav file
                                        |
                                        v
                    Transcriber backend (backends.py)
                    faster-whisper (CPU) or OpenVINO (CPU/GPU/NPU)
                                        |
                                        v
                text cleanup + vocabulary correction (sttlocal.py, vocabulary.py)
                                        |
                                        v
                        paste into the active window (sttlocal.py)
```

Everything above the dashed line is orchestrated by one of two front ends
that share the same core:

- **`plume.py`** — the current product. A pywebview app: native Python core
  (audio, engine, global hotkey, paste, tray, autostart, self-update) plus an
  embedded web view for the UI (`ui/index.html` for the main window,
  `ui/bubble.html` for the floating "listening" pill).
- **`tray_app.py`** — legacy Tk-based test app, kept for reference/testing but
  not the shipped product. Uses `listening_bubble.py` (a Tk canvas widget)
  instead of the HTML bubble.
- **`dictate.py`** — bare console MVP (F9 start/stop, Esc quit), useful for
  quick engine testing without any UI.

## Modules

| File | Responsibility |
|---|---|
| `plume.py` | Product app: window/tray/hotkey lifecycle, `PlumeApp` (native state + business logic), `Api` (methods exposed to the web UI as `window.pywebview.api.*`), self-update check/download. |
| `backends.py` | Pluggable STT engines. `Transcriber` protocol, `TranscriptionResult` (text/elapsed/language/rtf), `FasterWhisperBackend` (CPU, CTranslate2), `OpenVINOBackend` (CPU/GPU/NPU via OpenVINO GenAI), `create_backend()` factory. See [OpenVINO / NPU](../README.md#openvino--npu). |
| `sttlocal.py` | `Recorder` (mic capture -> wav via `sounddevice`), `DictationEngine` (thin backward-compatible wrapper around `backends.py` used by `tray_app.py`/`dictate.py`), text cleanup (`clean_transcript`, filler/repeat removal), spoken punctuation commands (`apply_spoken_commands`), clipboard paste (`paste_text`, `copy_text`). |
| `config.py` | Persistent per-user settings (`Config`, backed by `%APPDATA%\Plume\config.json` on Windows, `~/.config/plume` elsewhere), hotkey display-string <-> pynput format conversion. |
| `vocabulary.py` | User correction dictionary: biases recognition (`hotwords`/`initial_prompt`) and post-corrects known mis-hearings. |
| `ui_theme.py` | Shared design tokens (colors, font) and the procedurally-drawn feather app icon (used for the tray icon and window icon; also generates `assets/plume.ico`/`.png` at build time via `scripts/make_icons.py`). |
| `listening_bubble.py` | Tk-canvas floating "listening" pill — legacy, used by `tray_app.py` only. The shipped app uses `ui/bubble.html` instead. |
| `benchmark.py` | CLI: sweep backend x device x model x file combinations on `samples/` and write `benchmark-results/results.csv`. |
| `perflog.py` | CLI: summarize/tail the `metrics.csv` history the app writes per real dictation (see [BENCHMARKING.md](BENCHMARKING.md)). |

## UI (pywebview)

`ui/index.html` and `ui/bubble.html` are plain HTML/CSS/JS, no build step, no
framework. They talk to Python two ways:

- **UI -> Python**: `window.pywebview.api.<method>(...)` calls a method on the
  `Api` class in `plume.py`. The JS side wraps this in a small `Proxy` (see
  `const api = new Proxy(...)` in `index.html`) so `api.toggle()` etc. always
  resolve to a promise, even before pywebview has injected `window.pywebview`.
- **Python -> UI**: `PlumeApp._js(window, code)` calls `window.evaluate_js(code)`
  to invoke a function the page defined on `window.plume` (main window) or
  `window.plumeBubble` (bubble window) — e.g. `plume.setStatus(...)`,
  `plumeBubble.setState(...)`. Keep these two objects as the only surface
  Python pushes into; anything else risks silently no-op'ing if the page
  hasn't finished loading.

Design tokens (colors, radii, easing) live as CSS custom properties at the
top of `index.html`; `ui_theme.py` holds the equivalent Python-side palette
for the tray icon / legacy Tk bubble. They are kept in sync by convention,
not by a shared source of truth — if you change one, check the other.

## Packaging & release

- `packaging/pyinstaller/Plume.spec` — bundles `plume.py`, the `ui/` folder,
  and native deps (pywebview's EdgeChromium backend needs `clr_loader` +
  `pythonnet` on Windows) into `dist/Plume/`.
- `packaging/inno/Plume.iss` — Inno Setup script wrapping the PyInstaller
  output into `Plume-Setup-<version>.exe`.
- `scripts/build_windows.ps1` — drives both steps locally.
- `scripts/make_icons.py` — renders `assets/plume.ico`/`.png` from
  `ui_theme.make_icon_image()` before packaging.
- `.github/workflows/windows-installer.yml` — CI: on push of a `v*` tag,
  builds on `windows-latest` and publishes the installer as a GitHub Release
  asset. See [CONTRIBUTING.md](../CONTRIBUTING.md#releasing) for the release
  procedure.

## Data that never leaves the machine

- Recordings: `%APPDATA%\Plume\recordings\` (main app) — deleted/overwritten
  per session, not curated.
- Settings + history + vocabulary: `%APPDATA%\Plume\config.json`.
- Performance history: `%APPDATA%\Plume\metrics.csv`.

No network call is made except: (a) the optional startup/manual check against
the GitHub Releases API for app updates, and (b) the first-ever load of a
given Whisper model name, which `faster-whisper` downloads from Hugging Face
if it isn't already cached locally. Both are documented in the README
["Privacy Positioning"](../README.md#privacy-positioning) section.
