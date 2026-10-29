#!/usr/bin/env bash
# 用 PyInstaller 打成独立 app / exe
set -euo pipefail
cd "$(dirname "$0")/.."

[ -d .venv ] || ./scripts/setup.sh
./.venv/bin/pip install pyinstaller -i "${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
./.venv/bin/pyinstaller --noconfirm kitty_launcher.spec

echo
echo "产物："
ls -d dist/* 2>/dev/null
