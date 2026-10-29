"""皮肤解析 + 纯 Qt 渲染（不引第三方图片库）。

取皮肤的顺序：
    1. 已登录微软账号 profile 里的 skins[].url（最准）
    2. 玩家名 → api.mojang.com 查 uuid → sessionserver 拿 textures
    3. 都失败 → 本地生成一张占位皮肤（保证界面永远有东西看）

渲染：
    head()  只画正脸（含帽子层）
    body()  把皮肤图按标准 UV 拼成 16×32 的「正面站姿」，再整体放大
            皮肤图 64×32 是 legacy 格式，没有左右手脚分层，用镜像补
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

import requests
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from .paths import DATA

CACHE_DIR = DATA / "cache" / "skins"
UA = {"User-Agent": "KittyLauncher/1.0.0"}
TTL = 24 * 3600
TIMEOUT = 15


# ---------------------------------------------------------------- 取皮肤

def _cache_file(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{hashlib.sha1(key.encode()).hexdigest()}.png"


def _fresh(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 100 and (time.time() - path.stat().st_mtime) < TTL


def _download(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        if r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n":
            return r.content
    except Exception:
        return None
    return None


def _name_to_uuid(name: str) -> str:
    try:
        r = requests.get(f"https://api.mojang.com/users/profiles/minecraft/{name}", headers=UA, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json().get("id", "")
    except Exception:
        pass
    return ""


def _uuid_to_skin(uuid: str) -> tuple[str, str]:
    """返回 (皮肤 URL, 模型 classic/slim)。"""
    if not uuid:
        return "", "classic"
    try:
        r = requests.get(
            f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid}",
            headers=UA,
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return "", "classic"
        data = r.json()
        for prop in data.get("properties", []):
            if prop.get("name") != "textures":
                continue
            tex = json.loads(base64.b64decode(prop["value"]).decode("utf-8"))
            skin = (tex.get("textures") or {}).get("SKIN") or {}
            model = (skin.get("metadata") or {}).get("model", "classic")
            return skin.get("url", ""), model
    except Exception:
        pass
    return "", "classic"


def placeholder_skin() -> Path:
    """画一张最朴素的皮肤，网络不通时也能预览。"""
    path = CACHE_DIR / "placeholder.png"
    if path.exists():
        return path
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    img = QImage(64, 64, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))

    def rect(x, y, w, h, color):
        p = QPainter(img)
        p.fillRect(QRect(x, y, w, h), QColor(color))
        p.end()

    skin = "#c69c6d"
    dark = "#b0895f"
    shirt = "#3fa9f5"
    pants = "#3b4a6b"
    # 头
    rect(8, 8, 8, 8, skin)
    rect(8, 8, 8, 2, dark)          # 头发
    rect(10, 11, 1, 1, "#2b2b2b")   # 眼
    rect(13, 11, 1, 1, "#2b2b2b")
    rect(8, 40, 8, 8, skin)
    # 身体
    rect(20, 20, 8, 12, shirt)
    # 右臂 / 腿
    rect(44, 20, 4, 12, shirt)
    rect(4, 20, 4, 12, pants)
    # 左臂 / 腿（legacy 用镜像，这里直接填一份）
    rect(36, 52, 4, 12, shirt)
    rect(20, 52, 4, 12, pants)
    img.save(str(path), "PNG")
    return path


def resolve(name: str = "") -> dict:
    """找一张能用的皮肤，返回 {path, source, name, uuid, model, error}。"""
    from . import auth, core

    acc = None
    try:
        acc = auth.active_account()
    except Exception:
        acc = None

    # 1) 微软账号档案里直接带了皮肤 URL
    if acc and not name:
        skins = acc.get("skins") or []
        url = skins[0].get("url") if skins else ""
        if url:
            target = _cache_file(url)
            if not _fresh(target):
                data = _download(url)
                if data:
                    target.write_bytes(data)
            if target.exists():
                return {
                    "path": target, "source": "微软账号档案", "name": acc.get("name", ""),
                    "uuid": acc.get("uuid", ""), "model": "classic", "error": "",
                }

    # 2) 用玩家名查 Mojang 公开档案
    who = (name or (acc.get("name") if acc else "") or core.load_config().get("username") or "").strip()
    uuid = (acc.get("uuid") if acc and not name else "") or _name_to_uuid(who) if who else ""
    if uuid:
        url, model = _uuid_to_skin(uuid)
        if url:
            target = _cache_file(url)
            if not _fresh(target):
                data = _download(url)
                if data:
                    target.write_bytes(data)
            if target.exists():
                return {
                    "path": target, "source": "Mojang 公开档案", "name": who,
                    "uuid": uuid, "model": model, "error": "",
                }

    # 3) 兜底
    return {
        "path": placeholder_skin(),
        "source": "占位皮肤（没查到这个玩家的皮肤）",
        "name": who or "-",
        "uuid": uuid or "",
        "model": "classic",
        "error": "" if not who else f"没找到「{who}」的皮肤（离线名或网络不通）",
    }


# ---------------------------------------------------------------- 渲染

def _crop(img: QImage, x: int, y: int, w: int, h: int) -> QImage:
    return img.copy(QRect(x, y, w, h))


def head(path: Path | str, size: int = 96, hat: bool = True) -> QPixmap:
    img = QImage(str(path))
    if img.isNull():
        return QPixmap()
    face = _crop(img, 8, 8, 8, 8)
    if hat and img.height() >= 64:
        hat_layer = _crop(img, 40, 8, 8, 8)
        canvas = QImage(8, 8, QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)
        p = QPainter(canvas)
        p.drawImage(0, 0, face)
        p.drawImage(0, 0, hat_layer)
        p.end()
        out = canvas
    else:
        out = face
    return QPixmap.fromImage(out.scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation))


def body(path: Path | str, scale: int = 8, slim: bool = False) -> QPixmap:
    img = QImage(str(path))
    if img.isNull():
        return QPixmap()
    legacy = img.height() < 64

    canvas = QImage(16 * scale, 32 * scale, QImage.Format_ARGB32)
    canvas.fill(Qt.transparent)
    p = QPainter(canvas)

    def blit(x, y, w, h, dx, dy, alpha=True):
        p.drawImage(QRect(dx * scale, dy * scale, w * scale, h * scale), img, QRect(x, y, w, h))

    def mirror(x, y, w, h, dx, dy):
        piece = _crop(img, x, y, w, h).mirrored(True, False)
        p.drawImage(QRect(dx * scale, dy * scale, w * scale, h * scale), piece)

    # 头 + 帽子层
    blit(8, 8, 8, 8, 4, 0)
    if not legacy:
        blit(40, 8, 8, 8, 4, 0)

    # 身体 + 外套
    blit(20, 20, 8, 12, 4, 8)
    if not legacy:
        blit(20, 36, 8, 12, 4, 8)

    arm_w = 3 if slim else 4
    # 手臂贴着身体两侧：右臂右边缘贴 4，左臂左边缘贴 12
    r_dx = 4 - arm_w
    l_dx = 12
    # 右臂（画面左侧）+ 袖子
    blit(44, 20, arm_w, 12, r_dx, 8)
    if not legacy:
        blit(44, 36, arm_w, 12, r_dx, 8)
    # 左臂（画面右侧）：legacy 镜像右臂
    if legacy:
        mirror(44, 20, arm_w, 12, l_dx, 8)
    else:
        blit(36, 52, arm_w, 12, l_dx, 8)
        blit(52, 52, arm_w, 12, l_dx, 8)

    # 右腿 + 裤腿
    blit(4, 20, 4, 12, 4, 20)
    if not legacy:
        blit(4, 36, 4, 12, 4, 20)
    # 左腿
    if legacy:
        mirror(4, 20, 4, 12, 8, 20)
    else:
        blit(20, 52, 4, 12, 8, 20)
        blit(4, 52, 4, 12, 8, 20)

    p.end()
    return QPixmap.fromImage(canvas)


def render_to_file(path: Path | str, out: Path, scale: int = 10) -> dict:
    """调试用：把正面图存成 PNG。"""
    pm = body(path, scale)
    if pm.isNull():
        return {"error": "皮肤图读不出来"}
    pm.save(str(out), "PNG")
    return {"ok": True, "path": str(out), "size": [pm.width(), pm.height()]}
