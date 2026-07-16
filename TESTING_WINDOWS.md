# Windows Test Procedure

This document explains how to test the ugly MVP on a Windows PC.

Target test:

- run locally on Windows;
- select a Whisper model;
- press `F9`;
- speak in French;
- press `F9` again;
- verify that the text is pasted into Notepad.

## 1. Install Prerequisites

Install Python 3.12 for Windows:

https://www.python.org/downloads/windows/

During install, enable:

- `Add python.exe to PATH`
- `py launcher`

Then open PowerShell.

Check Python:

```powershell
py --version
```

Expected: Python 3.11 or 3.12. Prefer 3.12.

## 2. Clone The Repo

```powershell
cd $env:USERPROFILE\Downloads
git clone https://github.com/hugoinformatique/STTLocal.git
cd STTLocal
```

If Git is not installed:

https://git-scm.com/download/win

## 3. Create The Virtual Environment

Simple method:

```powershell
.\install_windows.ps1
```

Manual method:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If `py -3.12` fails, use:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 4. First Test In Notepad

Start with `base` to verify the chain:

```powershell
python dictate.py --model base --language fr
```

Then:

1. Open Notepad.
2. Click inside the blank document.
3. Press `F9`.
4. Speak for 5 to 10 seconds.
5. Press `F9` again.
6. Wait for transcription.
7. The text should paste into Notepad.

Press `Esc` to stop the script.

## 5. Test The Windows App

The V2 desktop app has a small window and a tray icon:

```powershell
python tray_app.py --model base --language fr
```

Then:

1. Open Notepad.
2. Click inside the blank document.
3. Press `F9`.
4. Speak for 5 to 10 seconds.
5. Press `F9` again.
6. Wait for transcription.
7. The text should paste into Notepad.

If `base` works, test:

```powershell
python tray_app.py --model small --language fr
```

Optional live preview inside the Plume window:

```powershell
python tray_app.py --model small --language fr --live-preview
```

Read `APP_WINDOWS.md` for the full app procedure.

## 6. Compare Models

Test in this order:

```powershell
python dictate.py --model base --language fr
python dictate.py --model small --language fr
python dictate.py --model medium --language fr
python dictate.py --model turbo --language fr
```

For each model, note:

- first startup time;
- transcription time after pressing `F9` the second time;
- text quality;
- whether punctuation is acceptable;
- whether accents and French words are correct;
- whether the PC fan gets loud.

Expected rough behavior:

- `base`: fastest, weaker quality;
- `small`: likely best first candidate;
- `medium`: better quality, slower;
- `turbo`: potentially strong, but must be validated on the HP.

Also compare the app mode:

```powershell
python tray_app.py --model base --language fr
python tray_app.py --model small --language fr
python tray_app.py --model medium --language fr
python tray_app.py --model turbo --language fr
```

## 7. Benchmark Audio Files

Create a `samples` folder and put test audio files in it:

```powershell
mkdir samples
```

Supported files:

- `.wav`
- `.mp3`
- `.m4a`
- `.flac`
- `.ogg`

Run:

```powershell
python benchmark.py --models base small medium turbo --language fr
```

Results:

```text
benchmark-results/results.csv
```

## 8. What To Report Back

For each model, send:

```text
PC model:
CPU:
RAM:
Windows version:
Model tested:
Startup time:
Recording length:
Transcription time:
Quality 1-10:
Text pasted correctly in Notepad: yes/no
Problems:
```

Example:

```text
PC model: HP ...
CPU: Intel Core Ultra 5 125U
RAM: 16 GB DDR5
Windows version: Windows 11 24H2
Model tested: small
Startup time: 18s
Recording length: 12s
Transcription time: 3.4s
Quality 1-10: 8
Text pasted correctly in Notepad: yes
Problems: first run downloaded model, fan audible
```

## 9. Troubleshooting

### PowerShell blocks activation

Run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then retry:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Microphone error

Check Windows microphone privacy settings:

```text
Settings > Privacy & security > Microphone
```

Allow microphone access for desktop apps.

### F9 does nothing

Click the PowerShell window once and retry. If another app intercepts `F9`, run:

```powershell
python dictate.py --model base --language fr
```

Then test again with Notepad focused.

### Paste does not happen

The transcription is still copied to the clipboard. Try manual `Ctrl+V`.

### First launch is slow

The first launch downloads the model. Later launches should be faster.

For a future enterprise/offline version, models should be bundled or installed from an internal package.

## 10. Current MVP Limits

- UI is intentionally rough.
- No installer.
- No NPU acceleration yet.
- Uses CPU through `faster-whisper`.
- Uses clipboard paste, not deep Windows text injection.
- First model download may require internet.
- Live preview is heavier than final-only transcription.

The goal of this MVP is to validate the product loop and choose the best model.
