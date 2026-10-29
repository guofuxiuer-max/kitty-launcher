"""启动闪屏：logo 淡入 + 进度条走完 600ms，再淡出交出主窗口。

为什么单独一个模块：闪屏必须在 App 构造之前就显示出来，
而 App 构造要读配置、扫 Java、扫实例（几百毫秒），正好用这段时间盖住。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap,
)
from PySide6.QtWidgets import QApplication, QWidget

from .paths import VERSION, asset_path

W, H = 440, 250


class SplashScreen(QWidget):
    finished = Signal()

    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.setWindowTitle("KittyLauncher")

        self.progress = 0.0
        self.fading = False
        self._started_at = 0.0
        self.min_show = 0.72   # 至少露个脸，别一闪而过
        logo = asset_path("logo.png")
        self.logo = QPixmap(str(logo)) if logo else QPixmap()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(240)
        self._fade.setEasingCurve(QEasingCurve.InOutQuad)
        self._fade.finished.connect(self._on_faded)

    # ---------------- 生命周期
    def start(self) -> None:
        import time

        self._started_at = time.time()
        self.setWindowOpacity(0.0)
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - W // 2, geo.center().y() - H // 2)
        self.show()

        fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        fade_in.setDuration(220)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)
        fade_in.start(QPropertyAnimation.DeleteWhenStopped)

    def _tick(self) -> None:
        if self.fading:
            return
        self.progress = min(1.0, self.progress + 16 / 600.0)
        self.update()
        if self.progress >= 1.0:
            self.finish()

    def finish(self) -> None:
        if self.fading:
            return
        import time

        early = self._started_at + self.min_show - time.time()
        if early > 0.05:
            QTimer.singleShot(int(early * 1000), self._do_fade)
        else:
            self._do_fade()

    def _do_fade(self) -> None:
        if self.fading:
            return
        self.fading = True
        self._timer.stop()
        self._fade.setStartValue(max(0.05, self.windowOpacity()))
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_faded(self) -> None:
        self.hide()
        self.finished.emit()

    # ---------------- 绘制
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        card = QRectF(6, 6, W - 12, H - 12)
        path = QPainterPath()
        path.addRoundedRect(card, 22, 22)

        bg = QLinearGradient(0, 0, W, H)
        bg.setColorAt(0.0, QColor("#1d2029"))
        bg.setColorAt(0.55, QColor("#16181f"))
        bg.setColorAt(1.0, QColor("#101116"))
        p.fillPath(path, bg)

        # 顶部一抹紫粉光
        glow = QLinearGradient(0, 0, W, 0)
        glow.setColorAt(0.0, QColor(168, 85, 247, 90))
        glow.setColorAt(0.6, QColor(236, 72, 153, 40))
        glow.setColorAt(1.0, QColor(236, 72, 153, 0))
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, W, 3), glow)
        p.restore()

        p.setPen(QColor(168, 85, 247, 80))
        p.drawPath(path)

        # logo
        if not self.logo.isNull():
            side = 92
            scaled = self.logo.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((W - side) // 2, 38, scaled)
        else:
            p.setPen(QColor("#e8e9f2"))
            f = QFont()
            f.setPointSize(46)
            p.setFont(f)
            p.drawText(QRectF(0, 38, W, 92), Qt.AlignCenter, "🐱")

        # 标题
        p.setPen(QColor("#e8e9f2"))
        f = QFont()
        f.setPointSize(19)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.drawText(QRectF(0, 142, W, 28), Qt.AlignCenter, "KittyLauncher")

        # 副标题
        p.setPen(QColor("#9498ac"))
        f = QFont()
        f.setPointSize(10)
        p.setFont(f)
        p.drawText(QRectF(0, 168, W, 20), Qt.AlignCenter, f"macOS 专用的 Minecraft 启动器 · v{VERSION}")

        # 进度条
        bar = QRectF(70, H - 42, W - 140, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(bar, 2, 2)

        if self.progress > 0:
            fill = QRectF(bar.x(), bar.y(), bar.width() * self.progress, bar.height())
            grad = QLinearGradient(fill.left(), 0, fill.right(), 0)
            grad.setColorAt(0.0, QColor("#a855f7"))
            grad.setColorAt(1.0, QColor("#ec4899"))
            p.setBrush(grad)
            p.drawRoundedRect(fill, 2, 2)
        p.end()


def show_splash() -> SplashScreen | None:
    """显示闪屏；返回对象，调用 finish() 或等它自己结束。"""
    try:
        splash = SplashScreen()
        splash.start()
        QApplication.processEvents()
        return splash
    except Exception:
        return None
