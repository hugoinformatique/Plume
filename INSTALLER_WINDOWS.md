# Plume Installer

Goal: produce a Windows download that works for a normal user without installing Python manually.

## Product Name

The MVP product name is **Plume**.

Positioning:

> Local AI dictation for Windows. Your voice stays on your PC.

## Build Outputs

The Windows build produces two artifacts:

- `Plume-portable`: app folder containing `Plume.exe` and dependencies.
- `Plume-installer`: setup executable generated with Inno Setup.

The installer file name is:

```text
Plume-Setup-1.2.0.exe
```

## Build On GitHub

The repo includes a GitHub Actions workflow:

```text
.github/workflows/windows-installer.yml
```

It runs on Windows and builds:

1. Python dependencies, including the OpenVINO **runtime**
   (`requirements-openvino-runtime.txt`).
2. A Whisper `small` model converted to OpenVINO FP16 IR, in a throwaway
   virtualenv so that `optimum-intel` and torch never end up in the bundle.
3. PyInstaller app folder.
4. Inno Setup installer.
5. Downloadable GitHub Actions artifacts.

Since v0.4.25 the installer therefore carries the OpenVINO runtime and the
converted model, so the NPU / iGPU profiles work on a fresh machine with no
extra install and no conversion step. That is what makes the download large
(hundreds of MB rather than ~65 MB) — a deliberate trade for an app whose
whole point is running with nothing external.

## Build Manually On Windows

Install:

- Python 3.12
- Git
- Inno Setup 6

Then run:

```powershell
git clone https://github.com/hugoinformatique/Plume.git
cd Plume
.\scripts\build_windows.ps1
```

Outputs:

```text
dist\Plume\
dist\installer\Plume-Setup-1.2.0.exe
```

## User Install Flow

For a normal user:

1. Download `Plume-Setup-1.2.0.exe`.
2. Run the installer.
3. Launch `Plume`.
4. Choose a model.
5. Press `F9`, speak, press `F9` again.
6. Text is pasted into the active app.

## Important Caveat

This installer bundles the Python app and dependencies, but not the Whisper model files yet. On first model use, `faster-whisper` may download the selected model.

For an enterprise/offline version, the next packaging step is to bundle approved model files or ship a separate offline model pack.
