"""配色与全局样式表（QSS）。改这里就能换皮肤。"""

DARK = {
    "bg": "#101116",
    "bg_soft": "#16181f",
    "panel": "#1c1f28",
    "panel2": "#232733",
    "line": "#2b3040",
    "text": "#e8e9f2",
    "dim": "#9498ac",
    "accent": "#a855f7",
    "accent2": "#ec4899",
    "ok": "#34d399",
    "warn": "#fbbf24",
    "err": "#f87171",
}

LIGHT = {
    "bg": "#f4f5fa",
    "bg_soft": "#ffffff",
    "panel": "#ffffff",
    "panel2": "#f2f4fa",
    "line": "#dfe3ee",
    "text": "#1b1d26",
    "dim": "#6b7080",
    "accent": "#8b5cf6",
    "accent2": "#ec4899",
    "ok": "#059669",
    "warn": "#d97706",
    "err": "#dc2626",
}


def qss(c: dict) -> str:
    return f"""
* {{
    font-family: "PingFang SC", "SF Pro Text", "Helvetica Neue", sans-serif;
    font-size: 13px;
    outline: none;
}}
QWidget#Root {{ background: {c['bg']}; color: {c['text']}; }}
QWidget {{ color: {c['text']}; }}

/* ---------- 左侧导航 ---------- */
QWidget#Rail {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c['bg_soft']}, stop:1 {c['bg']});
    border-right: 1px solid {c['line']};
}}
QLabel#Logo {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['accent']}, stop:1 {c['accent2']});
    border-radius: 15px;
    font-size: 24px;
}}
QPushButton#Nav {{
    background: transparent; border: 0; border-radius: 13px;
    color: {c['dim']}; padding: 8px 0;
}}
QPushButton#Nav:hover {{ background: rgba(168,85,247,0.14); color: {c['text']}; }}
QPushButton#Nav:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['accent']}, stop:1 {c['accent2']});
    color: white;
}}

/* ---------- 顶栏 ---------- */
QWidget#TopBar {{ background: {c['bg_soft']}; border-bottom: 1px solid {c['line']}; }}
QLabel#TopTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#TopSub {{ color: {c['dim']}; font-size: 12px; }}
QLabel#Chip {{
    background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 11px;
    color: {c['dim']}; padding: 5px 12px; font-size: 12px;
}}
QLabel#ChipOn {{
    background: {c['panel']}; border: 1px solid {c['ok']}; border-radius: 11px;
    color: {c['ok']}; padding: 5px 12px; font-size: 12px;
}}

/* ---------- 卡片 ---------- */
QFrame#Card {{
    background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 16px;
}}
QFrame#Hero {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0.3,
                stop:0 rgba(168,85,247,0.55), stop:0.55 rgba(236,72,153,0.30),
                stop:1 {c['panel']});
    border: 1px solid rgba(168,85,247,0.45); border-radius: 20px;
}}
QLabel#HeroTitle {{ font-size: 24px; font-weight: 700; }}
QLabel#HeroSub {{ color: {c['dim']}; }}
QLabel#StatKey {{ color: {c['dim']}; font-size: 11px; }}
QLabel#StatVal {{ font-size: 17px; font-weight: 600; }}
QFrame#Stat {{
    background: rgba(0,0,0,0.22); border: 1px solid {c['line']}; border-radius: 13px;
}}
QFrame#InstCard {{
    background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 15px;
}}
QFrame#InstCard:hover {{ border: 1px solid rgba(168,85,247,0.65); }}
QFrame#InstCard[picked="true"] {{ border: 1px solid {c['accent']}; background: {c['panel2']}; }}
QLabel#InstName {{ font-weight: 600; font-size: 14px; }}
QLabel#InstVer {{ color: {c['dim']}; font-size: 12px; }}
QLabel#Section {{ font-size: 14px; font-weight: 600; }}
QLabel#SectionSub {{ color: {c['dim']}; font-size: 12px; }}
QLabel#Hint {{ color: {c['dim']}; font-size: 12px; }}

/* ---------- 按钮 ---------- */
QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['accent']}, stop:1 {c['accent2']});
    color: white; border: 0; border-radius: 12px;
    padding: 11px 22px; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #b06bf8, stop:1 #f25aa5); }}
QPushButton#Primary:disabled {{ background: {c['panel2']}; color: {c['dim']}; }}
QPushButton#Big {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['accent']}, stop:1 {c['accent2']});
    color: white; border: 0; border-radius: 15px;
    padding: 15px 40px; font-size: 16px; font-weight: 700; letter-spacing: 1px;
}}
QPushButton#Big:disabled {{ background: {c['panel2']}; color: {c['dim']}; }}
QPushButton#Ghost {{
    background: {c['panel2']}; border: 1px solid {c['line']};
    border-radius: 10px; padding: 8px 16px;
}}
QPushButton#Ghost:hover {{ border: 1px solid {c['accent']}; }}
QPushButton#Tiny {{
    background: {c['panel2']}; border: 1px solid {c['line']};
    border-radius: 8px; padding: 4px 10px; font-size: 12px;
}}
QPushButton#Tiny:hover {{ border: 1px solid {c['accent']}; }}
QPushButton#Seg {{
    background: transparent; border: 0; border-radius: 9px;
    padding: 7px 16px; color: {c['dim']};
}}
QPushButton#Seg:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['accent']}, stop:1 {c['accent2']});
    color: white;
}}

/* ---------- 输入 ---------- */
QLineEdit, QComboBox, QSpinBox {{
    background: {c['panel2']}; border: 1px solid {c['line']}; border-radius: 10px;
    padding: 8px 12px; selection-background-color: {c['accent']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {c['accent']}; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {c['panel']}; border: 1px solid {c['line']};
    selection-background-color: {c['accent']};
}}

/* ---------- 列表 ---------- */
QListWidget {{
    background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 14px;
    padding: 6px;
}}
QListWidget::item {{ border-radius: 10px; padding: 8px 10px; }}
QListWidget::item:hover {{ background: {c['panel2']}; }}
QListWidget::item:selected {{ background: rgba(168,85,247,0.22); color: {c['text']}; }}

/* ---------- 日志 ---------- */
QPlainTextEdit#Log {{
    background: #0b0c10; border: 1px solid {c['line']}; border-radius: 13px;
    color: #c7cbd9; font-family: "SF Mono", Menlo, monospace; font-size: 11.5px;
    padding: 10px;
}}
QLabel#TermTitle {{ color: {c['dim']}; font-size: 12px; }}

/* ---------- 进度条 ---------- */
QProgressBar {{
    background: {c['panel2']}; border: 0; border-radius: 5px; height: 8px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {c['accent']}, stop:1 {c['accent2']});
}}

QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{ background: transparent; border: 0; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['line']}; padding: 6px; }}
"""
