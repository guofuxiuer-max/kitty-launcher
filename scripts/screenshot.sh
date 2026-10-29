#!/usr/bin/env bash
# 无头渲染五个页面截图，用于 README 与改 UI 后的回归对比
set -euo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python
[ -x "$PY" ] || PY=python3
QT_QPA_PLATFORM=offscreen "$PY" -m kitty.main --screenshot screenshots
