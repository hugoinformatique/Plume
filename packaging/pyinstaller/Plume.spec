# -*- mode: python ; coding: utf-8 -*-

import importlib.util
import os
import re

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
    VarStruct, VSVersionInfo,
)

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

# OpenVINO runtime (NPU / iGPU / OpenVINO-CPU profiles). Optional: a build
# without these packages installed simply ships without them, and the app
# refuses those profiles with an explanatory message instead of crashing.
# `optimum-intel` (the *conversion* tool) is deliberately NOT installed in the
# build environment -- it drags in torch, which PyInstaller would then try to
# bundle, for no runtime benefit. The model is converted in a separate
# environment during CI and copied in below.
#
# PLUME_REQUIRE_OPENVINO=1 (set by CI) turns "missing" into a build failure:
# collect_all() only *warns* for an absent package and returns empty lists, so
# without this a botched install would produce a green build and a released
# installer whose NPU/iGPU profiles are dead.
require_openvino = os.environ.get("PLUME_REQUIRE_OPENVINO") == "1"
for pkg in ("openvino", "openvino_genai", "openvino_tokenizers"):
    if importlib.util.find_spec(pkg) is None:
        if require_openvino:
            raise SystemExit(f"PLUME_REQUIRE_OPENVINO=1 but {pkg} is not installed")
        continue
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# A pre-converted Whisper model, so the OpenVINO profiles work out of the box
# instead of asking the user for an optimum-cli export.
ov_model = os.path.join(ROOT, "models", "openvino")
if os.path.isdir(ov_model):
    datas += [(ov_model, os.path.join("models", "openvino"))]
elif require_openvino:
    raise SystemExit(f"PLUME_REQUIRE_OPENVINO=1 but no converted model in {ov_model}")

# Bundle the web UI.
datas += [(os.path.join(ROOT, "ui"), "ui")]

png_path = os.path.join(ROOT, "assets", "plume.png")
if os.path.exists(png_path):
    datas += [(png_path, "assets")]

ico_path = os.path.join(ROOT, "assets", "plume.ico")
icon = ico_path if os.path.exists(ico_path) else None

# Windows version resource. An executable with no publisher/version metadata is
# one of the cheapest heuristics an antivirus or SmartScreen has for "suspicious
# unsigned binary", and it is also the first thing a security reviewer looks at
# in the file properties. Read the version from plume.py so there is a single
# source of truth.
with open(os.path.join(ROOT, "plume.py"), encoding="utf-8") as fh:
    _m = re.search(r'^APP_VERSION = "([\d.]+)"', fh.read(), re.M)
if _m is None:
    raise SystemExit("could not read APP_VERSION from plume.py")
APP_VERSION = _m.group(1)
_vparts = tuple(int(x) for x in (APP_VERSION.split(".") + ["0", "0", "0"])[:4])

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_vparts, prodvers=_vparts, mask=0x3F, flags=0x0,
                      OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040C04B0", [
            StringStruct("CompanyName", "Hugo Informatique"),
            StringStruct("FileDescription", "Plume — dictée vocale locale"),
            StringStruct("FileVersion", APP_VERSION),
            StringStruct("InternalName", "Plume"),
            StringStruct("LegalCopyright", "© Hugo Informatique — MIT"),
            StringStruct("OriginalFilename", "Plume.exe"),
            StringStruct("ProductName", "Plume"),
            StringStruct("ProductVersion", APP_VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x040C, 1200])]),
    ],
)


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
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
    version=version_info,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Plume",
)
