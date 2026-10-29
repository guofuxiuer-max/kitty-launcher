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

from . import core, env_report
from .paths import VERSION
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
            mode = "离线登录"
            try:
                from . import auth

                st = auth.status()
                if st.get("loggedIn"):
                    mode = f"微软正版 · {st['name']}"
            except Exception:
                pass
            self.hint.setText(f"{mode} · Java {java.get('major','?')} · 内存 {cfg.get('memoryMB', 4096)} MB")

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
            card.repair.connect(self.host.install_loader_for)
            card.settings.connect(self.host.open_instance_settings)
            self.inst_grid.addWidget(card, i // cols, i % cols, Qt.AlignLeft | Qt.AlignTop)
        self.inst_grid.setRowStretch(len(items) // cols + 1, 1)
        for c in range(cols):
            self.inst_grid.setColumnStretch(c, 0)
        self.inst_grid.setColumnStretch(cols, 1)


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

        import_btn = QPushButton("导入整合包（.mrpack / .zip）")
        import_btn.setObjectName("Ghost")
        import_btn.setCursor(Qt.PointingHandCursor)
        import_btn.clicked.connect(self.import_modpack)
        panel.body.addWidget(import_btn)

        tip = QLabel("下载走 Mojang / FabricMC / Forge 官方源，可在设置页切 BMCLAPI 镜像。\n首次安装原版约 200–400 MB（含资源文件）。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        panel.body.addWidget(tip)
        panel.body.addStretch(1)

        lay.addLayout(left, 1)
        lay.addWidget(panel, 0, Qt.AlignTop)

        self.setAcceptDrops(True)
        self.search.textChanged.connect(self._on_search)
        self.list.itemClicked.connect(self._on_pick)
        self.create_btn.clicked.connect(self.create_instance)

    @staticmethod
    def _label(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("Hint")
        return lab

    # ---- 拖拽导入整合包
    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith((".mrpack", ".zip")):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):  # noqa: N802
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".mrpack", ".zip")):
                self.host.import_modpack(path)
                event.acceptProposedAction()
                return

    def import_modpack(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "选择整合包", str(Path.home()), "Modrinth 整合包 (*.mrpack *.zip)"
        )
        if path:
            self.host.import_modpack(path)

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
        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(14)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(_scroll(inner))
        lay = QHBoxLayout()
        lay.setSpacing(18)
        outer.addLayout(lay)

        card = Card()
        card.setMaximumWidth(520)
        t = QLabel("启动与 Java")
        t.setObjectName("Section")
        card.body.addWidget(t)

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

        card.body.addWidget(self._label("全局 JVM 参数（实例可在自己的设置里追加）"))
        self.jvm = QLineEdit()
        self.jvm.setPlaceholderText("-XX:+UseG1GC -XX:MaxGCPauseMillis=50")
        card.body.addWidget(self.jvm)

        card.body.addWidget(self._label("下载源（国内建议切镜像）"))
        self.mirror = QComboBox()
        self.mirror.addItem("官方源（Mojang / FabricMC）", "official")
        self.mirror.addItem("BMCLAPI 镜像（国内加速）", "bmclapi")
        card.body.addWidget(self.mirror)

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
        about = QLabel(f"KittyLauncher {VERSION}\nmacOS 专用的 PCL 风格 Minecraft 启动器\nPython + PySide6 (Qt 6) · MIT")
        about.setObjectName("Hint")
        right.body.addWidget(about)
        right.body.addStretch(1)

        env = Card()
        t3 = QLabel("环境自检")
        t3.setObjectName("Section")
        env.body.addWidget(t3)
        tip = QLabel("报 issue 时把这块整段复制过去，比描述一百句都管用。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        env.body.addWidget(tip)

        self.env_view = QPlainTextEdit()
        self.env_view.setObjectName("Log")
        self.env_view.setReadOnly(True)
        self.env_view.setFixedHeight(250)
        small = QFont("Menlo")
        small.setPointSize(9)
        self.env_view.setFont(small)
        self.env_view.setPlainText(env_report.render())
        env.body.addWidget(self.env_view)

        env_btns = QHBoxLayout()
        copy_btn = QPushButton("复制")
        copy_btn.setObjectName("Ghost")
        copy_btn.clicked.connect(self.copy_env)
        again_btn = QPushButton("重新检测")
        again_btn.setObjectName("Ghost")
        again_btn.clicked.connect(self.refresh_env)
        env_btns.addWidget(copy_btn)
        env_btns.addWidget(again_btn)
        env_btns.addStretch(1)
        env.body.addLayout(env_btns)

        lay.addWidget(card, 0, Qt.AlignTop)
        lay.addWidget(right, 0, Qt.AlignTop)
        lay.addStretch(1)

        outer.addWidget(env, 0)
        outer.addStretch(1)

    @staticmethod
    def _label(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("Hint")
        return lab

    def refresh(self, boot: dict) -> None:
        cfg = boot["config"]
        self.mem.setValue(int(cfg.get("memoryMB", 4096)))
        self.jvm.setText(cfg.get("jvmArgs", "") or "")
        mi = self.mirror.findData(cfg.get("mirror", "official"))
        self.mirror.setCurrentIndex(max(0, mi))
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

        if hasattr(self, "env_view"):
            self.env_view.setPlainText(env_report.render())

    def save(self) -> None:
        core.save_config({
            "javaPath": self.java.currentData() or "",
            "memoryMB": self.mem.value(),
            "width": self.w.value(),
            "height": self.h.value(),
            "jvmArgs": self.jvm.text().strip(),
            "mirror": self.mirror.currentData() or "official",
        })
        self.host.toast("设置已保存", "ok")
        self.host.refresh_all()

    def open_instance(self) -> None:
        inst = self.host.selected_instance()
        if inst:
            core.open_path(inst["dir"])

    def refresh_env(self) -> None:
        self.env_view.setPlainText(env_report.render())

    def copy_env(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.env_view.toPlainText())
        self.host.toast("环境信息已复制到剪贴板", "ok")


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
        diag = QPushButton("分析日志")
        diag.setObjectName("Tiny")
        diag.setCursor(Qt.PointingHandCursor)
        diag.clicked.connect(lambda: host.diagnose(host.selected_instance()["name"] if host.selected_instance() else ""))
        bar.addWidget(diag)
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



class UsersPage(QWidget):
    """用户页：微软账号 + 3D 皮肤预览，账号相关的东西全在这一页。"""

    def __init__(self, host):
        super().__init__()
        self.host = host
        self._skin_key = None

        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(26, 22, 26, 24)
        outer.setSpacing(14)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(_scroll(inner))

        # ---------------- 账号卡
        top = QHBoxLayout()
        top.setSpacing(16)

        acc = Card()
        acc.setMaximumWidth(560)
        t = QLabel("微软账号")
        t.setObjectName("Section")
        acc.body.addWidget(t)

        self.account_view = QLabel("离线")
        self.account_view.setWordWrap(True)
        self.account_view.setStyleSheet("font-size:14px;")
        acc.body.addWidget(self.account_view)

        self.uuid_view = QLabel("")
        self.uuid_view.setObjectName("Hint")
        self.uuid_view.setWordWrap(True)
        acc.body.addWidget(self.uuid_view)

        row = QHBoxLayout()
        self.login_btn = QPushButton("微软登录…")
        self.login_btn.setObjectName("Primary")
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.clicked.connect(host.open_microsoft_login)
        self.refresh_btn = QPushButton("刷新 token")
        self.refresh_btn.setObjectName("Ghost")
        self.refresh_btn.clicked.connect(host.refresh_microsoft)
        self.logout_btn = QPushButton("退出登录")
        self.logout_btn.setObjectName("Ghost")
        self.logout_btn.clicked.connect(host.logout_microsoft)
        row.addWidget(self.login_btn)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.logout_btn)
        row.addStretch(1)
        acc.body.addLayout(row)

        acc.body.addWidget(self._label("离线玩家名（没登录正版时用这个名字）"))
        name_row = QHBoxLayout()
        self.offline_name = QLineEdit()
        self.offline_name.setPlaceholderText("Steve")
        self.offline_name.returnPressed.connect(self.save_offline_name)
        save_name = QPushButton("保存")
        save_name.setObjectName("Ghost")
        save_name.clicked.connect(self.save_offline_name)
        name_row.addWidget(self.offline_name, 1)
        name_row.addWidget(save_name)
        acc.body.addLayout(name_row)
        top.addWidget(acc, 0, Qt.AlignTop)

        tip = Card()
        tip.setMaximumWidth(380)
        t2 = QLabel("说明")
        t2.setObjectName("Section")
        tip.body.addWidget(t2)
        note = QLabel(
            "· 登录后才能进正版服，启动命令里的用户名/UUID/token 会换成真实身份\n"
            "· token 存在 data/accounts.json，权限 600，只有你自己能读\n"
            "· Minecraft token 约 24 小时过期，启动前会自动续期\n"
            "· 退出登录只删本地记录，不影响微软账号"
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        tip.body.addWidget(note)
        tip.body.addStretch(1)
        top.addWidget(tip, 0, Qt.AlignTop)
        top.addStretch(1)
        outer.addLayout(top)

        # ---------------- 皮肤卡
        skin_card = Card()
        skin_row = QHBoxLayout()
        skin_row.setSpacing(20)

        from .skin3d import Skin3DView

        self.view3d = Skin3DView()
        self.view3d.setFixedSize(230, 320)
        self.view3d.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(168,85,247,0.16), stop:1 rgba(0,0,0,0.25));"
            "border: 1px solid #2b3040; border-radius: 16px;"
        )
        view_col = QVBoxLayout()
        view_col.setSpacing(6)
        view_col.addWidget(self.view3d, 0, Qt.AlignTop)
        view_hint = QLabel("拖动旋转 · 滚轮缩放 · 双击暂停自转")
        view_hint.setObjectName("Hint")
        view_hint.setAlignment(Qt.AlignCenter)
        view_hint.setFixedWidth(230)
        view_col.addWidget(view_hint)
        skin_row.addLayout(view_col)

        info = QVBoxLayout()
        info.setSpacing(10)

        head_row = QHBoxLayout()
        self.head_label = QLabel("")
        self.head_label.setFixedSize(96, 96)
        self.head_label.setAlignment(Qt.AlignCenter)
        self.head_label.setStyleSheet("border-radius: 14px; background: rgba(255,255,255,0.04);")
        head_row.addWidget(self.head_label)

        name_col = QVBoxLayout()
        self.skin_name = QLabel("—")
        self.skin_name.setStyleSheet("font-size:19px; font-weight:600;")
        self.skin_sub = QLabel("")
        self.skin_sub.setObjectName("Hint")
        self.skin_sub.setWordWrap(True)
        name_col.addWidget(self.skin_name)
        name_col.addWidget(self.skin_sub)
        name_col.addStretch(1)
        head_row.addLayout(name_col, 1)
        info.addLayout(head_row)

        self.skin_source = QLabel("")
        self.skin_source.setObjectName("Hint")
        self.skin_source.setWordWrap(True)
        info.addWidget(self.skin_source)

        self.skin_path = QLabel("")
        self.skin_path.setObjectName("Hint")
        self.skin_path.setWordWrap(True)
        info.addWidget(self.skin_path)

        info.addWidget(self._label("想看别人？输入正版玩家名预览"))
        look_row = QHBoxLayout()
        self.look_name = QLineEdit()
        self.look_name.setPlaceholderText("例如 Notch / jeb_ / Dream")
        self.look_name.returnPressed.connect(lambda: self.load_skin(self.look_name.text().strip()))
        look = QPushButton("预览")
        look.setObjectName("Primary")
        look.clicked.connect(lambda: self.load_skin(self.look_name.text().strip()))
        look_row.addWidget(self.look_name, 1)
        look_row.addWidget(look)
        info.addLayout(look_row)

        info.addStretch(1)
        btn_row = QHBoxLayout()
        self.spin_btn = QPushButton("暂停自转")
        self.spin_btn.setObjectName("Tiny")
        self.spin_btn.clicked.connect(self.toggle_spin)
        reset_btn = QPushButton("重置视角")
        reset_btn.setObjectName("Tiny")
        reset_btn.clicked.connect(lambda: self.view3d.reset_view())
        big_btn = QPushButton("独立窗口")
        big_btn.setObjectName("Tiny")
        big_btn.clicked.connect(host.open_skin_preview)
        open_btn = QPushButton("打开皮肤文件")
        open_btn.setObjectName("Tiny")
        open_btn.clicked.connect(self.open_skin_file)
        btn_row.addWidget(self.spin_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addWidget(big_btn)
        btn_row.addWidget(open_btn)
        btn_row.addStretch(1)
        info.addLayout(btn_row)

        skin_row.addLayout(info, 1)
        skin_card.body.addLayout(skin_row)
        outer.addWidget(skin_card)
        outer.addStretch(1)

        self._info = {}

    @staticmethod
    def _label(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("Hint")
        return lab

    # ---------------- 行为
    def toggle_spin(self) -> None:
        running = self.view3d.toggle_auto()
        self.spin_btn.setText("暂停自转" if running else "继续自转")

    def save_offline_name(self) -> None:
        name = self.offline_name.text().strip() or "Steve"
        core.save_config({"username": name})
        self.host.toast(f"离线名字已保存：{name}", "ok")
        self._skin_key = None
        self.load_skin()

    def open_skin_file(self) -> None:
        import subprocess

        path = self._info.get("path")
        if path:
            subprocess.Popen(["open", "-R", str(path)])

    def load_skin(self, who: str = "", network: bool = False) -> None:
        from . import skin

        info = skin.resolve(who, allow_network=network)
        self._apply_skin(info)
        if info.get("pending"):
            self._fetch_skin_async(who)

    def _fetch_skin_async(self, who: str) -> None:
        import threading

        from . import skin

        from PySide6.QtCore import QTimer

        if getattr(self, "_skin_busy", False):
            return
        self._skin_busy = True
        box: dict = {}

        def work():
            try:
                box["info"] = skin.resolve(who, allow_network=True)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc
            box["done"] = True

        threading.Thread(target=work, name="skin-fetch", daemon=True).start()

        poll = QTimer(self)
        poll.setInterval(250)

        def check():
            if not box.get("done"):
                return
            poll.stop()
            self._skin_busy = False
            if "info" in box:
                self._apply_skin(box["info"])

        poll.timeout.connect(check)
        poll.start()
        self._skin_poll = poll

    def _apply_skin(self, info: dict) -> None:
        from . import skin

        self._info = info
        self.view3d.set_skin(info["path"], slim=(info.get("model") == "slim"))
        head = skin.head(info["path"], 88)
        if not head.isNull():
            self.head_label.setPixmap(head)
        self.skin_name.setText(info.get("name") or "—")
        self.skin_sub.setText(("UUID " + info["uuid"]) if info.get("uuid") else "无 uuid（离线名）")
        model = "经典（4px 手臂）" if info.get("model") != "slim" else "纤细（3px 手臂）"
        self.skin_source.setText(f"来源：{info.get('source', '')} · {model}"
                                 + (f"\n{info['error']}" if info.get("error") else ""))
        self.skin_path.setText(f"文件：{info['path']}")

    def refresh(self, boot: dict) -> None:
        from . import auth

        try:
            st = auth.status()
        except Exception:
            st = {"loggedIn": False}

        self.offline_name.setText(boot["config"].get("username", "") or "")

        if st.get("loggedIn"):
            hours = st.get("expiresIn", 0) / 3600
            self.account_view.setText(f"✅ 已登录微软正版：<b>{st['name']}</b>")
            self.account_view.setStyleSheet("color:#6ee7b7; font-size:14px;")
            self.uuid_view.setText(f"UUID {st['uuid']} · token 剩余 {hours:.1f} 小时")
            self.login_btn.setText("切换账号…")
            self.refresh_btn.setEnabled(True)
            self.logout_btn.setEnabled(True)
        else:
            self.account_view.setText("离线模式（能玩单人和离线服；正版服需要登录）")
            self.account_view.setStyleSheet("color:#9498ac; font-size:14px;")
            self.uuid_view.setText("")
            self.login_btn.setText("微软登录…")
            self.refresh_btn.setEnabled(False)
            self.logout_btn.setEnabled(False)

        key = st.get("uuid") or ("offline:" + (boot["config"].get("username") or ""))
        if key != self._skin_key:
            self._skin_key = key
            try:
                self.load_skin()
            except Exception as exc:  # noqa: BLE001
                core.log(f"[UI] 皮肤加载失败：{exc}")

def build_pages(host) -> dict[str, QWidget]:
    return {
        "launch": LaunchPage(host),
        "download": DownloadPage(host),
        "mods": ModsPage(host),
        "settings": SettingsPage(host),
        "logs": LogsPage(host),
        "users": UsersPage(host),
    }
