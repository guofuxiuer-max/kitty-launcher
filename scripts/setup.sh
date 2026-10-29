#!/usr/bin/env bash
# 建虚拟环境并装 Python 依赖。
#
# 它只负责「Python 这一侧」：
#   下载 PySide6-Essentials + minecraft-launcher-lib + requests（约 115 MB，展开约 365 MB）
# 它【不】负责：
#   Java —— 装游戏版本时由启动器自动下 Mojang 官方 JRE（data/minecraft/runtime/）
#   Minecraft 本体 —— 第一次在启动器里建实例时才下，约 800 MB
#
# 用法：
#   ./scripts/setup.sh            交互式
#   ./scripts/setup.sh --yes      缺 Python 时别问，直接 brew 装
#   PIP_INDEX_URL=... ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

INDEX="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
VENV_DIR=".venv"
ASSUME_YES=0
for a in "$@"; do
  if [ "$a" = "--yes" ] || [ "$a" = "-y" ]; then
    ASSUME_YES=1
  fi
done

echo "==> 将要下载：PySide6-Essentials / minecraft-launcher-lib / requests（约 115 MB）"
echo "    不会下 Java 和 Minecraft 本体：Java 在装版本时自动装 Mojang 官方 JRE，本体按需下载"

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
  echo
  echo "⚠️  没找到 Python >= 3.10（当前 python3 是：$(python3 -V 2>&1 || echo 未安装)）"
  if command -v brew >/dev/null 2>&1; then
    answer="y"
    if [ "$ASSUME_YES" -eq 0 ] && [ -t 0 ]; then
      read -r -p "要我用 Homebrew 装一个 python@3.13 吗？[Y/n] " answer || answer="y"
      answer="${answer:-y}"
    fi
    case "$answer" in
      [Yy]*)
        echo "==> brew install python@3.13（约 40 MB，几分钟）"
        brew install python@3.13
        hash -r
        PY="$(pick_python || true)"
        ;;
    esac
  fi
fi

if [ -z "$PY" ]; then
  cat >&2 <<'EOF'

============================================================
需要 Python >= 3.10，但没找到，也没有可用的 Homebrew。三选一：

  1) 装 Homebrew 后再跑本脚本：
       /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  2) 官网安装包（最简单）：
       https://www.python.org/downloads/macos/

  3) 已经有 Python，只是不在 PATH 里：
       PYTHON=/path/to/python3.12 ./scripts/setup.sh

============================================================
EOF
  exit 1
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
  echo "==> 创建虚拟环境 .venv"
  if ! "$PY" -m venv "$VENV_DIR" >/dev/null 2>&1; then
    echo "==> 该解释器没带 ensurepip，改用无 pip 方式创建 + 手动补 pip"
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
echo "==> .venv 体积：$(du -sh .venv | cut -f1)"
echo
echo "装好了。启动：./run.sh"
echo "只看环境：./run.sh --env"
