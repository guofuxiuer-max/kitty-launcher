#!/usr/bin/env bash
# 启动 KittyLauncher
#
#   ./run.sh                  启动图形界面（带闪屏）
#   ./run.sh --no-splash      跳过闪屏
#   ./run.sh --env            打印环境自检（贴 issue 用）
#   ./run.sh --screenshot DIR 无头渲染页面截图
set -euo pipefail
cd "$(dirname "$0")"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "KittyLauncher 只支持 macOS（当前：$(uname -s)）。Windows / Linux 不做适配。" >&2
  exit 1
fi

# 1) 优先用 setup.sh 建好的虚拟环境
if [ -x .venv/bin/python ] && .venv/bin/python -c "import PySide6, minecraft_launcher_lib" >/dev/null 2>&1; then
  PY="$PWD/.venv/bin/python"

# 2) 开发者本地可能把依赖放 vendor/ 里（仓库默认不带，.gitignore 已忽略）
elif [ -n "${KITTY_VENDOR:-}" ] && [ -d "${KITTY_VENDOR}" ]; then
  export PYTHONPATH="${KITTY_VENDOR}:${PYTHONPATH:-}"
  PY="${KITTY_PYTHON:-python3}"

# 3) 系统解释器：必须 >= 3.10
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

case " $* " in
  *" --env "*)
    exec "$PY" -m kitty.env_report
    ;;
esac

exec "$PY" -m kitty.main "$@"
