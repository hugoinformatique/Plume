# Configuration

All persistent state lives in one per-user JSON file, so it survives
reinstalls and is never bundled with the app.

## Location

| OS | Path |
|---|---|
| Windows | `%APPDATA%\Plume\config.json` |
| Other (dev/testing) | `~/.config/plume/config.json` |

The same directory (`config.config_dir()`) also holds `metrics.csv` (see
[BENCHMARKING.md](BENCHMARKING.md)) and `recordings/` (transient wav files,
deleted right after each transcription).

Read/write goes through `config.Config` (`config.py`): `Config.load()` reads
the file and fills in any missing key from `DEFAULTS`; `Config.set(key,
value)` writes a key and persists immediately.

## Schema

| Key | Default | Meaning |
|---|---|---|
| `language` | `"fr"` | Whisper language hint. `"auto"` lets Whisper detect it. |
| `model` | `"small"` | Model name for `faster-whisper` (`base`/`small`/`medium`/`turbo`), or a filesystem path to a converted OpenVINO model directory when `backend` is `"openvino"`. |
| `backend` | `"faster-whisper"` | `"faster-whisper"` or `"openvino"` — see `backends.py` / [ARCHITECTURE.md](ARCHITECTURE.md). |
| `device` | `"cpu"` | `faster-whisper`: `"cpu"` or `"cuda"`. `openvino`: `"CPU"`, `"GPU"`, or `"NPU"`. |
| `compute` | `"int8"` | `faster-whisper` compute type (`int8`, `int8_float16`, `float16`, `float32`). Ignored by the `openvino` backend (precision is fixed at model-conversion time). |
| `cleanup` | `"light"` | Post-processing mode: `"off"`, `"light"` (strip filler words/repeats), `"strong"` (also strips hedging phrases). See `sttlocal.clean_transcript`. |
| `bubble_position` | `"bottom"` | Floating listening-pill placement: `"bottom"` or `"top"`. |
| `hotkey` | `"<ctrl>+<space>"` | Global hotkey in `pynput` format. Set indirectly via `hotkey_display` + `config.hotkey_to_pynput()` — don't hand-edit this one. |
| `hotkey_display` | `"Ctrl + Espace"` | Human-readable hotkey shown in the UI. |
| `autopaste` | `true` | Paste the transcript into the active app automatically; if `false`, it's copied to the clipboard instead. |
| `autostart` | `false` | Launch Plume when Windows starts (writes/removes a `HKCU\...\Run` registry value — packaged builds only, see `set_autostart()` in `plume.py`). |
| `metrics` | `true` | Whether real dictations are logged to `metrics.csv` (see [BENCHMARKING.md](BENCHMARKING.md)). |
| `push_to_talk` | `false` | `false`: press the hotkey to start, press again to stop (default). `true`: hold the hotkey to record, release to stop. Both modes are served by the same `HotkeyEngine` in `plume.py`, a raw press/release listener (edge-triggered, so OS key-repeat can't double-fire it) rather than `pynput.GlobalHotKeys`. |
| `sound_feedback` | `true` | Short, distinct start/stop beep (`winsound.Beep`, played on its own thread, falling back to `MessageBeep`). Independent of the listening bubble window, so it still gives feedback if that window fails to render. |
| `vocabulary` | `[]` | List of `{"from": str, "to": str}` — see below. |
| `history` | `[]` | Last ~12 local dictations (`{"text": str, "timestamp": iso8601}`), most recent first. Never leaves the machine; shown in the "Dictée" tab. |

The UI's "profile" dropdown (Rapide/NPU/iGPU/OpenVINO-CPU) is a convenience
that writes `backend` + `device` together — see `PROFILES` in `plume.py`. It
is not stored as its own key.

## Vocabulary / correction dictionary

Managed by `vocabulary.Vocabulary`, persisted as the `vocabulary` config key.
Each entry is:

```json
{"from": "kubernét", "to": "Kubernetes"}
```

- `to` is required; `from` is optional.
- If `from` is set: every future transcript has that exact (case-insensitive,
  whole-word) string replaced by `to`. Use this for known mis-hearings.
- The set of all `to` terms is also fed to the engine as `hotwords` /
  `initial_prompt` on every transcription, biasing recognition toward
  spelling them correctly in the first place — so adding a term with `from`
  left blank still helps even before any mis-hearing has been observed.
- Casing of known `to` terms is normalized in the output even when no
  explicit `from` match fired (e.g. "kubernetes" -> "Kubernetes").

## Hotkey format

Two representations are kept in sync:

- `hotkey_display` — what the UI shows and what the "click then press keys"
  capture flow in `index.html` produces (e.g. `"Ctrl + Espace"`, `"F9"`,
  `"Ctrl + Maj + D"`).
- `hotkey` — the same combination in `pynput`'s `GlobalHotKeys` format (e.g.
  `"<ctrl>+<space>"`), computed from `hotkey_display` by
  `config.hotkey_to_pynput()`.

Only set `hotkey_display` from the UI (via `Api.set_hotkey`); `plume.py`
derives and persists `hotkey` from it and reinstalls the global listener.
