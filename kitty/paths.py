"""路径与目录约定（core 和 auth 共用，避免循环 import）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_root() -> Path:
    """数据目录：开发时用仓库里的 data/，打包成 .app 后用 ~/Library/Application Support。"""
    env = os.environ.get("KITTY_DATA")
    if env:
        return Path(env).expanduser()
    if getattr(sys, "frozen", False):
        return Path.home() / "Library" / "Application Support" / "KittyLauncher"
    return Path(__file__).resolve().parent.parent / "data"


IS_MACOS = sys.platform == "darwin"


APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
DATA = data_root()
MC_DIR = DATA / "minecraft"
INSTANCES_DIR = DATA / "instances"
LOGS_DIR = DATA / "logs"
CONFIG_PATH = DATA / "config.json"
INSTANCES_JSON = DATA / "instances.json"
ACCOUNTS_PATH = DATA / "accounts.json"

for _d in (DATA, MC_DIR, INSTANCES_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


VERSION = "0.9.0"


def asset_path(name: str):
    """assets/ 里的资源，兼容源码运行与 PyInstaller 打包。"""
    import sys

    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / name)
    candidates.append(APP_DIR.parent / "assets" / name)
    for c in candidates:
        if c.exists():
            return c
    return None
