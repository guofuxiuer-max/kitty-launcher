#!/usr/bin/env bash
# 启动 KittyLauncher
# 1) .venv 依赖齐 → 用它
# 2) 否则用内置 python + vendor（开发者本机环境）
# 3) 都没有 → 要求系统 python >= 3.10
#
# 特殊参数：
#   ./run.sh --env            打印环境自检（贴 issue 用）
#   ./run.sh --screenshot DIR 无头渲染五个页面截图
set -euo pipefail
cd "$(dirname "$0")"

BUILTIN="/Applications/DSH Desktop.app/Contents/Resources/office-runtime/primary-runtime/dependencies/python/bin/python3"
PY=""
VENDOR_PATH=""

if [ -x .venv/bin/python ] && .venv/bin/python -c "import PySide6, minecraft_launcher_lib" >/dev/null 2>&1; then
  PY="$PWD/.venv/bin/python"
elif [ -x "$BUILTIN" ] && [ -d vendor/PySide6 ]; then
  PY="$BUILTIN"
  VENDOR_PATH="$PWD/vendor"
else
  PY="${KITTY_PYTHON:-python3}"
  "$PY" - <<'CHK'
import sys
if sys.version_info < (3, 10):
    sys.exit(
        f"需要 Python 3.10+，当前是 {sys.version.split()[0]}。\n"
        "先跑 ./scripts/setup.sh（它会自动挑 3.10+ 的解释器）"
    )
CHK
fi

if [ -n "$VENDOR_PATH" ]; then
  export PYTHONPATH="$VENDOR_PATH:${PYTHONPATH:-}"
fi

case " $* " in
  *" --env "*)
    exec "$PY" -m kitty.env_report
    ;;
esac

exec "$PY" -m kitty.main "$@"
