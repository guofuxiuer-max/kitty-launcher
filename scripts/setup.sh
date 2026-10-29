#!/usr/bin/env bash
# 建虚拟环境并装依赖（国内默认走清华镜像）
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
MIRROR="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

[ -d .venv ] || "$PY" -m venv .venv
./.venv/bin/python -m pip install --upgrade pip -i "$MIRROR"
./.venv/bin/pip install -r requirements.txt -i "$MIRROR"
echo
echo "装好了。启动：./run.sh"
