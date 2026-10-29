#!/usr/bin/env bash
# 启动 KittyLauncher
# 1) 有 .venv 且依赖齐 → 用它
# 2) 否则尝试内置 python + vendor（开发者本机环境）
# 3) 都不行 → 提示先跑 ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")"

check_deps() {
  "$1" -c "import PySide6, minecraft_launcher_lib" >/dev/null 2>&1
}

if [ -x .venv/bin/python ]; then
  if check_deps .venv/bin/python; then
    exec ./.venv/bin/python -m kitty.main "$@"
  fi
  echo "⚠️  .venv 里缺依赖（可能装的时候 Python 版本不对）。跑一下 ./scripts/setup.sh 修复。"
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
    sys.exit(
        f"需要 Python 3.10+，当前是 {sys.version.split()[0]}。\n"
        "先跑 ./scripts/setup.sh（它会自动挑 3.10+ 的解释器）"
    )
CHK
exec "$PY" -m kitty.main "$@"
