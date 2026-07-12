# Local Whisper Dictation MVP

Windows-first MVP for local voice dictation.

Goal:

- press a global hotkey;
- speak;
- transcribe locally with Whisper;
- paste the text into the active app, such as Notepad;
- keep audio local.

This is not polished software. It is a benchmarkable V1 for testing latency and quality on Windows PCs.

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
pip install -r requirements.txt
python dictate.py --model small --language fr
```

If Python 3.12 is not installed, try:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
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

Put `.wav`, `.mp3`, or `.m4a` files in `samples/`, then run:

```powershell
python benchmark.py --models base small medium turbo --language fr
```

Results are written to `benchmark-results/results.csv`.

## Privacy Positioning

The MVP uses local inference. It does not call an API for transcription.

Important caveat: the first run may download the selected model from Hugging Face through `faster-whisper`. For an enterprise/offline version, models should be pre-bundled or installed once from an approved internal package.

## Notes

- CPU is the first reliable target.
- Intel GPU/OpenVINO and NPU should be benchmarked separately after this V1 proves the product loop.
- The MVP uses clipboard paste for compatibility. A later product can use deeper Windows text injection if needed.
