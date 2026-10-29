"""3D 皮肤渲染：正交投影 + 每个面做四点透视映射，纯 Qt，不用 OpenGL。

思路：
    1. 把皮肤拆成 6 个长方体部件（头 / 身 / 双臂 / 双腿）
    2. 每个部件的 6 个面都有标准 UV 区域
    3. 按 yaw/pitch 旋转 3D 顶点 → 正交投影到 2D → 得到 4 个屏幕坐标
    4. 用 QTransform.quadToQuad 把「皮肤上的那个矩形」映射到这个四边形上
    5. 所有面按深度排序后依次画（画家算法），足够画一个方块小人

坐标系：y 向上，脚底 y=0，头顶 y=32；1 单位 = 1 像素（16 单位 = 1 格）。
"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap, QPolygonF, QTransform

# 每个面的 UV 区域：(u, v, w, h)
HEAD_UV = {
    "front": (8, 8, 8, 8), "right": (0, 8, 8, 8), "back": (24, 8, 8, 8),
    "left": (16, 8, 8, 8), "top": (8, 0, 8, 8), "bottom": (16, 0, 8, 8),
}
HEAD_OV = {
    "front": (40, 8, 8, 8), "right": (32, 8, 8, 8), "back": (56, 8, 8, 8),
    "left": (48, 8, 8, 8), "top": (40, 0, 8, 8), "bottom": (48, 0, 8, 8),
}
BODY_UV = {
    "front": (20, 20, 8, 12), "right": (16, 20, 4, 12), "back": (32, 20, 8, 12),
    "left": (28, 20, 4, 12), "top": (20, 16, 8, 4), "bottom": (28, 16, 8, 4),
}
BODY_OV = {
    "front": (20, 36, 8, 12), "right": (16, 36, 4, 12), "back": (32, 36, 8, 12),
    "left": (28, 36, 4, 12), "top": (20, 32, 8, 4), "bottom": (28, 32, 8, 4),
}
RARM_UV = {
    "front": (44, 20, 4, 12), "right": (40, 20, 4, 12), "back": (56, 20, 4, 12),
    "left": (52, 20, 4, 12), "top": (44, 16, 4, 4), "bottom": (48, 16, 4, 4),
}
RARM_OV = {
    "front": (44, 36, 4, 12), "right": (40, 36, 4, 12), "back": (56, 36, 4, 12),
    "left": (52, 36, 4, 12), "top": (44, 32, 4, 4), "bottom": (48, 32, 4, 4),
}
LARM_UV = {
    "front": (36, 52, 4, 12), "right": (32, 52, 4, 12), "back": (48, 52, 4, 12),
    "left": (44, 52, 4, 12), "top": (36, 48, 4, 4), "bottom": (40, 48, 4, 4),
}
LARM_OV = {
    "front": (52, 52, 4, 12), "right": (48, 52, 4, 12), "back": (64, 52, 4, 12),
    "left": (60, 52, 4, 12), "top": (52, 48, 4, 4), "bottom": (56, 48, 4, 4),
}
RLEG_UV = {
    "front": (4, 20, 4, 12), "right": (0, 20, 4, 12), "back": (16, 20, 4, 12),
    "left": (12, 20, 4, 12), "top": (4, 16, 4, 4), "bottom": (8, 16, 4, 4),
}
RLEG_OV = {
    "front": (4, 36, 4, 12), "right": (0, 36, 4, 12), "back": (16, 36, 4, 12),
    "left": (12, 36, 4, 12), "top": (4, 32, 4, 4), "bottom": (8, 32, 4, 4),
}
LLEG_UV = {
    "front": (20, 52, 4, 12), "right": (16, 52, 4, 12), "back": (32, 52, 4, 12),
    "left": (28, 52, 4, 12), "top": (20, 48, 4, 4), "bottom": (24, 48, 4, 4),
}
LLEG_OV = {
    "front": (4, 52, 4, 12), "right": (0, 52, 4, 12), "back": (52, 52, 4, 12),
    "left": (48, 52, 4, 12), "top": (4, 48, 4, 4), "bottom": (8, 48, 4, 4),
}

SHADE = {"front": 1.0, "back": 0.78, "left": 0.86, "right": 0.86, "top": 1.0, "bottom": 0.6}

PARTS = [
    {"name": "head", "size": (8, 8, 8), "pos": (0, 28, 0), "uv": HEAD_UV, "ov": HEAD_OV},
    {"name": "body", "size": (8, 12, 4), "pos": (0, 18, 0), "uv": BODY_UV, "ov": BODY_OV},
    {"name": "rarm", "size": (4, 12, 4), "pos": (6, 18, 0), "uv": RARM_UV, "ov": RARM_OV},
    {"name": "larm", "size": (4, 12, 4), "pos": (-6, 18, 0), "uv": LARM_UV, "ov": LARM_OV},
    {"name": "rleg", "size": (4, 12, 4), "pos": (2, 6, 0), "uv": RLEG_UV, "ov": RLEG_OV},
    {"name": "lleg", "size": (4, 12, 4), "pos": (-2, 6, 0), "uv": LLEG_UV, "ov": LLEG_OV},
]


def _face_quads(hx: float, hy: float, hz: float) -> dict[str, list[tuple[float, float, float]]]:
    """六个面的 4 个角（顺序：左上、右上、右下、左下）。"""
    return {
        "front": [(-hx, hy, hz), (hx, hy, hz), (hx, -hy, hz), (-hx, -hy, hz)],
        "right": [(hx, hy, hz), (hx, hy, -hz), (hx, -hy, -hz), (hx, -hy, hz)],
        "back": [(hx, hy, -hz), (-hx, hy, -hz), (-hx, -hy, -hz), (hx, -hy, -hz)],
        "left": [(-hx, hy, -hz), (-hx, hy, hz), (-hx, -hy, hz), (-hx, -hy, -hz)],
        "top": [(-hx, hy, hz), (hx, hy, hz), (hx, hy, -hz), (-hx, hy, -hz)],
        "bottom": [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz)],
    }


def _rotate(p: tuple[float, float, float], yaw: float, pitch: float) -> tuple[float, float, float]:
    x, y, z = p
    cy, sy = math.cos(yaw), math.sin(yaw)
    x, z = x * cy + z * sy, -x * sy + z * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = y * cp - z * sp, y * sp + z * cp
    return x, y, z


def parts_for(slim: bool = False) -> list[dict]:
    """slim（Alex）模型手臂只有 3 宽，位置也要往里收 0.5。"""
    out = []
    for part in PARTS:
        if slim and part["name"] in ("rarm", "larm"):
            sign = 1 if part["name"] == "rarm" else -1
            out.append({**part, "size": (3, 12, 4), "pos": (sign * 5.5, 18, 0)})
        else:
            out.append(part)
    return out


def render(
    skin_path: Path | str,
    width: int = 300,
    height: int = 420,
    yaw_deg: float = 25.0,
    pitch_deg: float = 6.0,
    scale: float = 1.0,
    overlays: bool = True,
    slim: bool = False,
) -> QPixmap:
    img = QImage(str(skin_path))
    if img.isNull():
        return QPixmap()

    legacy = img.height() < 64
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)

    # 先把所有面算成 {depth, polygon, uv}
    faces: list[dict] = []
    for part in parts_for(slim):
        sx, sy, sz = part["size"]
        px, py, pz = part["pos"]
        uv_base = part["uv"]
        if legacy and part["name"] == "larm":
            uv_base = RARM_UV   # 64×32 老皮肤没有左臂，用右臂顶替
        elif legacy and part["name"] == "lleg":
            uv_base = RLEG_UV
        variants = [(1.0, uv_base)]
        if overlays and not legacy:
            variants.append((1.12, part["ov"]))  # 叠加层稍微放大一点，避免和本体 z-fighting

        for inflate, uvmap in variants:
            hx, hy, hz = sx * inflate / 2, sy * inflate / 2, sz * inflate / 2
            quads = _face_quads(hx, hy, hz)
            for face, corners in quads.items():
                uv = uvmap.get(face)
                if not uv:
                    continue
                pts3 = [(x + px, y + py, z + pz) for (x, y, z) in corners]
                rot = [_rotate(p, yaw, pitch) for p in pts3]
                depth = sum(p[2] for p in rot) / 4.0
                # UV 顺序：左上、右上、右下、左下
                u, v, uw, uh = uv
                faces.append({
                    "depth": depth,
                    "pts": rot,
                    "uv": (u, v, uw, uh),
                    "shade": SHADE.get(face, 1.0),
                })

    # 远的先画
    faces.sort(key=lambda f: f["depth"])

    pm = QPixmap(width, height)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, False)  # 像素风要硬边

    # 按投影后的包围盒居中，避免不同角度/身高时跑出画布
    xs = [pt.x() for face in faces for pt in [QPointF(x, -y) for (x, y, _z) in face["pts"]]]
    ys = [pt.y() for face in faces for pt in [QPointF(x, -y) for (x, y, _z) in face["pts"]]]
    if not xs:
        p.end()
        return pm
    span_x = max(xs) - min(xs) or 1.0
    span_y = max(ys) - min(ys) or 1.0
    base = min(width * 0.82 / span_x, height * 0.86 / span_y) * scale
    cx = width / 2.0 - (min(xs) + max(xs)) / 2.0 * base
    cy = height / 2.0 - (min(ys) + max(ys)) / 2.0 * base

    for face in faces:
        src = QPolygonF([
            QPointF(face["uv"][0], face["uv"][1]),
            QPointF(face["uv"][0] + face["uv"][2], face["uv"][1]),
            QPointF(face["uv"][0] + face["uv"][2], face["uv"][1] + face["uv"][3]),
            QPointF(face["uv"][0], face["uv"][1] + face["uv"][3]),
        ])
        dst = QPolygonF([QPointF(cx + x * base, cy - y * base) for (x, y, _z) in face["pts"]])

        # 退化（侧到看不见）就跳过
        area = abs(
            (dst[1].x() - dst[0].x()) * (dst[3].y() - dst[0].y())
            - (dst[3].x() - dst[0].x()) * (dst[1].y() - dst[0].y())
        )
        if area < 0.6:
            continue

        transform = QTransform()
        if not QTransform.quadToQuad(src, dst, transform):
            continue
        p.save()
        p.setTransform(transform, True)
        u, v, uw, uh = face["uv"]
        p.drawImage(QRectF(u, v, uw, uh), img, QRectF(u, v, uw, uh))
        p.restore()

        shade = face.get("shade", 1.0)
        if shade < 1.0:
            path = QPainterPath()
            path.addPolygon(dst)
            path.closeSubpath()
            p.fillPath(path, QColor(0, 0, 0, int(255 * (1.0 - shade) * 0.55)))

    p.end()
    return pm


def render_angles(skin_path: Path | str, out_dir: Path | str, yaw_list=(0, 35, 70, 135, 180), size=(240, 340)) -> list[Path]:
    """调试/截图用：转一圈各存一张。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for yaw in yaw_list:
        pm = render(skin_path, size[0], size[1], yaw_deg=yaw, pitch_deg=8)
        p = out_dir / f"skin3d-yaw{yaw}.png"
        pm.save(str(p), "PNG")
        paths.append(p)
    return paths


