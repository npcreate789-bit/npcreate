# PyInstaller spec for the NP Create Studio macOS .app bundle.
#
# Build with:    .venv/bin/pyinstaller --noconfirm build_macos_app.spec
# Output:        dist/NPCreateStudio.app
#
# Notes:
# - --windowed mode (BUNDLE) → real .app, no terminal window on launch
# - customtkinter ships its own assets (themes/fonts) which PyInstaller can't
#   find automatically; we vendor them via collect_data_files.
# - The 5 first-party data files (device_profiles, i18n) are explicit so the
#   bundle works without the source tree.
# - cryptography's Rust backend needs its dynamic library collected.
# - External streaming tools (ffmpeg/adb/scrcpy) are NOT bundled — the app
#   resolves them via shutil.which() at runtime (Phase G fallback).

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
PROJECT_ROOT = Path.cwd()
ENTRYPOINT = str(PROJECT_ROOT / "launcher_macos.py")

datas = []
datas += collect_data_files("customtkinter")
datas += [
    (str(PROJECT_ROOT / "src" / "npcreate_studio" / "data" / "device_profiles.json"),
     "npcreate_studio/data"),
    (str(PROJECT_ROOT / "src" / "npcreate_studio" / "ui" / "i18n"),
     "npcreate_studio/ui/i18n"),
]

hiddenimports = [
    "customtkinter",
    "PIL._tkinter_finder",
    "cryptography.hazmat.bindings._rust",
]
hiddenimports += collect_submodules("npcreate_studio")

a = Analysis(
    [ENTRYPOINT],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "pytest", "_pytest",          # test-only
        "ruff", "mypy", "bandit",      # dev tools
        "tkinter.test",                # large + unused
    ],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NPCreateStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,           # native arch (arm64 on M-series)
    codesign_identity=None,     # set to your Developer ID for distribution
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="NPCreateStudio",
)

# Mac .app bundle wraps the COLLECT directory.
app = BUNDLE(
    coll,
    name="NPCreateStudio.app",
    icon=None,                  # add a .icns once we have branded art
    bundle_identifier="com.npcreate.studio",
    info_plist={
        "CFBundleName": "NP Create Studio",
        "CFBundleDisplayName": "NP Create Studio",
        "CFBundleShortVersionString": "2.6.0",
        "CFBundleVersion": "2.6.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "NSAppleEventsUsageDescription": "NP Create Studio launches adb / ffmpeg / scrcpy on your behalf for live streaming.",
    },
)
