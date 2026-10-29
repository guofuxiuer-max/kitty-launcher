#!/usr/bin/env bash
# 建虚拟环境并装依赖。
#
# 注意：minecraft-launcher-lib 8.x 需要 Python >= 3.10，PySide6 6.x 也要 3.10+。
# macOS 系统自带的是 3.9，所以这里会主动去找 3.10+ 的解释器；
# 如果只有没带 ensurepip 的 3.12，就手动塞一个 pip 进去。
set -euo pipefail
cd "$(dirname "$0")/.."

INDEX="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
VENV_DIR=".venv"

fail() {
  cat >&2 <<'EOF'

============================================================
需要一个 Python >= 3.10（macOS 自带的 3.9 太老）。三选一：

  1) Homebrew 装一个（推荐）：
       brew install python@3.13
     然后重跑 ./scripts/setup.sh

  2) 官网安装包：
       https://www.python.org/downloads/macos/

  3) 手动指定解释器：
       PYTHON=/path/to/python3.12 ./scripts/setup.sh

============================================================
EOF
  exit 1
}

py_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

pick_python() {
  local cands=()
  [ -n "${PYTHON:-}" ] && cands+=("$PYTHON")
  cands+=(python3.14 python3.13 python3.12 python3.11 python3.10
          /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13
          /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11
          /usr/local/bin/python3.13 /usr/local/bin/python3.12
          python3)
  local bundled="/Applications/DSH Desktop.app/Contents/Resources/office-runtime/primary-runtime/dependencies/python/bin/python3"
  [ -x "$bundled" ] && cands+=("$bundled")

  local c
  for c in "${cands[@]}"; do
    if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then
      if py_ok "$c"; then
        echo "$c"
        return 0
      fi
    fi
  done
  return 1
}

PY="$(pick_python || true)"
if [ -z "$PY" ]; then
  echo "当前 python3 是：$(python3 -V 2>&1 || echo 未安装)"
  fail
fi
echo "==> 使用解释器：$PY  ($("$PY" -V 2>&1))"

# 旧 venv 版本不对 / 坏了就重建
if [ -d "$VENV_DIR" ]; then
  if ! "$VENV_DIR/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    echo "==> 已有 .venv 的 Python 版本不对，删掉重建"
    rm -rf "$VENV_DIR"
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "==> 创建虚拟环境"
  if ! "$PY" -m venv "$VENV_DIR" >/dev/null 2>&1; then
    echo "==> 该解释器没有 ensurepip，改用无 pip 方式创建并手动补 pip"
    rm -rf "$VENV_DIR"
    "$PY" -m venv --without-pip "$VENV_DIR"
    SITE="$("$VENV_DIR/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    "$PY" scripts/_bootstrap_pip.py "$INDEX" "$SITE"
  fi
fi

VPY="$VENV_DIR/bin/python"
echo "==> venv: $("$VPY" -V 2>&1)"

if ! "$VPY" -m pip --version >/dev/null 2>&1; then
  echo "==> 补装 pip"
  SITE="$("$VPY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  "$PY" scripts/_bootstrap_pip.py "$INDEX" "$SITE"
fi

echo "==> 安装依赖，镜像: ${INDEX}"
"$VPY" -m pip install --upgrade pip -i "$INDEX" -q
"$VPY" -m pip install -r requirements.txt -i "$INDEX"

echo
echo "==> 自检"
"$VPY" - <<'EOF'
import minecraft_launcher_lib as m, PySide6, requests
print("minecraft-launcher-lib", getattr(m, "__version__", "?"))
print("PySide6", PySide6.__version__)
print("requests", requests.__version__)
EOF
echo
echo "装好了。启动：./run.sh"