# ---------------------------------------------------------------- 交互控件

try:
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QWidget

    class Skin3DView(QWidget):
        """可拖拽旋转、滚轮缩放、自动转圈的 3D 皮肤视图。"""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.skin_path: Path | str = ""
            self.slim = False
            self.yaw = 25.0
            self.pitch = 6.0
            self.zoom = 1.0
            self._drag = None
            self.setMinimumSize(220, 340)
            self.setCursor(Qt.OpenHandCursor)
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._spin)
            self._timer.start(50)
            self.auto = True

        # ---- 数据
        def set_skin(self, path: Path | str, slim: bool = False) -> None:
            self.skin_path = path or ""
            self.slim = slim
            self.update()

        def reset_view(self) -> None:
            self.yaw, self.pitch, self.zoom = 25.0, 6.0, 1.0
            self.update()

        def toggle_auto(self) -> bool:
            self.auto = not self.auto
            return self.auto

        # ---- 动画
        def _spin(self) -> None:
            if self.auto and self.isVisible():
                self.yaw = (self.yaw + 1.1) % 360
                self.update()

        # ---- 绘制
        def paintEvent(self, event):  # noqa: N802
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            if not self.skin_path:
                p.setPen(QColor("#9498ac"))
                p.drawText(self.rect(), Qt.AlignCenter, "还没有皮肤")
                p.end()
                return
            pm = render(
                self.skin_path, self.width(), self.height(),
                yaw_deg=self.yaw, pitch_deg=self.pitch, scale=self.zoom,
                slim=self.slim,
            )
            if not pm.isNull():
                p.drawPixmap(0, 0, pm)
            p.end()

        # ---- 交互
        def mousePressEvent(self, event):  # noqa: N802
            if event.button() == Qt.LeftButton:
                self._drag = event.position().toPoint()
                self.setCursor(Qt.ClosedHandCursor)

        def mouseMoveEvent(self, event):  # noqa: N802
            if self._drag is None:
                return
            pos = event.position().toPoint()
            self.yaw += (pos.x() - self._drag.x()) * 0.7
            self.pitch = max(-40.0, min(40.0, self.pitch + (pos.y() - self._drag.y()) * 0.4))
            self._drag = pos
            self.update()

        def mouseReleaseEvent(self, event):  # noqa: N802
            self._drag = None
            self.setCursor(Qt.OpenHandCursor)

        def wheelEvent(self, event):  # noqa: N802
            delta = 1.0 if event.angleDelta().y() > 0 else -1.0
            self.zoom = max(0.6, min(2.2, self.zoom + delta * 0.08))
            self.update()

        def mouseDoubleClickEvent(self, event):  # noqa: N802
            self.toggle_auto()

except Exception:  # pragma: no cover - 只有无 Qt 环境才会走到
    Skin3DView = None  # type: ignore[assignment]
