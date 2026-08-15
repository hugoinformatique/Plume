# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import (
    collect_all, collect_data_files, collect_dynamic_libs, collect_submodules,
)

# Repo root, resolved from the spec location so the build works regardless of CWD.
ROOT = os.path.dirname(os.path.dirname(SPECPATH))

hiddenimports = (
    collect_submodules("faster_whisper")
    + collect_submodules("ctranslate2")
    + collect_submodules("pystray")
    + collect_submodules("PIL")
    + [
        "numpy",
        "pyperclip",
        "pynput",
        "sounddevice",
        "clr",
        # The floating bubble is a native Tk window: nothing imports tkinter at
        # module level (it is loaded lazily so the app still runs without it),
        # so PyInstaller would not bundle it on its own.
        "tkinter",
        # Local modules.
        "plume",
        "floating_bubble",
        "backends",
        "sttlocal",
        "ui_theme",
        "config",
        "vocabulary",
    ]
)

datas = collect_data_files("faster_whisper") + collect_data_files("ctranslate2")
binaries = collect_dynamic_libs("ctranslate2")

# pywebview (+ its Windows EdgeChromium backend via pythonnet/clr_loader).
for pkg in ("webview", "clr_loader"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Bundle the web UI.
datas += [(os.path.join(ROOT, "ui"), "ui")]

png_path = os.path.join(ROOT, "assets", "plume.png")
if os.path.exists(png_path):
    datas += [(png_path, "assets")]

ico_path = os.path.join(ROOT, "assets", "plume.ico")
icon = ico_path if os.path.exists(ico_path) else None


a = Analysis(
    [os.path.join(ROOT, "plume.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "tensorflow"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Plume",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Plume",
)
