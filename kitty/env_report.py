"""环境自检：一行看全 Python / Qt / Java / 目录 / 权限。

三种用法：
    python -m kitty.env_report          # 终端打印
    ./run.sh --env                      # 同上（run.sh 会挑对解释器）
    设置页「环境自检」卡片 → 复制     # 贴 issue 用

这个模块刻意不 import PySide6，这样即使 Qt 装坏了也能跑出报告。
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from .paths import VERSION  # 版本号唯一来源
MIN_PY = (3, 10)


def _visual_len(text: str) -> int:
    """中文按 2 个字符宽算，让终端里对齐得好看点。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _visual_len(text))


def _module_version(mod_name: str, attr: str = "__version__") -> str:
    try:
        import importlib.metadata as meta

        return meta.version(mod_name)
    except Exception:
        pass
    try:
        mod = __import__(mod_name.replace("-", "_"))
        return str(getattr(mod, attr, "?"))
    except Exception:
        return "未安装"


def collect() -> dict:
    info: dict = {
        "launcher": VERSION,
        "python": platform.python_version(),
        "python_impl": platform.python_implementation(),
        "python_path": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "venv": sys.prefix != sys.base_prefix,
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "qt": "未安装",
        "mll": _module_version("minecraft-launcher-lib"),
        "requests": _module_version("requests"),
        "java": [],
        "data_dir": "",
        "game_dir": "",
        "instances": [],
        "disk_free_gb": 0.0,
        "core_ok": False,
    }

    try:
        from PySide6 import __version__ as pyside_ver
        from PySide6.QtCore import qVersion

        info["qt"] = f"PySide6 {pyside_ver} / Qt {qVersion()}"
    except Exception as exc:  # noqa: BLE001
        info["qt"] = f"未安装（{type(exc).__name__}）"

    try:
        from kitty import auth

        st = auth.status()
        info["account"] = (
            f"微软 {st['name']}" if st.get("loggedIn") else "离线（未登录正版）"
        )
    except Exception:
        info["account"] = "未知"

    try:
        from kitty import core

        info["core_ok"] = True
        info["data_dir"] = str(core.DATA)
        info["game_dir"] = str(core.MC_DIR)
        info["java"] = [
            {"path": j["path"], "label": f"Java {j['major']} · {j['vendor']} · {j['version']}"}
            for j in core.list_java()
        ]
        info["instances"] = [i["name"] for i in core.load_instances()]
        try:
            info["disk_free_gb"] = round(shutil.disk_usage(core.DATA).free / 1024 ** 3, 1)
            info["data_writable"] = os.access(core.DATA, os.W_OK)
        except Exception:
            info["data_writable"] = False
    except Exception as exc:  # noqa: BLE001
        info["core_error"] = f"{type(exc).__name__}: {exc}"
        info["data_writable"] = False

    return info


def checks(info: dict) -> list[tuple[str, str, str]]:
    """返回 [(等级, 项目, 说明)]，等级 ✅ / ⚠️ / ❌。"""
    out: list[tuple[str, str, str]] = []

    py = tuple(int(x) for x in info["python"].split(".")[:2])
    if py >= MIN_PY:
        out.append(("✅", "Python", f"{info['python']} ≥ 3.10"))
    else:
        out.append(("❌", "Python", f"{info['python']} 太老，需要 3.10+（跑 ./scripts/setup.sh）"))

    if info["qt"].startswith("PySide6"):
        out.append(("✅", "Qt", info["qt"]))
    else:
        out.append(("❌", "Qt", "PySide6 未装好，界面起不来"))

    if info["mll"] == "未安装":
        out.append(("❌", "启动器底层", "minecraft-launcher-lib 缺失"))
    else:
        out.append(("✅", "启动器底层", f"minecraft-launcher-lib {info['mll']}"))

    # Java：只要有一个 >= 8 就能启动老版本，>= 21 才吃得下现代版本
    majors = []
    for j in info["java"]:
        try:
            majors.append(int(j["label"].split()[1]))
        except Exception:
            pass
    if not majors:
        out.append(("❌", "Java", "没找到任何 java，游戏起不来（去设置页手动指路径）"))
    elif max(majors) >= 21:
        out.append(("✅", "Java", f"找到 {len(majors)} 个，最高 {max(majors)}"))
    else:
        out.append(("⚠️", "Java", f"找到 {len(majors)} 个，但最高只有 {max(majors)}，现代版本需要 21+"))

    if info["os"].startswith("Darwin"):
        out.append(("✅", "系统", "macOS"))
    else:
        out.append(("❌", "系统", f"{info['os']} —— 本项目只支持 macOS"))

    if info.get("core_ok"):
        if info.get("data_writable"):
            out.append(("✅", "数据目录", f"{info['data_dir']}（可写，剩余 {info['disk_free_gb']} GB）"))
        else:
            out.append(("❌", "数据目录", f"{info['data_dir']} 不可写，换个位置（KITTY_DATA）"))
    else:
        out.append(("❌", "启动器内核", info.get("core_error", "导入失败")))

    return out


def render(info: dict | None = None, color: bool = False) -> str:
    info = info or collect()
    rows = [
        ("启动器", f"KittyLauncher {info['launcher']}"),
        ("运行方式", "打包 app" if info["frozen"] else ("源码 + .venv" if info["venv"] else "源码")),
        ("Python", f"{info['python']} ({info['python_impl']})"),
        ("解释器", info["python_path"]),
        ("Qt", info["qt"]),
        ("启动器底层", f"minecraft-launcher-lib {info['mll']}"),
        ("requests", info["requests"]),
        ("系统", f"{info['os']} / {info['arch']}"),
        ("数据目录", info["data_dir"] or "（未初始化）"),
        ("游戏目录", info["game_dir"] or "（未初始化）"),
        ("Java", "；".join(j["label"] for j in info["java"]) or "未找到"),
        ("账号", info.get("account", "未知")),
        ("实例", f"{len(info['instances'])} 个" + (f"：{', '.join(info['instances'])}" if info["instances"] else "")),
    ]
    width = max(_visual_len(k) for k, _ in rows) + 2
    lines = [f"KittyLauncher {info['launcher']} 环境自检", "─" * 52]
    for k, v in rows:
        lines.append(f"{_pad(k, width)}: {v}")
    lines.append("─" * 52)
    for level, item, note in checks(info):
        lines.append(f"{level} {_pad(item, width)}: {note}")

    bad = [c for c in checks(info) if c[0] == "❌"]
    lines.append("─" * 52)
    lines.append("结论: " + ("一切正常，可以开玩喵～" if not bad else f"有 {len(bad)} 项不满足，看上面 ❌"))
    return "\n".join(lines)


def summary_line(info: dict | None = None) -> str:
    """给日志页用的一行摘要。"""
    info = info or collect()
    bad = [c for c in checks(info) if c[0] == "❌"]
    java = max((int(j["label"].split()[1]) for j in info["java"]), default=0)
    return (
        f"[环境] Python {info['python']} · {info['qt']} · Java≤{java} · "
        f"实例 {len(info['instances'])} · " + ("✅ 正常" if not bad else f"❌ {len(bad)} 项异常")
    )


if __name__ == "__main__":
    print(render())
