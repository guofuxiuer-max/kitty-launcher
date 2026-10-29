"""两个对话框：实例设置（PCL 的「版本设置」）和日志诊断。

对话框作为主窗口的子控件创建，样式表会自动继承，不用重复写 QSS。
"""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QComboBox, QVBoxLayout, QWidget,
)

from . import core


class InstanceSettingsDialog(QDialog):
    """实例级覆盖：内存 / 窗口 / Java / JVM 参数 / 游戏参数。0 或空 = 跟随全局。"""

    def __init__(self, host, name: str, parent=None):
        super().__init__(parent or host)
        self.host = host
        self.name = name
        self.inst = core.get_instance(name)
        self.setWindowTitle(f"实例设置 · {name}")
        self.setMinimumWidth(580)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        title = QLabel(name)
        title.setObjectName("HeroTitle")
        title.setStyleSheet("font-size:18px;")
        lay.addWidget(title)

        sub = QLabel(
            f"{self.inst.get('mcVersion', '?')} · {self.inst.get('loader', 'vanilla')} · "
            f"{self.inst.get('versionId', '')}"
        )
        sub.setObjectName("Hint")
        lay.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.mem = QSpinBox()
        self.mem.setRange(0, 65536)
        self.mem.setSingleStep(512)
        self.mem.setSpecialValueText("跟随全局")
        self.mem.setSuffix(" MB")

        self.width = QSpinBox()
        self.width.setRange(0, 5120)
        self.width.setSingleStep(64)
        self.width.setSpecialValueText("跟随全局")

        self.height = QSpinBox()
        self.height.setRange(0, 2880)
        self.height.setSingleStep(64)
        self.height.setSpecialValueText("跟随全局")

        self.java = QComboBox()
        self.java.addItem("跟随全局", "")
        for j in core.list_java():
            self.java.addItem(f"Java {j['major']} · {j['vendor']} · {j['version']}", j["path"])

        self.jvm = QLineEdit()
        self.jvm.setPlaceholderText("-XX:+UseG1GC -XX:MaxGCPauseMillis=50（追加到全局之后）")
        self.game = QLineEdit()
        self.game.setPlaceholderText("--width 1280 --height 720，或 --server mc.example.com")

        form.addRow(self._lab("内存上限"), self.mem)
        row = QHBoxLayout()
        row.addWidget(self.width)
        row.addWidget(QLabel("×"))
        row.addWidget(self.height)
        row.addStretch(1)
        form.addRow(self._lab("窗口尺寸"), self._wrap(row))
        form.addRow(self._lab("Java"), self.java)
        form.addRow(self._lab("JVM 参数"), self.jvm)
        form.addRow(self._lab("游戏参数"), self.game)
        lay.addLayout(form)

        self.modpack = QLabel("")
        self.modpack.setObjectName("Hint")
        lay.addWidget(self.modpack)

        # 预填
        s = self.inst.get("settings") or {}
        self.mem.setValue(int(s.get("memoryMB") or 0))
        self.width.setValue(int(s.get("width") or 0))
        self.height.setValue(int(s.get("height") or 0))
        idx = self.java.findData(s.get("javaPath") or "")
        self.java.setCurrentIndex(max(0, idx))
        self.jvm.setText(s.get("jvmArgs") or "")
        self.game.setText(s.get("gameArgs") or "")
        if self.inst.get("modpack"):
            mp = self.inst["modpack"]
            self.modpack.setText(f"来自整合包：{mp.get('name', '')} {mp.get('version', '')}")

        lay.addStretch(1)
        btns = QHBoxLayout()
        export = QPushButton("导出实例…")
        export.setObjectName("Ghost")
        export.clicked.connect(self.do_export)
        open_dir = QPushButton("打开目录")
        open_dir.setObjectName("Ghost")
        open_dir.clicked.connect(lambda: core.open_path(str(core.instance_dir(name))))
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self.do_save)
        btns.addWidget(export)
        btns.addWidget(open_dir)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(save)
        lay.addLayout(btns)

    @staticmethod
    def _lab(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("Hint")
        return lab

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return w

    def do_save(self) -> None:
        core.update_instance_settings(self.name, {
            "memoryMB": self.mem.value(),
            "width": self.width.value(),
            "height": self.height.value(),
            "javaPath": self.java.currentData() or "",
            "jvmArgs": self.jvm.text().strip(),
            "gameArgs": self.game.text().strip(),
        })
        self.host.toast("实例设置已保存", "ok")
        self.host.refresh_all()
        self.accept()

    def do_export(self) -> None:
        default = str(Path.home() / f"{self.name}.zip")
        path, _ = QFileDialog.getSaveFileName(self, "导出实例", default, "Zip 压缩包 (*.zip)")
        if not path:
            return
        r = core.export_instance(self.name, path)
        if r.get("ok"):
            self.host.toast(f"已导出：{Path(r['path']).name}（{r['size'] // 1024} KB）", "ok")
        else:
            self.host.toast(r.get("error", "导出失败"), "err")


class DiagnosisDialog(QDialog):
    """把日志里的常见错误翻译成中文 + 给修法（PCL 的招牌功能之一）。"""

    def __init__(self, host, name: str, parent=None):
        super().__init__(parent or host)
        self.host = host
        self.name = name
        self.setWindowTitle(f"日志诊断 · {name}")
        self.resize(760, 560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        data = core.diagnose_instance(name)
        self.text = ""
        body = QPlainTextEdit()
        body.setObjectName("Log")
        body.setReadOnly(True)

        if data.get("error"):
            header = QLabel(data["error"])
            header.setObjectName("Hint")
            lay.addWidget(header)
            body.setPlainText("没有日志可分析。先在启动页启动一次游戏，哪怕启动失败也会留下日志。")
        else:
            issues = data["issues"]
            summary = QLabel(
                f"日志：{data['file']}\n共 {data['lines']} 行 · 命中 {len(issues)} 条已知问题"
                + (f" · 崩溃报告：{Path(data['crashPath']).name}" if data.get("crashPath") else "")
            )
            summary.setObjectName("Hint")
            summary.setWordWrap(True)
            lay.addWidget(summary)
            body.setPlainText(self._render(data))
            self.text = self._render(data)

        lay.addWidget(body, 1)

        btns = QHBoxLayout()
        open_log = QPushButton("打开日志目录")
        open_log.setObjectName("Ghost")
        open_log.clicked.connect(lambda: core.open_path(str(core.instance_dir(name) / "logs")))
        copy = QPushButton("复制诊断")
        copy.setObjectName("Ghost")
        copy.clicked.connect(self.do_copy)
        close = QPushButton("关闭")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        btns.addWidget(open_log)
        btns.addWidget(copy)
        btns.addStretch(1)
        btns.addWidget(close)
        lay.addLayout(btns)

    @staticmethod
    def _render(data: dict) -> str:
        out: list[str] = []
        if data.get("header"):
            out.append("—— 运行信息 ——")
            out.extend("  " + h for h in data["header"])
            out.append("")

        if not data["issues"]:
            out.append("—— 结论 ——")
            out.append("  没命中任何已知故障特征，日志看起来是正常的一次启动/退出。")
            out.append("  如果游戏确实有问题，把这份日志提到 issue 里，我再加规则。")
            return "\n".join(out)

        out.append("—— 诊断 ——")
        for i, issue in enumerate(data["issues"], 1):
            mark = "❌" if issue["level"] == "err" else "⚠️"
            out.append(f"{mark} {i}. {issue['title']}")
            out.append(f"   原因：{issue['detail']}")
            out.append(f"   修法：{issue['fix']}")
            if issue.get("evidence"):
                out.append(f"   日志：{issue['evidence']}")
            out.append("")
        out.append("—— 下一步 ——")
        out.append("  照着「修法」改完再启动一次；还不行就把这份诊断贴进 issue。")
        return "\n".join(out)

    def do_copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.text or "（没有可复制的诊断）")
        self.host.toast("诊断结果已复制", "ok")
