"""五个页面：启动 / 下载 / 模组 / 设置 / 日志。

页面只负责显示与收集输入，真正的活在 kitty/core.py 里。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget, QButtonGroup,
)

from . import core
from .widgets import Card, InstanceCard, StatCard, Tag, elide, loader_cn


def _title(text: str, sub: str = "") -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    t = QLabel(text)
    t.setObjectName("Section")
    lay.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setObjectName("SectionSub")
        lay.addWidget(s)
    lay.addStretch(1)
    return w


def _scroll(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setWidget(inner)
    return sa


class LaunchPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(14)

        # ---- Hero
        hero = QFrame()
        hero.setObjectName("Hero")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(26, 22, 26, 22)
        hl.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(6)
        self.greet = QLabel("嗨，Steve 喵～")
        self.greet.setObjectName("HeroTitle")
        self.sub = QLabel("当前实例：—")
        self.sub.setObjectName("HeroSub")
        self.launch_btn = QPushButton("启动游戏")
        self.launch_btn.setObjectName("Big")
        self.launch_btn.setCursor(Qt.PointingHandCursor)
        self.launch_btn.setFixedWidth(220)
        self.hint = QLabel("离线登录 · 无需正版账号")
        self.hint.setObjectName("Hint")
        left.addWidget(self.greet)
        left.addWidget(self.sub)
        left.addSpacing(10)
        left.addWidget(self.launch_btn, 0, Qt.AlignLeft)
        left.addSpacing(6)
        left.addWidget(self.hint)
        left.addStretch(1)
        hl.addLayout(left, 1)

        stats = QVBoxLayout()
        stats.setSpacing(8)
        self.stat_ver = StatCard("游戏版本")
        self.stat_loader = StatCard("加载器")
        self.stat_mods = StatCard("已装模组", "0")
        for s in (self.stat_ver, self.stat_loader, self.stat_mods):
            s.setFixedWidth(210)
            stats.addWidget(s)
        hl.addLayout(stats)
        lay.addWidget(hero)

        # ---- 实例列表
        lay.addWidget(_title("我的实例", "每个实例独立 mods / 存档 / 配置"))
        self.inst_host = QWidget()
        self.inst_grid = QGridLayout(self.inst_host)
        self.inst_grid.setContentsMargins(0, 0, 6, 0)
        self.inst_grid.setSpacing(12)
        self.inst_scroll = _scroll(self.inst_host)
        self.inst_scroll.setMinimumHeight(150)
        self.inst_scroll.setMaximumHeight(280)
        lay.addWidget(self.inst_scroll, 1)

        # ---- 迷你日志
        lay.addWidget(_title("最近日志", ""))
        self.mini_log = QPlainTextEdit()
        self.mini_log.setObjectName("Log")
        self.mini_log.setReadOnly(True)
        self.mini_log.setMaximumBlockCount(200)
        self.mini_log.setPlaceholderText("启动游戏后，这里会实时显示游戏日志喵～")
        self.mini_log.setFixedHeight(140)
        lay.addWidget(self.mini_log)

        self.launch_btn.clicked.connect(host.launch_selected)

    # ---- 刷新
    def refresh(self, boot: dict) -> None:
        cfg = boot["config"]
        inst = self.host.selected_instance()
        self.greet.setText(f"嗨，{cfg.get('username') or 'Steve'} 喵～")
        self.sub.setText(f"当前实例：{inst['name']}" if inst else "当前实例：还没有实例，去「下载」页建一个")
        self.stat_ver.set_value(inst["mcVersion"] if inst else "—")
        self.stat_loader.set_value(loader_cn(inst.get("loader")) if inst else "—")
        self.stat_mods.set_value(str(inst.get("modCount", 0)) if inst else "0")

        running = boot["game"]["running"]
        self.launch_btn.setEnabled(bool(inst) and inst.get("installed") and not running)
        self.launch_btn.setText("游戏运行中…" if running else "启动游戏")
        if not inst:
            self.hint.setText("先在「下载」页新建一个实例")
        elif not inst.get("installed"):
            self.hint.setText("这个实例的版本还没下载完")
        else:
            java = inst.get("java") or {}
            self.hint.setText(
                f"离线登录 · Java {java.get('major','?')} · 内存 {cfg.get('memoryMB', 4096)} MB"
            )

        # 实例卡
        while self.inst_grid.count():
            item = self.inst_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        items = boot["instances"]
        if not items:
            empty = QLabel("还没有实例，去「下载」页创建一个喵～")
            empty.setObjectName("Hint")
            empty.setAlignment(Qt.AlignCenter)
            self.inst_grid.addWidget(empty, 0, 0)
            return
        cols = 3
        for i, it in enumerate(items):
            card = InstanceCard(it, selected=bool(inst and it["name"] == inst["name"]))
            card.clicked.connect(self.host.select_instance)
            card.deleted.connect(self.host.delete_instance)
            self.inst_grid.addWidget(card, i // cols, i % cols)
        self.inst_grid.setRowStretch(len(items) // cols + 1, 1)


class DownloadPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.kind = "release"
        self.picked = ""

        lay = QHBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(18)

        # ---- 左：版本列表
        left = QVBoxLayout()
        left.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.seg_box = QWidget()
        seg = QHBoxLayout(self.seg_box)
        seg.setContentsMargins(4, 4, 4, 4)
        seg.setSpacing(2)
        self.seg_box.setStyleSheet(
            "background:#1c1f28; border:1px solid #2b3040; border-radius:12px;"
        )
        self.group = QButtonGroup(self)
        for i, (key, text) in enumerate((("release", "正式版"), ("snapshot", "快照"), ("installed", "已安装"))):
            b = QPushButton(text)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("kind", key)
            if i == 0:
                b.setChecked(True)
            self.group.addButton(b)
            seg.addWidget(b)
        self.group.buttonClicked.connect(self._on_kind)
        bar.addWidget(self.seg_box)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索版本号，例如 26.3")
        self.search.setClearButtonEnabled(True)
        bar.addWidget(self.search, 1)
        left.addLayout(bar)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(False)
        self.list.setSpacing(2)
        left.addWidget(self.list, 1)

        # ---- 右：新建实例
        panel = Card()
        panel.setFixedWidth(330)
        panel.body.setSpacing(10)
        t = QLabel("新建实例并安装")
        t.setObjectName("Section")
        panel.body.addWidget(t)

        panel.body.addWidget(self._label("选中的游戏版本"))
        self.pick_label = QLabel("← 点左边任意版本")
        self.pick_label.setObjectName("Hint")
        self.pick_label.setStyleSheet("font-family:monospace; font-size:13px;")
        panel.body.addWidget(self.pick_label)

        panel.body.addWidget(self._label("实例名称"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如 生存-Fabric")
        panel.body.addWidget(self.name_edit)

        panel.body.addWidget(self._label("加载器"))
        self.loader_box = QComboBox()
        self.loader_box.addItem("原版 Vanilla", "vanilla")
        self.loader_box.addItem("Fabric（主流模组）", "fabric")
        self.loader_box.addItem("Forge（老模组）", "forge")
        self.loader_box.addItem("Quilt（Fabric 分支）", "quilt")
        panel.body.addWidget(self.loader_box)

        self.create_btn = QPushButton("创建并开始下载")
        self.create_btn.setObjectName("Primary")
        self.create_btn.setCursor(Qt.PointingHandCursor)
        panel.body.addWidget(self.create_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        panel.body.addWidget(self.progress)
        self.progress_text = QLabel("空闲")
        self.progress_text.setObjectName("Hint")
        panel.body.addWidget(self.progress_text)

        tip = QLabel("下载走 Mojang / FabricMC / Forge 官方源。\n首次安装原版约 200–400 MB（含资源文件）。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        panel.body.addWidget(tip)
        panel.body.addStretch(1)

        lay.addLayout(left, 1)
        lay.addWidget(panel, 0, Qt.AlignTop)

        self.search.textChanged.connect(self._on_search)
        self.list.itemClicked.connect(self._on_pick)
        self.create_btn.clicked.connect(self.create_instance)

    @staticmethod
    def _label(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("Hint")
        return lab

    # ---- 行为
    def _on_kind(self, btn):
        self.kind = btn.property("kind")
        self.reload()

    def _on_search(self):
        if not hasattr(self, "_timer"):
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.reload)
        self._timer.start(280)

    def reload(self) -> None:
        self.list.clear()
        if self.kind == "installed":
            for inst in self.host.boot_data.get("instances", []):
                item = QListWidgetItem(f"{inst['mcVersion']}    {loader_cn(inst.get('loader'))}    {inst['name']}")
                item.setData(Qt.UserRole, inst["mcVersion"])
                self.list.addItem(item)
            return
        q = self.search.text().strip().lower()
        items = core.remote_versions()
        if self.kind == "release":
            items = [v for v in items if v["type"] == "release"]
        elif self.kind == "snapshot":
            items = [v for v in items if v["type"] != "release"]
        if q:
            items = [v for v in items if q in v["id"].lower()]
        installed = {i["versionId"] for i in self.host.boot_data.get("instances", [])}
        for v in items[:150]:
            tag = "  · 已装" if v["id"] in installed else ""
            item = QListWidgetItem(f"{v['id']:<16} {v['releaseTime'][:10]}{tag}")
            item.setData(Qt.UserRole, v["id"])
            self.list.addItem(item)

    def _on_pick(self, item) -> None:
        vid = item.data(Qt.UserRole)
        self.picked = vid
        self.pick_label.setText(vid)
        if not self.name_edit.text().strip():
            self.name_edit.setText(f"{vid}-实例")

    def create_instance(self) -> None:
        vid = self.picked
        if self.kind == "installed" or not vid:
            self.host.toast("先在左边点一个版本喵", "err")
            return
        name = self.name_edit.text().strip() or f"{vid}-实例"
        loader = self.loader_box.currentData()
        r = self.host.create_instance(name, vid, loader)
        if r:
            self.name_edit.clear()
            self.pick_label.setText("← 点左边任意版本")
            self.picked = ""

    def on_job(self, job: dict | None) -> None:
        if not job:
            self.progress_text.setText("空闲")
            self.progress.setValue(0)
            return
        self.progress_text.setText(f"{job['title']} · {job['status']}")
        if job["total"]:
            self.progress.setRange(0, 100)
            self.progress.setValue(job["percent"])
        else:
            self.progress.setRange(0, 0)


class ModsPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(12)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜 Modrinth 模组，例如 sodium / jei / 家具")
        self.search.returnPressed.connect(self.do_search)
        btn = QPushButton("搜索")
        btn.setObjectName("Primary")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.do_search)
        bar.addWidget(self.search, 1)
        bar.addWidget(btn)
        lay.addLayout(bar)

        self.scope = QLabel("按当前实例的版本与加载器过滤")
        self.scope.setObjectName("Hint")
        lay.addWidget(self.scope)

        self.results_host = QWidget()
        self.results_grid = QGridLayout(self.results_host)
        self.results_grid.setContentsMargins(0, 0, 6, 0)
        self.results_grid.setSpacing(12)
        lay.addWidget(_scroll(self.results_host), 1)

        lay.addWidget(_title("已装模组"))
        self.installed = QListWidget()
        self.installed.setMaximumHeight(150)
        lay.addWidget(self.installed)

    def refresh(self, boot: dict) -> None:
        inst = self.host.selected_instance()
        self.scope.setText(
            f"实例「{inst['name']}」· {inst['mcVersion']} · {loader_cn(inst.get('loader'))}"
            if inst else "先建一个实例再用模组页"
        )
        self.load_installed()

    def do_search(self) -> None:
        inst = self.host.selected_instance()
        if not inst:
            self.host.toast("先建一个实例", "err")
            return
        if inst.get("loader") == "vanilla":
            self.clear_results("原版实例装不了模组，先建 Fabric/Forge 实例")
            return
        data = core.modrinth_search(self.search.text().strip(), inst["mcVersion"], inst.get("loader", ""))
        if data.get("error"):
            self.host.toast(data["error"], "err")
            return
        self.clear_results()
        hits = data.get("hits", [])
        if not hits:
            self.clear_results("没搜到，换个词喵")
        for i, m in enumerate(hits):
            card = self._mod_card(m, inst["name"])
            self.results_grid.addWidget(card, i // 2, i % 2)

    def clear_results(self, text: str = "") -> None:
        while self.results_grid.count():
            item = self.results_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if text:
            lab = QLabel(text)
            lab.setObjectName("Hint")
            lab.setAlignment(Qt.AlignCenter)
            self.results_grid.addWidget(lab, 0, 0, 1, 2)

    def _mod_card(self, m: dict, instance: str) -> QFrame:
        card = Card()
        card.setFixedHeight(118)
        head = QHBoxLayout()
        title = QLabel(m.get("title", ""))
        title.setObjectName("InstName")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(Tag(f"⤓ {int(m.get('downloads') or 0):,}"))
        card.body.addLayout(head)

        desc = QLabel(m.get("description", ""))
        desc.setObjectName("Hint")
        desc.setWordWrap(True)
        desc.setMaximumHeight(44)
        card.body.addWidget(desc)

        foot = QHBoxLayout()
        cats = QLabel(" · ".join((m.get("categories") or [])[:3]))
        cats.setObjectName("Hint")
        foot.addWidget(cats)
        foot.addStretch(1)
        btn = QPushButton("装到实例")
        btn.setObjectName("Tiny")
        btn.setCursor(Qt.PointingHandCursor)

        def install():
            btn.setEnabled(False)
            btn.setText("下载中…")
            r = core.install_mod_from_modrinth(instance, m.get("id", ""))
            if r.get("ok"):
                btn.setText("已安装")
                self.host.toast(f"已装：{r['file']}", "ok")
                self.load_installed()
                self.host.refresh_all()
            else:
                btn.setEnabled(True)
                btn.setText("装到实例")
                self.host.toast(r.get("error", "失败"), "err")

        btn.clicked.connect(install)
        foot.addWidget(btn)
        card.body.addLayout(foot)
        return card

    def load_installed(self) -> None:
        inst = self.host.selected_instance()
        self.installed.clear()
        if not inst:
            return
        for m in core.list_mods(inst["name"]):
            item = QListWidgetItem(f"{m['file']}    {m['size']/1048576:.2f} MB")
            self.installed.addItem(item)


class SettingsPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        lay = QHBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(18)

        card = Card()
        card.setMaximumWidth(520)
        t = QLabel("账号与启动")
        t.setObjectName("Section")
        card.body.addWidget(t)

        card.body.addWidget(self._label("离线玩家名（游戏内显示的名字）"))
        self.user = QLineEdit()
        card.body.addWidget(self.user)

        card.body.addWidget(self._label("Java 运行时"))
        self.java = QComboBox()
        card.body.addWidget(self.java)
        self.java_hint = QLabel("")
        self.java_hint.setObjectName("Hint")
        self.java_hint.setWordWrap(True)
        card.body.addWidget(self.java_hint)

        card.body.addWidget(self._label("内存上限（MB）"))
        self.mem = QSpinBox()
        self.mem.setRange(1024, 32768)
        self.mem.setSingleStep(512)
        self.mem.setSuffix(" MB")
        card.body.addWidget(self.mem)

        size_row = QHBoxLayout()
        vcol = QVBoxLayout()
        vcol.addWidget(self._label("窗口宽"))
        self.w = QSpinBox()
        self.w.setRange(640, 5120)
        self.w.setSingleStep(64)
        vcol.addWidget(self.w)
        hcol = QVBoxLayout()
        hcol.addWidget(self._label("窗口高"))
        self.h = QSpinBox()
        self.h.setRange(480, 2880)
        self.h.setSingleStep(64)
        hcol.addWidget(self.h)
        size_row.addLayout(vcol)
        size_row.addLayout(hcol)
        card.body.addLayout(size_row)

        save = QPushButton("保存设置")
        save.setObjectName("Primary")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self.save)
        card.body.addWidget(save)
        card.body.addStretch(1)

        right = Card()
        right.setMaximumWidth(420)
        t2 = QLabel("目录")
        t2.setObjectName("Section")
        right.body.addWidget(t2)
        self.dir_game = QLabel("")
        self.dir_game.setObjectName("Hint")
        self.dir_game.setWordWrap(True)
        right.body.addWidget(self.dir_game)
        b1 = QPushButton("在访达中打开游戏目录")
        b1.setObjectName("Ghost")
        b1.clicked.connect(lambda: core.open_path(str(core.MC_DIR)))
        right.body.addWidget(b1)

        self.dir_inst = QLabel("")
        self.dir_inst.setObjectName("Hint")
        self.dir_inst.setWordWrap(True)
        right.body.addWidget(self.dir_inst)
        b2 = QPushButton("打开当前实例目录")
        b2.setObjectName("Ghost")
        b2.clicked.connect(self.open_instance)
        right.body.addWidget(b2)

        t3 = QLabel("关于")
        t3.setObjectName("Section")
        right.body.addSpacing(10)
        right.body.addWidget(t3)
        about = QLabel("KittyLauncher 1.0.0\nPCL 风格的跨平台 Minecraft 启动器\nPython + PySide6 (Qt 6) · MIT")
        about.setObjectName("Hint")
        right.body.addWidget(about)
        right.body.addStretch(1)

        lay.addWidget(card, 0, Qt.AlignTop)
        lay.addWidget(right, 0, Qt.AlignTop)
        lay.addStretch(1)

    @staticmethod
    def _label(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("Hint")
        return lab

    def refresh(self, boot: dict) -> None:
        cfg = boot["config"]
        self.user.setText(cfg.get("username", ""))
        self.mem.setValue(int(cfg.get("memoryMB", 4096)))
        self.w.setValue(int(cfg.get("width", 1280)))
        self.h.setValue(int(cfg.get("height", 720)))
        self.dir_game.setText(str(core.MC_DIR))
        inst = self.host.selected_instance()
        self.dir_inst.setText(inst["dir"] if inst else "（无实例）")

        self.java.clear()
        self.java.addItem("自动选择（按版本需求）", "")
        for j in boot["java"]:
            self.java.addItem(f"Java {j['major']} · {j['vendor']} · {j['version']}", j["path"])
        idx = self.java.findData(cfg.get("javaPath", ""))
        self.java.setCurrentIndex(max(0, idx))

        if inst:
            need = core.version_java_major(inst["versionId"])
            have = [j["major"] for j in boot["java"]]
            ok = any(m >= need for m in have)
            self.java_hint.setText(
                f"该实例需要 Java {need}+，本机有：{', '.join(map(str, sorted(set(have), reverse=True))) or '无'}"
                + ("" if ok else "  ⚠️ 版本不够，需要另装 Java")
            )
        else:
            self.java_hint.setText("")

    def save(self) -> None:
        core.save_config({
            "username": self.user.text().strip() or "Steve",
            "javaPath": self.java.currentData() or "",
            "memoryMB": self.mem.value(),
            "width": self.w.value(),
            "height": self.h.value(),
        })
        self.host.toast("设置已保存", "ok")
        self.host.refresh_all()

    def open_instance(self) -> None:
        inst = self.host.selected_instance()
        if inst:
            core.open_path(inst["dir"])


class LogsPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(10)

        bar = QHBoxLayout()
        hint = QLabel("实时日志：游戏 stdout + 启动器事件")
        hint.setObjectName("Hint")
        bar.addWidget(hint)
        bar.addStretch(1)
        clear = QPushButton("清屏")
        clear.setObjectName("Tiny")
        clear.clicked.connect(lambda: self.log.clear())
        stop = QPushButton("结束游戏")
        stop.setObjectName("Tiny")
        stop.clicked.connect(host.stop_game)
        bar.addWidget(clear)
        bar.addWidget(stop)
        lay.addLayout(bar)

        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(8000)
        lay.addWidget(self.log, 1)


def build_pages(host) -> dict[str, QWidget]:
    return {
        "launch": LaunchPage(host),
        "download": DownloadPage(host),
        "mods": ModsPage(host),
        "settings": SettingsPage(host),
        "logs": LogsPage(host),
    }
