#!/usr/bin/env bash
# 启动 KittyLauncher
# 1) 有 .venv 就用 .venv
# 2) 否则用内置 python + vendor（开发者本机环境）
# 3) 都没有就要求 python3 >= 3.10
set -euo pipefail
cd "$(dirname "$0")"

if [ -x .venv/bin/python ]; then
  exec ./.venv/bin/python -m kitty.main "$@"
fi

BUILTIN="/Applications/DSH Desktop.app/Contents/Resources/office-runtime/primary-runtime/dependencies/python/bin/python3"
if [ -x "$BUILTIN" ] && [ -d vendor/PySide6 ]; then
  export PYTHONPATH="$PWD/vendor:${PYTHONPATH:-}"
  exec "$BUILTIN" -m kitty.main "$@"
fi

PY="${KITTY_PYTHON:-python3}"
"$PY" - <<'CHK'
import sys
if sys.version_info < (3, 10):
    sys.exit("需要 Python 3.10+，当前是 %s。先跑 ./scripts/setup.sh 或装个新 Python。" % sys.version.split()[0])
CHK
exec "$PY" -m kitty.main "$@"
