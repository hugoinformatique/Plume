# STTLocal Windows App

This is the V2 test app. It is still intentionally rough, but it behaves more like a Windows desktop tool than the first console-only script.

## What It Does

- Opens a small Windows desktop window.
- Adds a tray icon when `pystray` is available.
- Uses `F9` globally to start and stop recording.
- Lets you choose the model before testing: `base`, `small`, `medium`, `turbo`.
- Transcribes locally with `faster-whisper`.
- Cleans common hesitations and repeated words.
- Copies the final text to the clipboard and pastes it into the active app.
- Optionally shows a live preview inside the STTLocal window while you speak.

The final paste still happens after you stop recording. This is deliberate for the test version: Whisper often improves punctuation and wording once it has the full sentence.

## Install

Simple install:

```powershell
.\install_windows.ps1
```

Manual install:

```powershell
cd $env:USERPROFILE\Downloads
git clone https://github.com/hugoinformatique/STTLocal.git
cd STTLocal
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If the repo is already cloned:

```powershell
cd $env:USERPROFILE\Downloads\STTLocal
git pull
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Launch The App

Simple launch after install:

```powershell
.\run_tray_app.bat
```

Recommended first run:

```powershell
python tray_app.py --model base --language fr
```

Better quality test:

```powershell
python tray_app.py --model small --language fr
```

Higher quality candidates:

```powershell
python tray_app.py --model medium --language fr
python tray_app.py --model turbo --language fr
```

## Test Flow

1. Launch the app.
2. Open Notepad.
3. Click inside Notepad.
4. Press `F9`.
5. Speak naturally.
6. Press `F9` again.
7. Wait for transcription.
8. The text should paste into Notepad.

## Live Preview

To preview text inside the STTLocal window while recording:

```powershell
python tray_app.py --model small --language fr --live-preview
```

This preview is useful to see that the app is listening, but it is heavier because it transcribes snapshots while recording. For performance benchmarks, test once with it disabled and once enabled.

## Cleanup Modes

Default:

```powershell
python tray_app.py --cleanup light
```

Available modes:

- `off`: raw Whisper output.
- `light`: removes common hesitations and repeated words, keeps punctuation.
- `strong`: more aggressive cleanup for spoken notes.

Example:

```powershell
python tray_app.py --model small --language fr --cleanup strong
```

## What To Measure

For each model, note:

- first launch time;
- delay after pressing stop;
- transcription quality;
- punctuation quality;
- whether repeated words or hesitations are cleaned correctly;
- whether paste works in Notepad, Outlook, Teams, browser, and the target business app.

## Current Technical Position

This version targets CPU first because it is the most reliable Windows baseline. Intel GPU/OpenVINO and Intel AI Boost/NPU acceleration should be tested after the product loop is validated.
