"""路径与目录约定（core 和 auth 共用，避免循环 import）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_root() -> Path:
    """数据目录：开发时用仓库里的 data/，打包成 app 后用系统用户目录。"""
    env = os.environ.get("KITTY_DATA")
    if env:
        return Path(env).expanduser()
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "KittyLauncher"
        if os.name == "nt":
            return Path(os.environ.get("APPDATA", Path.home())) / "KittyLauncher"
        return Path.home() / ".local" / "share" / "KittyLauncher"
    return Path(__file__).resolve().parent.parent / "data"


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
