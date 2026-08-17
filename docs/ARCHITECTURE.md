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
  embedded web view for the UI (`ui/index.html`). The floating "listening"
  pill is a native Tk window (`floating_bubble.py`) featuring a liquid glass &
  water-droplet design (multi-layer optical depth, 3D droplet indicator bead,
  voice-reactive fluid wave ripples). It runs in its own thread, never takes focus,
  and degrades to a no-op if Tk is missing.
- **`dictate.py`** — bare console MVP (F9 start/stop, Esc quit), useful for
  quick engine testing without any UI.

## Modules

| File | Responsibility |
|---|---|
| `plume.py` | Product app: window/tray/hotkey lifecycle, `PlumeApp` (native state + business logic), `Api` (methods exposed to the web UI as `window.pywebview.api.*`), self-update check/download. |
| `backends.py` | Pluggable STT engines. `Transcriber` protocol, `TranscriptionResult` (text/elapsed/language/rtf), `FasterWhisperBackend` (CPU, CTranslate2), `OpenVINOBackend` (CPU/GPU/NPU via OpenVINO GenAI), `create_backend()` factory. See [OpenVINO / NPU](../README.md#openvino--npu). |
| `sttlocal.py` | `Recorder` (mic capture -> wav via `sounddevice`), `DictationEngine` (thin wrapper around `backends.py`, used by `plume.py` and `dictate.py`), text cleanup (`clean_transcript`, filler/repeat removal), spoken punctuation commands (`apply_spoken_commands`), clipboard paste (`paste_text`, `copy_text`). |
| `config.py` | Persistent per-user settings (`Config`, backed by `%APPDATA%\Plume\config.json` on Windows, `~/.config/plume` elsewhere), hotkey display-string <-> pynput format conversion. |
| `vocabulary.py` | User correction dictionary: biases recognition (`hotwords`/`initial_prompt`) and post-corrects known mis-hearings. |
| `ui_theme.py` | Shared design tokens (colors, font) and the procedurally-drawn feather app icon (used for the tray icon and window icon; also generates `assets/plume.ico`/`.png` at build time via `scripts/make_icons.py`). |
| `floating_bubble.py` | The shipped floating "listening" pill. `GlassRenderer` draws it with Pillow (supersampled, real per-pixel alpha) and `_LayeredWindow` pushes each frame to a Windows layered window via `UpdateLayeredWindow`, which is what makes it translucent glass with antialiased edges rather than a colour-keyed Tk canvas. Runs its own Tk loop in a daemon thread purely for windowing and events, driven from any thread through a command queue. Draggable, never takes focus, degrades to a no-op if Tk or Pillow is missing. Nothing is ever read back from the screen. |

## UI (pywebview)

`ui/index.html` is plain HTML/CSS/JS, no build step, no framework. It talks to
Python two ways:

- **UI -> Python**: `window.pywebview.api.<method>(...)` calls a method on the
  `Api` class in `plume.py`. The JS side wraps this in a small `Proxy` (see
  `const api = new Proxy(...)` in `index.html`) that queues calls behind a
  `bridgeReady` promise, so a click landing before pywebview has injected the
  bridge is delayed rather than silently dropped, and a bridge that never
  comes up surfaces an error instead of nothing.
- **Python -> UI**: `PlumeApp._js(window, code)` calls `window.evaluate_js(code)`
  to invoke a function the page defined on `window.plume` — e.g.
  `plume.setStatus(...)`. Keep that object as the only surface Python pushes
  into; anything else risks silently no-op'ing if the page hasn't finished
  loading. The bubble is not scripted this way: it is a Python object
  (`FloatingBubble`) called directly.

Design tokens (colors, radii, easing) live as CSS custom properties at the
top of `index.html`; `ui_theme.py` holds the equivalent Python-side palette
for the tray icon and the floating bubble. They are kept in sync by convention,
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
- Diagnostics: `%APPDATA%\Plume\debug.log` (local support trail, rotated at 1 MB).

No network call is made except the update check against the GitHub Releases
API, which is **off by default** (`auto_update`) and otherwise only runs when
the user presses "Vérifier". The shipped engine is the bundled OpenVINO
FP16 model, so no model download happens either. See
[SECURITY.md](SECURITY.md) and the README
["Privacy Positioning"](../README.md#privacy-positioning) section.
