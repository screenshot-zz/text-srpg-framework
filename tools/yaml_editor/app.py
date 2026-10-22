"""QApplication 装配 + 主窗口创建。

职责：
  1. 设置中文字体（Windows / Linux / macOS 各自的候选）
  2. 注入 .runtime/unmapped.log 路径给 zh_map
  3. 定位 config 目录（tools/yaml_editor/app.py → 项目根/config）
  4. 启动 MainWindow
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from . import zh_map
from .widgets.main_window import MainWindow


# 中文字体候选（按优先级）
_FONT_CANDIDATES = [
    "Microsoft YaHei",       # Windows
    "PingFang SC",           # macOS
    "Noto Sans CJK SC",      # Linux
    "WenQuanYi Micro Hei",   # Linux 备选
    "SimHei",                # Windows 备选
]


def _project_root() -> Path:
    """app.py → yaml_editor → tools → 项目根。"""
    return Path(__file__).resolve().parent.parent.parent


def _config_dir() -> Path:
    return _project_root() / "config"


def _setup_runtime_log() -> Path:
    """创建 .runtime/ 并把日志路径注入 zh_map。"""
    log_dir = Path(__file__).resolve().parent / ".runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    zh_map.set_log_path(log_dir / "unmapped.log")
    return log_dir


def _pick_font() -> QFont:
    """按可用性挑中文字体；都没命中就退回默认字体。"""
    families = set(QFontDatabase.families())
    for name in _FONT_CANDIDATES:
        if name in families:
            f = QFont(name)
            f.setPointSize(10)
            return f
    f = QFont()
    f.setPointSize(10)
    return f


def run_app() -> int:
    _setup_runtime_log()

    app = QApplication(sys.argv)
    app.setApplicationName("FE YAML Editor")
    app.setFont(_pick_font())

    config_dir = _config_dir()
    if not config_dir.exists():
        QMessageBox.critical(
            None, "缺少 config 目录",
            f"未找到 config 目录：\n{config_dir}\n\n"
            f"请确认 tools/yaml_editor/ 位于项目根目录下。",
        )
        return 1

    win = MainWindow(config_dir)
    win.show()
    return app.exec()