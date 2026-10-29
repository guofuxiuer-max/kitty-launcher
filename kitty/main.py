"""KittyLauncher 主窗口与入口。

启动：python -m kitty.main
自检截图：python -m kitty.main --screenshot out/
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VENDOR = ROOT / "vendor"
# 只有当前解释器里没有 PySide6 时才用仓库自带的 vendor，
# 否则会把 vendor 里旧版 requests / mll 顶掉 venv 里装好的新版本。
try:  # noqa: SIM105
    import PySide6  # noqa: F401
except ImportError:
    if VENDOR.exists() and str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))

from PySide6.QtCore import Qt, QTimer, QSize  # noqa: E402
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor, QLinearGradient, QBrush  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from kitty import core  # noqa: E402
from kitty import env_report  # noqa: E402
from kitty import pages as pages_mod  # noqa: E402
from kitty import theme  # noqa: E402
from kitty.widgets import NavButton, Toast, elide  # noqa: E402


class App(QMainWindow):
    def __init__(self, dark: bool = True):
        super().__init__()
        self.setWindowTitle("KittyLauncher")
        self.resize(1200, 780)
        self.setMinimumSize(1000, 660)
        self.colors = theme.DARK if dark else theme.LIGHT
        self.log_seq = 0
        self.boot_data = core.bootstrap()
        self._last_job_state = None

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_rail())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        self.pages = pages_mod.build_pages(self)
        for key in ("launch", "download", "mods", "settings", "logs"):
            self.stack.addWidget(self.pages[key])
        right.addWidget(self.stack, 1)
        lay.addLayout(right, 1)

        self.toast_widget = Toast(root)
        self.apply_theme(dark)
        self.refresh_all()

        self.job_timer = QTimer(self)
        self.job_timer.timeout.connect(self.tick_job)
        self.job_timer.start(1200)
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.tick_logs)
        self.log_timer.start(900)

    # ---------------- 界面搭建
    def _build_rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("Rail")
        rail.setFixedWidth(96)
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(12, 16, 12, 14)
        lay.setSpacing(8)

        logo = QLabel("🐱")
        logo.setObjectName("Logo")
        logo.setFixedSize(46, 46)
        logo.setAlignment(Qt.AlignCenter)
        holder = QHBoxLayout()
        holder.addWidget(logo, 0, Qt.AlignHCenter)
        lay.addLayout(holder)
        lay.addSpacing(10)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for i, (key, icon, text) in enumerate((
            ("launch", "🚀", "启动"),
            ("download", "📥", "下载"),
            ("mods", "🧩", "模组"),
            ("settings", "⚙️", "设置"),
            ("logs", "📜", "日志"),
        )):
            btn = NavButton(icon, text)
            btn.setProperty("page", key)
            if i == 0:
                btn.setChecked(True)
            self.nav_group.addButton(btn)
            holder2 = QHBoxLayout()
            holder2.addWidget(btn, 0, Qt.AlignHCenter)
            lay.addLayout(holder2)
        self.nav_group.buttonClicked.connect(lambda b: self.go(b.property("page")))

        lay.addStretch(1)
        theme_btn = QPushButton("◐")
        theme_btn.setObjectName("Ghost")
        theme_btn.setFixedSize(34, 30)
        theme_btn.setToolTip("切换深浅主题")
        theme_btn.setCursor(Qt.PointingHandCursor)
        theme_btn.clicked.connect(self.toggle_theme)
        h = QHBoxLayout()
        h.addWidget(theme_btn, 0, Qt.AlignHCenter)
        lay.addLayout(h)
        self.theme_btn = theme_btn
        return rail

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(54)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(22, 0, 22, 0)
        lay.setSpacing(10)

        title = QLabel("KittyLauncher")
        title.setObjectName("TopTitle")
        sub = QLabel(self.boot_data.get("platform", ""))
        sub.setObjectName("TopSub")
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addStretch(1)

        self.job_bar = QProgressBar()
        self.job_bar.setFixedWidth(120)
        self.job_bar.setTextVisible(False)
        self.job_bar.hide()
        lay.addWidget(self.job_bar)

        self.job_chip = QLabel("")
        self.job_chip.setObjectName("Chip")
        self.job_chip.hide()
        lay.addWidget(self.job_chip)

        self.game_chip = QLabel("未运行")
        self.game_chip.setObjectName("Chip")
        lay.addWidget(self.game_chip)
        return bar

    def apply_theme(self, dark: bool) -> None:
        self.dark = dark
        self.colors = theme.DARK if dark else theme.LIGHT
        self.setStyleSheet(theme.qss(self.colors))
        self.theme_btn.setText("◐")

    def toggle_theme(self) -> None:
        self.apply_theme(not self.dark)

    def go(self, key: str) -> None:
        order = ["launch", "download", "mods", "settings", "logs"]
        if key in order:
            self.stack.setCurrentIndex(order.index(key))
            page = self.pages[key]
            if key == "download":
                page.reload()

    # ---------------- 状态
    def selected_instance(self) -> dict | None:
        items = self.boot_data.get("instances") or []
        sel = self.boot_data.get("selected")
        for it in items:
            if it["name"] == sel:
                return it
        return items[0] if items else None

    def refresh_all(self) -> None:
        self.boot_data = core.bootstrap()
        for key, page in self.pages.items():
            fn = getattr(page, "refresh", None)
            if not callable(fn):
                continue
            try:
                fn(self.boot_data)
            except Exception as exc:  # noqa: BLE001
                core.log(f"[UI] {key} 刷新异常：{exc}")
        game = self.boot_data["game"]
        if game["running"]:
            self.game_chip.setText("运行中 · " + game["instance"])
            self.game_chip.setObjectName("ChipOn")
        else:
            self.game_chip.setText("未运行")
            self.game_chip.setObjectName("Chip")
        self.game_chip.style().unpolish(self.game_chip)
        self.game_chip.style().polish(self.game_chip)

    # ---------------- 动作
    def toast(self, text: str, kind: str = "") -> None:
        self.toast_widget.show_message(text, kind)
        core.log(("[提示] " if not kind else "[提示] ") + text)

    def select_instance(self, name: str) -> None:
        core.save_config({"selectedInstance": name})
        self.refresh_all()

    def delete_instance(self, name: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("删除实例")
        box.setText(f"删除实例「{name}」？\n只删实例目录（存档 / mods / 配置），不动公共版本库。")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        if box.exec() == QMessageBox.Yes:
            core.delete_instance(name)
            self.refresh_all()
            self.toast("实例已删除")

    def create_instance(self, name: str, mc_version: str, loader: str):
        inst = core.create_instance(name, mc_version, loader)
        core.save_config({"selectedInstance": inst["name"]})
        if loader == "vanilla":
            job = core.install_vanilla_job(mc_version, inst["name"])
        else:
            core.install_vanilla_job(mc_version, "")  # 先补原版，再叠加载器
            job = core.install_loader_job(inst["name"], loader)
        self.toast(f"实例「{inst['name']}」已创建，开始下载", "ok")
        self.refresh_all()
        self.go("launch")
        return job

    def launch_selected(self) -> None:
        inst = self.selected_instance()
        if not inst:
            self.toast("先建一个实例喵", "err")
            return
        r = core.launch(inst["name"])
        if r.get("error"):
            self.toast(r["error"], "err")
            return
        self.toast("已启动，切到「日志」看输出喵～", "ok")
        self.refresh_all()
        self.go("logs")

    def stop_game(self) -> None:
        r = core.stop_game()
        self.toast(r.get("error") or "已发送结束信号", "" if r.get("ok") else "err")
        self.refresh_all()

    # ---------------- 轮询
    def tick_job(self) -> None:
        job = core.current_job()
        if job:
            self.job_chip.show()
            self.job_bar.show()
            self.job_chip.setText(f"{job['title']} · {job['status']}")
            if job["total"]:
                self.job_bar.setRange(0, 100)
                self.job_bar.setValue(job["percent"])
            else:
                self.job_bar.setRange(0, 0)
            if job["state"] != self._last_job_state:
                self._last_job_state = job["state"]
                if job["state"] == "done":
                    self.toast("完成：" + job["title"], "ok")
                    self.refresh_all()
                elif job["state"] == "error":
                    self.toast("失败：" + job["error"], "err")
        else:
            self.job_chip.hide()
            self.job_bar.hide()
        try:
            self.pages["download"].on_job(job)
        except Exception:  # noqa: BLE001
            pass
        game = core.game_status()
        self.game_chip.setText(("运行中 · " + game["instance"]) if game["running"] else "未运行")

    def tick_logs(self) -> None:
        data = core.get_logs(self.log_seq)
        lines = data.get("lines") or []
        if not lines:
            return
        self.log_seq = data["next"]
        text = "\n".join(f"{l['t']}  {l['line']}" for l in lines)
        for key in ("mini_log", "log"):
            widget = getattr(self.pages["launch"], key, None) or getattr(self.pages["logs"], key, None)
            if widget is not None:
                widget.appendPlainText(text)
                sb = widget.verticalScrollBar()
                sb.setValue(sb.maximum())


def app_icon() -> QIcon:
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, 256, 256)
    grad.setColorAt(0, QColor("#a855f7"))
    grad.setColorAt(1, QColor("#ec4899"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(8, 8, 240, 240, 54, 54)
    p.setPen(QColor("white"))
    f = QFont()
    f.setPointSize(120)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "🐱")
    p.end()
    return QIcon(pm)


def screenshot(outdir: str) -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    win = App()
    win.show()
    # 截图时把最近一份真实日志灌进日志页，README 里看起来才像样
    try:
        files = sorted(core.LOGS_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime)
        if files:
            lines = files[-1].read_text("utf-8", errors="replace").splitlines()[-120:]
            text = "\n".join(lines)
            win.pages["logs"].log.setPlainText(text)
            win.pages["launch"].mini_log.setPlainText("\n".join(lines[-12:]))
    except Exception:
        pass
    Path(outdir).mkdir(parents=True, exist_ok=True)
    order = ["launch", "download", "mods", "settings", "logs"]
    for key in order:
        win.go(key)
        if key == "mods":
            try:
                win.pages["mods"].search.setText("sodium")
                win.pages["mods"].do_search()
            except Exception:
                pass
        app.processEvents()
        QTimer.singleShot(0, lambda: None)
        app.processEvents()
        path = Path(outdir) / f"{key}.png"
        win.grab().save(str(path))
        print("saved", path, path.stat().st_size)
    return 0


def main() -> int:
    if "--env" in sys.argv:
        print(env_report.render(), flush=True)
        return 0
    if "--help" in sys.argv or "-h" in sys.argv:
        print(
            "KittyLauncher 1.0.0\n\n"
            "用法:\n"
            "  python -m kitty.main                 启动图形界面\n"
            "  python -m kitty.main --screenshot DIR  无头渲染五个页面截图\n"
            "  python -m kitty.main --env            打印环境自检（贴 issue 用）\n"
            "  python -m kitty.main --help           显示这段帮助\n\n"
            "环境变量:\n"
            "  KITTY_DATA   自定义数据目录（默认 ./data，打包后在用户目录）\n"
            "  KITTY_PYTHON run.sh 用的解释器\n"
        )
        return 0
    if "--screenshot" in sys.argv:
        idx = sys.argv.index("--screenshot")
        out = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "screenshots"
        return screenshot(out)

    app = QApplication(sys.argv)
    app.setApplicationName("KittyLauncher")
    app.setApplicationDisplayName("KittyLauncher")
    app.setWindowIcon(app_icon())
    win = App()
    win.show()

    # 启动时打一份环境自检：终端里能看，日志页也留一行摘要
    try:
        info = env_report.collect()
        print(env_report.render(info), flush=True)
        core.log(env_report.summary_line(info))
    except Exception as exc:  # noqa: BLE001
        core.log(f"[环境] 自检失败：{type(exc).__name__}: {exc}")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
