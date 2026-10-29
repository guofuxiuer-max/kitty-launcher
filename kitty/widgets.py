"""可复用小组件：导航按钮、卡片、统计块、实例卡、浮动提示。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QPoint, QTimer
from PySide6.QtGui import QFontMetrics, QFont
from PySide6.QtWidgets import (
    QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy,
)


def elide(label: QLabel, text: str) -> None:
    fm = QFontMetrics(label.font())
    label.setText(fm.elidedText(text, Qt.ElideRight, max(60, label.width() - 4)))


class NavButton(QPushButton):
    """左侧竖排导航：上图标下文字，用多行文本换行，颜色跟随按钮状态。"""

    def __init__(self, icon: str, text: str, parent=None):
        super().__init__(f"{icon}\n{text}", parent)
        self.setObjectName("Nav")
        self.setCheckable(True)
        self.setFixedSize(72, 58)
        self.setCursor(Qt.PointingHandCursor)
        self.page_key = ""
        f = QFont()
        f.setPointSize(11)
        self.setFont(f)


class Card(QFrame):
    def __init__(self, parent=None, object_name: str = "Card"):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 16, 16, 16)
        self.body.setSpacing(8)


class StatCard(QFrame):
    def __init__(self, key: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("Stat")
        self.setFixedHeight(64)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 9, 13, 9)
        lay.setSpacing(2)
        self.k = QLabel(key)
        self.k.setObjectName("StatKey")
        self.v = QLabel(value)
        self.v.setObjectName("StatVal")
        lay.addWidget(self.k)
        lay.addWidget(self.v)

    def set_value(self, text: str) -> None:
        self.v.setText(text)


class Tag(QLabel):
    def __init__(self, text: str, color: str = "dim", parent=None):
        super().__init__(text, parent)
        palette = {
            "dim": ("#9498ac", "rgba(255,255,255,0.05)", "#2b3040"),
            "accent": ("#d8b4fe", "rgba(168,85,247,0.16)", "rgba(168,85,247,0.35)"),
            "ok": ("#6ee7b7", "rgba(52,211,153,0.14)", "rgba(52,211,153,0.35)"),
            "warn": ("#fcd34d", "rgba(251,191,36,0.14)", "rgba(251,191,36,0.35)"),
        }
        fg, bg, bd = palette.get(color, palette["dim"])
        self.setStyleSheet(
            f"color:{fg}; background:{bg}; border:1px solid {bd};"
            "border-radius:9px; padding:2px 8px; font-size:11px;"
        )


class InstanceCard(QFrame):
    """一个实例卡片：图标 + 名字 + 版本 + 标签，点击选中。"""

    clicked = Signal(str)
    deleted = Signal(str)
    repair = Signal(str)
    settings = Signal(str)

    def __init__(self, inst: dict, selected: bool = False, parent=None):
        super().__init__(parent)
        self.inst = inst
        self.setObjectName("InstCard")
        self.setProperty("picked", "true" if selected else "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(112)
        self.setMaximumWidth(340)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        icon = QLabel({"fabric": "🧵", "forge": "🔨", "quilt": "🪡"}.get(inst.get("loader"), "🌱"))
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 rgba(168,85,247,0.45), stop:1 rgba(236,72,153,0.35));"
            "border-radius:10px; font-size:18px;"
        )
        top.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(1)
        self.name = QLabel(inst.get("name", ""))
        self.name.setObjectName("InstName")
        self.name.setMinimumWidth(80)
        ver = QLabel(f"{inst.get('mcVersion','')} · {loader_cn(inst.get('loader'))}")
        ver.setObjectName("InstVer")
        col.addWidget(self.name)
        col.addWidget(ver)
        top.addLayout(col, 1)

        # 选了加载器但版本 id 还等于原版 → 加载器没装上（多半是任务被顶掉/网络失败）
        needs_loader = (
            inst.get("loader") not in (None, "", "vanilla")
            and inst.get("versionId") == inst.get("mcVersion")
        )
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("CardIcon")
        self.settings_btn.setFixedSize(24, 24)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setToolTip("实例设置（内存 / Java / JVM 参数）")
        self.settings_btn.clicked.connect(lambda: self.settings.emit(inst.get("name", "")))
        top.addWidget(self.settings_btn, 0, Qt.AlignTop)

        self.repair_btn = QPushButton("装加载器")
        self.repair_btn.setObjectName("Tiny")
        self.repair_btn.setCursor(Qt.PointingHandCursor)
        self.repair_btn.setToolTip("这个实例只装了原版，点一下补装加载器")
        self.repair_btn.clicked.connect(lambda: self.repair.emit(inst.get("name", "")))
        self.repair_btn.setVisible(needs_loader)
        top.addWidget(self.repair_btn, 0, Qt.AlignTop)

        self.del_btn = QPushButton("✕")
        self.del_btn.setObjectName("CardIcon")
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.setToolTip("删除实例")
        self.del_btn.clicked.connect(lambda: self.deleted.emit(inst.get("name", "")))
        top.addWidget(self.del_btn, 0, Qt.AlignTop)
        lay.addLayout(top)

        tags = QHBoxLayout()
        tags.setSpacing(5)
        tags.addWidget(Tag("已就绪" if inst.get("installed") else "缺文件", "ok" if inst.get("installed") else "dim"))
        tags.addWidget(Tag(f"{inst.get('modCount',0)} 模组"))
        if needs_loader:
            tags.addWidget(Tag("加载器未装", "warn"))
        if inst.get("loader") and inst["loader"] != "vanilla":
            tags.addWidget(Tag(loader_cn(inst["loader"]), "accent"))
        tags.addStretch(1)
        lay.addLayout(tags)

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self.inst.get("name", ""))
        super().mousePressEvent(ev)


def loader_cn(loader: str | None) -> str:
    return {"vanilla": "原版", "fabric": "Fabric", "forge": "Forge", "quilt": "Quilt",
            "neoforge": "NeoForge"}.get(loader or "vanilla", loader or "原版")


class Toast(QFrame):
    """右下角浮动提示，3 秒自动消失。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 10, 14, 10)
        self.setStyleSheet("QFrame#Card { background: #232733; border: 1px solid #2b3040; border-radius: 12px; }")
        self.hide()

    def show_message(self, text: str, kind: str = "") -> None:
        color = {"err": "#f87171", "ok": "#34d399"}.get(kind, "#e8e9f2")
        for i in reversed(range(self.lay.count())):
            w = self.lay.itemAt(i).widget()
            if w:
                w.deleteLater()
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{color}; font-size:12.5px;")
        lab.setMaximumWidth(360)
        self.lay.addWidget(lab)
        self.adjustSize()
        parent = self.parentWidget()
        if parent:
            self.move(parent.width() - self.width() - 24, parent.height() - self.height() - 24)
        self.show()
        self.raise_()
        QTimer.singleShot(3600, self.hide)
