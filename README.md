# Plume

Windows-first MVP for local voice dictation.

> **Just want to test it?** See [GUIDE_TEST.md](GUIDE_TEST.md) (français) — how to get the installer, run it, and report back.

Goal:

- press a global hotkey;
- speak;
- transcribe locally with Whisper;
- paste the text into the active app, such as Notepad;
- keep audio local.

This is not polished software. It is a benchmarkable MVP for testing latency and quality on Windows PCs.

## Documentation

| Doc | What's in it |
|---|---|
| [GUIDE_TEST.md](GUIDE_TEST.md) | (français) Get the installer, run it, report back — the doc for a non-dev tester. |
| [TESTING_WINDOWS.md](TESTING_WINDOWS.md) | Full manual test procedure for the console/tray apps and model comparison. |
| [APP_WINDOWS.md](APP_WINDOWS.md) | What the legacy Tk tray app (`tray_app.py`) does and how to run it. |
| [INSTALLER_WINDOWS.md](INSTALLER_WINDOWS.md) | How the Windows installer is built (PyInstaller + Inno Setup) and what it produces. |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Code map: modules, the UI<->Python bridge, packaging, where data lives. |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | `config.json` schema, vocabulary/correction-dictionary format, hotkey format. |
| [docs/BENCHMARKING.md](docs/BENCHMARKING.md) | The three ways to measure speed/quality: in-app Bench tab, CLI `benchmark.py`, real-usage `perflog.py`. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, coding conventions, how to cut a release. |
| [CHANGELOG.md](CHANGELOG.md) | Version history. |

## V2 Windows App

The desktop test app is:

```powershell
python tray_app.py --model small --language fr
```

The legacy tray test app provides:

- a small Windows window;
- a tray icon when supported;
- global `F9` start/stop;
- model selection;
- local transcription;
- light cleanup for hesitations/repeated words;
- final paste into the active app.

Read:

```text
APP_WINDOWS.md
```

Optional live preview:

```powershell
python tray_app.py --model small --language fr --live-preview
```

The current product UI is:

```powershell
python plume.py
```

It adds the glass UI, voice-reactive bubble, configurable hotkey, local history,
spoken punctuation commands, correction dictionary, and advanced CPU/iGPU/NPU
profiles.

## Windows Installer

Build notes:

```text
INSTALLER_WINDOWS.md
```

The intended user-facing installer is:

```text
Plume-Setup-0.4.16.exe
```

## Quick Start On Windows

Full test procedure:

```text
TESTING_WINDOWS.md
```

Install Python 3.11 or 3.12 if needed.

```powershell
git clone <your-private-repo-url>
cd local-whisper-dictation
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python dictate.py --model small --language fr
```

If Python 3.12 is not installed, try:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python dictate.py --model small --language fr
```

## Usage

1. Start the script.
2. Open Notepad.
3. Press `F9` to start recording.
4. Speak.
5. Press `F9` again to stop.
6. The transcript is copied to the clipboard and pasted into the active app.

Quit with `Esc`.

## Models To Test

Recommended order:

```powershell
python dictate.py --model base --language fr
python dictate.py --model small --language fr
python dictate.py --model medium --language fr
python dictate.py --model turbo --language fr
```

Use `base` first to validate the chain. `small` is likely the first serious candidate. `medium` and `turbo` are quality candidates if latency is acceptable.

## Benchmark Existing Audio Files

Put `.wav`, `.mp3`, or `.m4a` files in `samples/`, then sweep backends, devices,
and models. This is how you decide NPU vs iGPU vs CPU on your real machine.

```powershell
# CPU baseline across models
python benchmark.py --backends faster-whisper --devices cpu --models base small medium turbo --language fr

# OpenVINO targets (after converting a model, see "OpenVINO / NPU")
python benchmark.py --backends openvino --devices CPU GPU NPU --models models\openvino\whisper-small --language fr
```

Results (latency + real-time factor RTF) are written to `benchmark-results/results.csv`.
Keep a few short clips in `samples/` too: for dictation, low absolute latency on
short utterances matters more than RTF on long files.

## Performance Over Time

Every real dictation from the app also logs a row to `metrics.csv` in the
per-user config dir (`%APPDATA%\Plume\metrics.csv` on Windows), as long as the
"metrics" setting is on (default). Summarize that history instead of relying
on a single one-off benchmark:

```powershell
python perflog.py --summary
python perflog.py --tail 20
```

This is how CPU vs NPU vs iGPU and model-size choices get validated against
actual day-to-day usage on the target machine, not just a lab run.

## Engine Backends

The STT engine is pluggable. Pick it with `--backend`:

- `faster-whisper` (default): CTranslate2, **CPU** int8. The reliable baseline. Cannot use the Intel NPU or iGPU.
- `openvino`: Intel OpenVINO GenAI. Targets **CPU / GPU (Arc iGPU) / NPU (AI Boost)** via `--device CPU|GPU|NPU`.

```powershell
python dictate.py --backend faster-whisper --device cpu --model small --language fr
python dictate.py --backend openvino --device GPU --model models\openvino\whisper-small --language fr
python dictate.py --backend openvino --device NPU --model models\openvino\whisper-small --language fr
```

## OpenVINO / NPU

Only needed to use the Intel iGPU or NPU. Do this **on the target Intel machine**.

1. Install the optional deps:

```powershell
python -m pip install -r requirements-openvino.txt
```

2. Convert a Whisper model to the OpenVINO IR format once (the pipeline needs a
   directory, not a Hugging Face name):

```powershell
optimum-cli export openvino --model openai/whisper-small --weight-format int8 models\openvino\whisper-small
```

3. Point `--model` at that directory and choose the device:

```powershell
python dictate.py --backend openvino --device NPU --model models\openvino\whisper-small --language fr
```

Reality check: on Core Ultra parts the **Arc iGPU (`GPU`) is often the fastest**
target for Whisper. The **NPU** trades some speed for low power, low heat, and a
free CPU. Don't assume NPU is fastest — measure with `benchmark.py` (below) on
your actual PC, then decide.

**NPU currently fails with `Port for tensor name cache_position was not
found`** on export produced by the versions in `requirements-openvino.txt`
(confirmed on real Core Ultra hardware, 2026-08). This is an unresolved
version conflict between `optimum-intel` (needs `transformers>=4.57` to
export at all) and the installed `openvino-genai` NPU static pipeline
(doesn't accept that export's shape). Older `transformers` pins don't help —
`optimum-intel`'s export refuses to run below 4.57. **Use `--device GPU` or
`CPU`** until a compatible version combination is found; both are unaffected
and GPU (Arc iGPU) has measured ~2-3x the throughput of CPU with comparable
quality on this project's own benchmarks.

## Privacy Positioning

The MVP uses local inference. It does not call an API for transcription.

Important caveat: the first run may download the selected model from Hugging Face through `faster-whisper`. For an enterprise/offline version, models should be pre-bundled or installed once from an approved internal package.

## Notes

- CPU (`faster-whisper`) is the reliable baseline and default.
- Intel iGPU/NPU are available through the `openvino` backend — benchmark them per machine before committing (see "OpenVINO / NPU").
- The MVP uses clipboard paste for compatibility. A later product can use deeper Windows text injection if needed.
