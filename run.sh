#!/usr/bin/env bash
# 启动 KittyLauncher。
# 优先用 .venv；没有就用内置 python + vendor（开发者本地环境）
set -euo pipefail
cd "$(dirname "$0")"

if [ -x .venv/bin/python ]; then
  exec ./.venv/bin/python -m kitty.main "$@"
fi

PY="${KITTY_PYTHON:-/Applications/DSH Desktop.app/Contents/Resources/office-runtime/primary-runtime/dependencies/python/bin/python3}"
[ -x "$PY" ] || PY="$(command -v python3)"
export PYTHONPATH="$PWD/vendor:${PYTHONPATH:-}"
exec "$PY" -m kitty.main "$@"
