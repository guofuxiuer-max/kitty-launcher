# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置（macOS .app）：pyinstaller --noconfirm kitty_launcher.spec
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/logo.png", "assets")],
    hiddenimports=collect_submodules("minecraft_launcher_lib") + ["requests", "certifi"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetworkAuth"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KittyLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="KittyLauncher",
)

app = BUNDLE(
    coll,
    name="KittyLauncher.app",
    icon="assets/logo.icns",
    bundle_identifier="io.github.kittylauncher",
    info_plist={
        "CFBundleName": "KittyLauncher",
        "CFBundleDisplayName": "KittyLauncher",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
)
