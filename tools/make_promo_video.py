"""生成 KittyLauncher 演示视频（抖音竖屏 1080x1920）。

素材：screenshots/*.png（真实界面）+ skin3d 实时渲染 + say 中文配音 + numpy 合成纯音乐。
输出：docs/KittyLauncher-promo.mp4

用法：
    ./.venv/bin/python tools/make_promo_video.py --stills   # 每个镜头出一张静帧，先看设计
    ./.venv/bin/python tools/make_promo_video.py            # 渲染整片
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SHOTS_DIR = ROOT / "screenshots"
TMP = Path("/tmp/promo")
W, H = 1080, 1920
FPS = 30

FONT_CN = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    # Hiragino Sans GB.ttc 里 0=W3 1=W6
    return ImageFont.truetype(FONT_CN, size, index=1 if bold else 0)


# ---------------------------------------------------------------- 基础绘制

def vertical_bg() -> Image.Image:
    """深色渐变 + 顶部紫光 + 底部压暗。"""
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    top = np.array([22, 23, 32], dtype=np.float32)
    bottom = np.array([9, 10, 14], dtype=np.float32)
    base = top * (1 - y) + bottom * y
    img = np.repeat(base[:, None, :], W, axis=1)

    # 顶部紫粉光
    xs = np.linspace(0, 1, W, dtype=np.float32)[None, :]
    glow = np.exp(-((xs - 0.5) ** 2) / 0.16) * np.exp(-(y / 0.35))
    img += glow[:, :, None] * np.array([70, 30, 90], dtype=np.float32)

    # 暗角
    yy = np.linspace(-1, 1, H, dtype=np.float32)[:, None]
    xx = np.linspace(-1, 1, W, dtype=np.float32)[None, :]
    vig = 1 - 0.35 * np.clip((xx ** 2 + yy ** 2) / 2.0, 0, 1)
    img *= vig[:, :, None]

    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def drop_shadow(canvas: Image.Image, xy: tuple[int, int], size: tuple[int, int], radius: int = 28, spread: int = 40) -> None:
    """给面板画一圈柔和阴影。"""
    x, y = xy
    w, h = size
    layer = Image.new("RGBA", (w + spread * 2, h + spread * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([spread, spread, spread + w, spread + h], radius, fill=(0, 0, 0, 190))
    layer = layer.filter(ImageFilter.GaussianBlur(spread * 0.55))
    canvas.alpha_composite(layer, (x - spread, y - spread))


def paste_screenshot(canvas: Image.Image, shot: str, box_w: int, center: tuple[int, int], zoom: float = 1.0,
                     pan: tuple[float, float] = (0.0, 0.0), radius: int = 26,
                     cut: tuple[float, float, float, float] = (0, 0, 0, 0)) -> tuple[int, int, int, int]:
    """把界面截图按 zoom/pan 裁一块贴上去；cut=(左,上,右,下) 是相对裁边，先砍掉再缩放。"""
    src = Image.open(SHOTS_DIR / shot).convert("RGB")
    sw, sh = src.size
    cut_dx = cut_dy = 0
    if any(cut):
        l, t, r, b = cut
        cut_dx, cut_dy = int(sw * l), int(sh * t)
        src = src.crop((cut_dx, cut_dy, int(sw * (1 - r)), int(sh * (1 - b))))
        sw, sh = src.size
    cw = int(sw / zoom)
    ch = int(cw * sh / sw)
    cx = sw / 2 + pan[0] * (sw - cw) / 2
    cy = sh / 2 + pan[1] * (sh - ch) / 2
    left = int(np.clip(cx - cw / 2, 0, sw - cw))
    top = int(np.clip(cy - ch / 2, 0, sh - ch))
    crop = src.crop((left, top, left + cw, top + ch))

    disp_w = box_w
    disp_h = int(ch * disp_w / cw)
    crop = crop.resize((disp_w, disp_h), Image.LANCZOS)
    crop = rounded(crop, radius)

    x = center[0] - disp_w // 2
    y = center[1] - disp_h // 2
    drop_shadow(canvas, (x, y), (disp_w, disp_h), radius)
    # 细边框
    border = Image.new("RGBA", (disp_w, disp_h), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle([0, 0, disp_w - 1, disp_h - 1], radius, outline=(255, 255, 255, 40), width=2)
    canvas.alpha_composite(crop, (x, y))
    canvas.alpha_composite(border, (x, y))
    _LAST.update({"x": x, "y": y, "scale": disp_w / src.width, "dx": cut_dx, "dy": cut_dy})
    return (x, y, x + disp_w, y + disp_h)


def text_center(canvas: Image.Image, y: int, text: str, size: int, color=(255, 255, 255), bold=True,
                alpha: int = 255, stroke: int = 0) -> None:
    d = ImageDraw.Draw(canvas)
    f = font(size, bold)
    if stroke:
        d.text((W // 2, y), text, font=f, fill=color + (alpha,), anchor="ma",
               stroke_width=stroke, stroke_fill=(0, 0, 0, alpha))
    else:
        d.text((W // 2, y), text, font=f, fill=color + (alpha,), anchor="ma")


def pill(canvas: Image.Image, y: int, text: str, size: int = 40, alpha: int = 230) -> None:
    """底部字幕胶囊。"""
    d = ImageDraw.Draw(canvas)
    f = font(size)
    max_w = W - 120
    lines, cur = [], ""
    for ch in text:
        if ImageDraw.Draw(canvas).textlength(cur + ch, font=f) > max_w - 60:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    line_h = size + 14
    box_h = line_h * len(lines) + 34
    box_w = max(ImageDraw.Draw(canvas).textlength(l, font=f) for l in lines) + 60
    x0, y0 = (W - box_w) // 2, y
    layer = Image.new("RGBA", (int(box_w), int(box_h)), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([0, 0, box_w - 1, box_h - 1], 26, fill=(12, 13, 18, 200),
                                            outline=(168, 85, 247, 90), width=2)
    canvas.alpha_composite(layer, (int(x0), int(y0)))
    for i, line in enumerate(lines):
        d.text((W // 2, y0 + 17 + i * line_h), line, font=f, fill=(240, 240, 245, alpha), anchor="ma")


class Danmaku:
    """从右往左飘的弹幕，带描边。"""

    def __init__(self, items: list[tuple[float, str, int]]):
        # items: (出场时间秒, 文本, 泳道)
        self.items = items

    def draw(self, canvas: Image.Image, t: float, top: int = 210, lane_h: int = 78) -> None:
        d = ImageDraw.Draw(canvas)
        for start, text, lane in self.items:
            if t < start:
                continue
            life = t - start
            f = font(38)
            tw = d.textlength(text, font=f)
            x = W + 40 - life * 380
            if x + tw < -40:
                continue
            y = top + (lane % 3) * lane_h
            alpha = 235 if life < 6.5 else max(0, int(235 * (1 - (life - 6.5) / 1.5)))
            d.text((x, y), text, font=f, fill=(255, 255, 255, alpha),
                   stroke_width=3, stroke_fill=(0, 0, 0, alpha))


def cursor(canvas: Image.Image, x: int, y: int, click: float = 0.0) -> None:
    """画一个 macOS 风格箭头，click>0 时画扩散圈。"""
    if click > 0:
        r = int(14 + click * 34)
        d = ImageDraw.Draw(canvas)
        d.ellipse([x - r, y - r, x + r, y + r], outline=(168, 85, 247, int(200 * (1 - click))), width=4)
    pts = [(x, y), (x, y + 42), (x + 11, y + 32), (x + 19, y + 50), (x + 28, y + 45), (x + 20, y + 28), (x + 34, y + 26)]
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.polygon(pts, fill=(255, 255, 255, 255), outline=(20, 20, 25, 255))
    canvas.alpha_composite(layer)


def highlight(canvas: Image.Image, rect: tuple[int, int, int, int], t: float, color=(168, 85, 247)) -> None:
    """呼吸高亮框。"""
    x0, y0, x1, y1 = rect
    a = 120 + int(80 * (0.5 + 0.5 * math.sin(t * 6)))
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([x0 - 8, y0 - 8, x1 + 8, y1 + 8], 20, outline=color + (a,), width=4)
    canvas.alpha_composite(layer)


# ---------------------------------------------------------------- 音频

SR = 44100


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        n = w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            data = data.reshape(-1, 2).mean(axis=1)
    return data


def make_music(total: float) -> np.ndarray:
    """一段干净的纯音乐：Am - F - C - G 的柔和 pad + 稀疏拨弦。"""
    n = int(total * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)

    chords = [
        (220.00, [220.00, 261.63, 329.63]),   # Am
        (174.61, [174.61, 220.00, 261.63]),   # F
        (130.81, [130.81, 164.81, 196.00]),   # C
        (196.00, [196.00, 246.94, 293.66]),   # G
    ]
    bar = 3.2  # 每小节 3.2 秒

    idx = 0
    while idx * bar < total:
        chord = chords[int(idx) % 4]
        start = idx * bar
        seg_t = np.arange(int(bar * SR)) / SR
        env = np.clip(seg_t / 0.8, 0, 1) * np.clip((bar - seg_t) / 1.0, 0, 1)
        pad = np.zeros_like(seg_t)
        for f in chord[1]:
            pad += np.sin(2 * np.pi * f * seg_t) * 0.5
            pad += np.sin(2 * np.pi * f * 1.004 * seg_t) * 0.3
        pad *= env * 0.055
        s0 = int(start * SR)
        s1 = min(n, s0 + len(pad))
        out[s0:s1] += pad[: s1 - s0]

        # 拨弦（每小节 4 下，错拍）
        for beat in range(4):
            bt = start + beat * bar / 4 + 0.12
            if bt >= total:
                break
            dur = 0.9
            st = np.arange(int(dur * SR)) / SR
            f0 = chord[1][beat % 3] * 2
            pluck = np.sin(2 * np.pi * f0 * st) * np.exp(-st * 4.2) * 0.07
            pluck += np.sin(2 * np.pi * f0 * 2 * st) * np.exp(-st * 7) * 0.02
            p0 = int(bt * SR)
            p1 = min(n, p0 + len(pluck))
            out[p0:p1] += pluck[: p1 - p0]
        idx += 1

    # 整体淡入淡出
    fade = int(1.2 * SR)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    return out


def build_audio(timeline: list[dict], total: float, out_path: Path) -> None:
    n = int(total * SR) + SR
    vo_track = np.zeros(n, dtype=np.float32)
    for seg in timeline:
        path = TMP / "wav" / f"{seg['vo']}.wav"
        if not path.exists():
            continue
        data = load_wav(path)
        s = int((seg["start"] + 0.25) * SR)
        e = min(n, s + len(data))
        vo_track[s:e] += data[: e - s] * 1.0

    music = make_music(total + 1)
    m = np.zeros(n, dtype=np.float32)
    m[: len(music)] = music[:n]
    mix = vo_track * 0.92 + m * 0.55
    # 归一化到 -1 dBFS 附近，手机外放才够响
    peak = float(np.abs(mix).max()) or 1.0
    mix = np.tanh(mix / peak * 1.15) * 0.94
    mix = np.clip(mix, -1, 1)
    stereo = np.stack([mix, mix], axis=1)
    pcm = (stereo * 32767).astype(np.int16)

    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- 镜头

PANEL_W = 980
PANEL_C = (540, 985)
SHOT_SCALE = PANEL_W / 1200.0
_LAST: dict = {"x": 0, "y": 0, "scale": SHOT_SCALE, "dx": 0, "dy": 0}


def map_rect(panel: tuple[int, int, int, int], rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """把原图坐标映射到屏幕（用最近一次贴图的实际缩放比例）。"""
    k = _LAST["scale"]
    px, py = _LAST["x"], _LAST["y"]
    dx, dy = _LAST.get("dx", 0), _LAST.get("dy", 0)
    x0, y0, x1, y1 = rect
    return (int(px + (x0 - dx) * k), int(py + (y0 - dy) * k),
            int(px + (x1 - dx) * k), int(py + (y1 - dy) * k))


def headline(canvas: Image.Image, title: str, sub: str = "") -> None:
    """每个镜头顶部的主标题。"""
    text_center(canvas, 205, title, 62, (255, 255, 255), True)
    if sub:
        text_center(canvas, 292, sub, 34, (185, 185, 200), False)


def brand(canvas: Image.Image) -> None:
    logo_path = ROOT / "assets" / "logo-128.png"
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA").resize((64, 64), Image.LANCZOS)
        canvas.alpha_composite(logo, (44, 56))
    d = ImageDraw.Draw(canvas)
    d.text((120, 72), "KittyLauncher", font=font(34, True), fill=(235, 235, 245, 210))


def badge(canvas: Image.Image, rect: tuple[int, int, int, int], text: str, color=(52, 211, 153)) -> None:
    d = ImageDraw.Draw(canvas)
    f = font(34, True)
    tw = d.textlength(text, font=f)
    x0, y0 = rect[0], rect[1] - 58
    x0 = min(x0, W - int(tw) - 70)
    x0 = max(24, x0)
    layer = Image.new("RGBA", (int(tw) + 44, 52), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([0, 0, tw + 43, 51], 16, fill=(12, 13, 18, 225), outline=color + (200,), width=2)
    canvas.alpha_composite(layer, (x0, y0))
    d.text((x0 + 22, y0 + 8), text, font=f, fill=color + (255,))


def shot_open(canvas, t, dur):
    """logo 弹出 + 标题。"""
    logo = Image.open(ROOT / "assets" / "logo.png").convert("RGBA")
    k = min(1.0, t / 0.55)
    ease = 1 - (1 - k) ** 3
    size = int(300 + 30 * ease)
    logo = logo.resize((size, size), Image.LANCZOS)
    a = int(255 * ease)
    logo.putalpha(logo.getchannel("A").point(lambda v: int(v * a / 255)))
    canvas.alpha_composite(logo, ((W - size) // 2, 560 - size // 2 + int(40 * (1 - ease))))

    if t > 0.5:
        a2 = int(255 * min(1, (t - 0.5) / 0.5))
        text_center(canvas, 860, "KittyLauncher", 96, (255, 255, 255), True, a2)
        text_center(canvas, 980, "macOS 专用的 Minecraft 启动器", 42, (200, 200, 215), False, a2)


def shot_pain(canvas, t, dur):
    d = ImageDraw.Draw(canvas)
    cards = [
        (0.0, "PCL2", "只支持 Windows", (255, 255, 255)),
        (1.6, "Mac 玩家", "那我呢？", (255, 210, 120)),
        (3.4, "所以写了这个", "", (168, 85, 247)),
    ]
    for start, big, small, color in cards:
        if t < start:
            continue
        life = t - start
        a = int(255 * min(1, life / 0.35))
        slide = int(30 * (1 - min(1, life / 0.35)))
        text_center(canvas, 780 + slide, big, 104, color, True, a)
        if small:
            text_center(canvas, 920 + slide, small, 52, (210, 210, 220), False, a)


def shot_launch(canvas, t, dur):
    zoom = 1.0 + 0.05 * (t / dur)
    panel = paste_screenshot(canvas, "launch.png", PANEL_W, PANEL_C, zoom=zoom, cut=(0, 0, 0, 0.27))
    btn = map_rect(panel, (148, 176, 372, 224))
    highlight(canvas, btn, t)

    # 光标从右下飞过来，2.2s 点击
    k = min(1.0, t / 1.2)
    cx = int(btn[0] + (btn[2] - btn[0]) * 0.5 + (1 - k) * 240)
    cy = int(btn[1] + (btn[3] - btn[1]) * 0.5 + (1 - k) * 320)
    click = max(0.0, min(1.0, (t - 2.2) / 0.5))
    cursor(canvas, cx, cy, click if t > 2.2 else 0)
    if 2.2 <= t < 3.2:
        badge(canvas, (btn[0], btn[1] + 120), "点一下就启动", (52, 211, 153))


def shot_loader(canvas, t, dur):
    panel = paste_screenshot(canvas, "download.png", PANEL_W, PANEL_C, cut=(0, 0.05, 0, 0.02))
    sel = map_rect(panel, (862, 281, 1158, 318))
    highlight(canvas, sel, t, (236, 72, 153))
    badge(canvas, (sel[2] + 12, sel[1] + 6), "一键换加载器", (236, 72, 153))

    # 假进度条
    p = min(1.0, t / (dur - 1.2))
    bar_w = int(panel[2] - panel[0] - 120)
    x0 = panel[0] + 60
    y0 = panel[3] + 46
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([x0, y0, x0 + bar_w, y0 + 14], 7, fill=(255, 255, 255, 28))
    if p > 0:
        d.rounded_rectangle([x0, y0, x0 + int(bar_w * p), y0 + 14], 7, fill=(236, 72, 153, 255))
        d.text((x0, y0 + 26), f"安装中 {int(p * 100)}%", font=font(32), fill=(200, 200, 212, 230))


def shot_mods(canvas, t, dur):
    panel = paste_screenshot(canvas, "mods.png", PANEL_W, PANEL_C, zoom=1.05, pan=(0, -0.05))
    box = map_rect(panel, (128, 76, 1085, 116))
    highlight(canvas, box, t, (52, 211, 153))

    # 打字效果
    typed = "sodium"[: max(0, int((t - 0.6) / 0.09))]
    if typed:
        d = ImageDraw.Draw(canvas)
        d.text((box[0] + 24, box[1] + 10), typed, font=font(34), fill=(240, 240, 245, 255))

    if t > 2.0:
        target = map_rect(panel, (543, 232, 610, 258))
        cursor(canvas, target[0] + 20, target[1] + 12, min(1.0, (t - 2.0) / 0.5))
        badge(canvas, (target[0] - 120, target[1] - 10), "一键装进实例", (52, 211, 153))


def shot_login(canvas, t, dur):
    shot = "users-logged-in.png" if (SHOTS_DIR / "users-logged-in.png").exists() else "users.png"
    panel = paste_screenshot(canvas, shot, PANEL_W, PANEL_C, zoom=1.12, pan=(-0.1, -0.25))
    card = map_rect(panel, (125, 75, 470, 300))
    highlight(canvas, card, t, (52, 211, 153))
    badge(canvas, (card[0], card[1]), "微软正版：已登录", (52, 211, 153))


_skin_frames: list[Image.Image] = []


def skin_frames() -> list[Image.Image]:
    if _skin_frames:
        return _skin_frames
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from kitty import skin, skin3d

    if QApplication.instance() is None:
        QApplication(sys.argv)

    cache = TMP / "skinframes"
    cache.mkdir(parents=True, exist_ok=True)
    info = skin.resolve("Notch")
    for i in range(72):
        p = cache / f"{i:03d}.png"
        if not p.exists():
            pm = skin3d.render(info["path"], 560, 740, yaw_deg=i * 5, pitch_deg=8, scale=1.0,
                               slim=(info.get("model") == "slim"))
            pm.save(str(p), "PNG")
        _skin_frames.append(Image.open(p).convert("RGBA"))
    return _skin_frames


def shot_skin(canvas, t, dur):
    frames = skin_frames()
    idx = int(t / dur * len(frames)) % len(frames)
    f = frames[idx]

    # 光晕底 + 细边框
    glow = Image.new("RGBA", (960, 800), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([160, 180, 800, 760], fill=(168, 85, 247, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    canvas.alpha_composite(glow, (60, 480))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([110, 500, W - 110, 1290], 34, outline=(168, 85, 247, 70), width=2)

    canvas.alpha_composite(f, ((W - f.width) // 2, 520))
    text_center(canvas, 1330, "拖拽旋转 · 滚轮缩放 · 自动转圈", 36, (200, 200, 215), False)


def shot_diag(canvas, t, dur):
    panel = paste_screenshot(canvas, "dialog-diagnosis.png", PANEL_W, PANEL_C, zoom=1.04, pan=(0, 0.06))
    region = map_rect(panel, (24, 178, 736, 392))
    highlight(canvas, region, t, (248, 113, 113))
    badge(canvas, (panel[2] - 300, panel[1] + 18), "3 条问题 + 修法", (248, 113, 113))


def shot_mirror(canvas, t, dur):
    panel = paste_screenshot(canvas, "settings.png", PANEL_W, PANEL_C, zoom=1.1, pan=(-0.15, 0.1))
    sel = map_rect(panel, (140, 493, 492, 532))
    highlight(canvas, sel, t, (168, 85, 247))
    badge(canvas, (sel[0], sel[1]), "切 BMCLAPI 镜像", (168, 85, 247))

    speed = 1.2 + min(1.0, t / (dur - 0.8)) * 8.6
    d = ImageDraw.Draw(canvas)
    txt = f"{speed:.1f} MB/s"
    d.text((540, panel[3] + 60), txt, font=font(72, True), fill=(52, 211, 153, 255), anchor="ma")


def shot_end(canvas, t, dur):
    logo = Image.open(ROOT / "assets" / "logo.png").convert("RGBA").resize((260, 260), Image.LANCZOS)
    canvas.alpha_composite(logo, ((W - 260) // 2, 520))
    text_center(canvas, 830, "KittyLauncher", 82, (255, 255, 255), True)
    text_center(canvas, 930, "macOS 专用的 Minecraft 启动器", 40, (205, 205, 220), False)
    text_center(canvas, 1050, "github.com/guofuxiuer-max/kitty-launcher", 34, (168, 85, 247), True)
    text_center(canvas, 1110, "MIT · 免费开源 · 星标就是动力", 32, (160, 160, 175), False)


# ---------------------------------------------------------------- 时间线

SHOTS = [
    # key,        vo 序号, 时长, 标题, 副标题, 底部字幕
    ("open",   1, 5.2, "", "", "Windows 有 PCL，Mac 有什么？"),
    ("pain",   2, 6.6, "", "", "现在有了：KittyLauncher，专为 macOS 写的启动器"),
    ("launch", 3, 7.0, "① 启动", "实例隔离 · 点一下就开", "卡片式实例列表，实例互相隔离，点一下就启动"),
    ("loader", 4, 6.4, "② 装版本", "原版 / Fabric / Forge / Quilt", "原版、Fabric、Forge、Quilt，一个下拉框全搞定"),
    ("mods",   5, 5.2, "③ 装模组", "Modrinth 直接搜，装进当前实例", "模组直接搜 Modrinth，一键装进当前实例"),
    ("login",  6, 5.4, "④ 正版登录", "设备码授权 · token 自动续期", "微软正版登录，浏览器输个码就进正版服"),
    ("skin",   7, 8.8, "⑤ 3D 皮肤", "拖拽旋转 · 纯 QPainter 投影", "皮肤是能转的 3D 模型，纯 Qt 手绘"),
    ("diag",   8, 4.8, "⑥ 崩溃诊断", "15 条规则翻译成人话", "崩了也不怕，一键把日志翻译成人话"),
    ("mirror", 9, 5.6, "⑦ 镜像加速", "官方源 / BMCLAPI 一键切", "下载慢？切 BMCLAPI 镜像"),
    ("end",   10, 8.0, "", "", "开源、免费、MIT。GitHub 搜 kitty-launcher"),
]

DRAW = {
    "open": shot_open, "pain": shot_pain, "launch": shot_launch, "loader": shot_loader,
    "mods": shot_mods, "login": shot_login, "skin": shot_skin, "diag": shot_diag,
    "mirror": shot_mirror, "end": shot_end,
}

DANMAKU = [
    (0.8, "PCL 的味道！", 0), (1.6, "Mac 终于有了", 1), (2.4, "这也太丝滑了", 2),
    (3.2, "macOS 狂喜", 3), (4.4, "前面那个说 PCL 的+1", 0),
    (6.0, "确实是刚需", 1), (7.2, "求 Windows 版（不", 2), (8.4, "猫咪启动器是吧", 3),
    (9.6, "这 UI 比原版好看", 0), (11.0, "点启动那下爽", 1),
    (13.2, "Fabric 一键装？", 2), (14.4, "学生党感动哭了", 3),
    (17.0, "sodium 我也装过", 0), (18.2, "装模组终于不用手动了", 1),
    (21.0, "正版服能进了", 2), (22.2, "设备码好评", 3),
    (25.0, "这皮肤能转？！", 0), (26.4, "纯 Qt 画的？离谱", 1), (27.8, "比某些网站还清楚", 2),
    (31.0, "崩溃诊断绝了", 3), (32.2, "求求先修我这个问题", 0),
    (35.0, "BMCLAPI 救我狗命", 1), (36.4, "这速度差十倍", 2),
    (39.0, "已 star", 3), (40.4, "开源好评", 0), (41.8, "已 fork，明天试试", 1),
]


def main() -> int:
    stills = "--stills" in sys.argv
    TMP.mkdir(parents=True, exist_ok=True)

    # 时间线
    timeline, t0 = [], 0.0
    for key, vo, dur, head, sub2, sub in SHOTS:
        timeline.append({"key": key, "vo": vo, "dur": dur, "head": head, "sub2": sub2,
                         "sub": sub, "start": t0})
        t0 += dur
    total = t0
    print(f"总时长 {total:.1f}s · {int(total * FPS)} 帧 · {W}×{H}@{FPS}")

    bg = vertical_bg()
    dm = Danmaku(DANMAKU)

    def frame_at(t: float) -> Image.Image:
        seg = timeline[-1]
        for s in timeline:
            if t < s["start"] + s["dur"]:
                seg = s
                break
        local = t - seg["start"]
        canvas = bg.copy()
        if seg.get("head"):
            headline(canvas, seg["head"], seg.get("sub2", ""))
        DRAW[seg["key"]](canvas, local, seg["dur"])

        # 画中画底部字幕
        pill(canvas, 1450, seg["sub"], 40)

        dm.draw(canvas, t, top=378, lane_h=68)
        brand(canvas)

        # 镜头切换时 0.22s 的黑场过渡
        if local < 0.22:
            a = int(255 * (1 - local / 0.22))
            canvas.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, a)))
        return canvas.convert("RGB")

    if stills:
        out = TMP / "stills"
        out.mkdir(exist_ok=True)
        for s in timeline:
            img = frame_at(s["start"] + s["dur"] * 0.62)
            p = out / f"{s['key']}.png"
            img.save(p)
            print("still:", p)
        return 0

    audio_path = TMP / "mix.wav"
    build_audio(timeline, total, audio_path)
    print("音频:", audio_path, f"{audio_path.stat().st_size // 1024} KB")

    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    out_path = ROOT / "docs" / "KittyLauncher-promo.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(audio_path),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = int(total * FPS)
    for i in range(frames):
        img = frame_at(i / FPS)
        proc.stdin.write(img.tobytes())
        if i % 300 == 0:
            print(f"  {i}/{frames} 帧")
    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    proc.wait()
    if proc.returncode != 0:
        print("ffmpeg 失败：", err[-2000:])
        return 1
    print(f"完成：{out_path}  {out_path.stat().st_size // 1024 // 1024} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
