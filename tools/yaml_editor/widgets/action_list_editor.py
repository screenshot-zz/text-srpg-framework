"""Action 列表编辑器（stories.yaml 的 actions 字段用）。

方案 A 设计：
    整体一个 QPlainTextEdit 显示整个 actions 列表的 JSON，
    底部「格式化」按钮重新缩进。

为什么不做 14 种 action 的表单：
    现有 stories.yaml 里 actions 通常 0-2 条，结构简单。
    一条一个专用子表单反而增加认知负担（14 种类型 × 每种 3-5 字段）。
    未来升级到方案 B 时，这个 widget 会被替换为 action 卡片表单。

数据安全：
    get_data() 返回 None 时表示「解析失败，保留原值」
    - 空列表 [] 是合法值（删除所有 action）
    - 单个 action 用一行 JSON 也可以解析
"""
from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton, QLabel,
)
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import ScalarString


_PLACEHOLDER = """[
  {"type": "give_item", "unit": "hero", "item": "vulnerary"}
]"""


class ActionListEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel(
            "JSON 数组，每项是一个 action。常用类型："
            "give_item / spawn_unit / set_stat / add_skill / "
            "add_status / next_map / change_faction / set_var / "
            "remove_unit / lose_item / change_ai / custom"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(_PLACEHOLDER)
        self.text.setMinimumHeight(100)
        self.text.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;")
        self.text.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text)

        btns = QHBoxLayout()
        fmt_btn = QPushButton("格式化")
        fmt_btn.setToolTip("重新缩进（需 JSON 合法）")
        btns.addWidget(fmt_btn)
        btns.addStretch(1)

        self._status = QLabel("")
        self._status.setStyleSheet("font-size: 11px;")
        btns.addWidget(self._status)

        layout.addLayout(btns)

        fmt_btn.clicked.connect(self._format)

        self._silent = False

    # ---------- 对外 ----------

    def load(self, data: list | None) -> None:
        self._silent = True
        try:
            if data:
                self.text.setPlainText(_dump_json(list(data)))
            else:
                self.text.setPlainText("")
            self._status.setText("")
        finally:
            self._silent = False

    def get_data(self) -> list | None:
        """解析 JSON。

        成功 → 返回 list（可能是空 list）
        失败 → 返回 None（调用方保留原值）
        """
        raw = self.text.toPlainText().strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            self._status.setText(f"✗ JSON 格式错误：{e.msg}")
            self._status.setStyleSheet("color: #c00; font-size: 11px;")
            return None
        if not isinstance(data, list):
            self._status.setText("✗ 顶层必须是数组 [...]")
            self._status.setStyleSheet("color: #c00; font-size: 11px;")
            return None
        self._status.setText("✓ JSON 合法")
        self._status.setStyleSheet("color: #080; font-size: 11px;")
        return data

    # ---------- 内部 ----------

    def _on_text_changed(self) -> None:
        if self._silent:
            return
        self.changed.emit()

    def _format(self) -> None:
        raw = self.text.toPlainText().strip()
        if not raw:
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            self._status.setText(f"✗ 无法格式化：{e.msg}")
            self._status.setStyleSheet("color: #c00; font-size: 11px;")
            return
        self._silent = True
        try:
            self.text.setPlainText(_dump_json(data))
        finally:
            self._silent = False
        self._status.setText("✓ 已格式化")
        self._status.setStyleSheet("color: #080; font-size: 11px;")


# ============================================================
# 辅助
# ============================================================
def _dump_json(v) -> str:
    return json.dumps(_to_plain(v), ensure_ascii=False, indent=2)


def _to_plain(v):
    if isinstance(v, (CommentedMap, dict)):
        return {str(k): _to_plain(val) for k, val in v.items()}
    if isinstance(v, (CommentedSeq, list)):
        return [_to_plain(x) for x in v]
    if isinstance(v, ScalarString):
        return str(v)
    return v