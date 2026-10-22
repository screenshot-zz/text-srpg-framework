"""键值对子表格（P2 的 items/skills 编辑器会用到）。

P1 交付但暂不使用 —— status_editor 用 GenericForm 的 dict 递归就够了。
P2 里会在以下场景用它：
  - items.yaml 的 formula.heal / cure_status 等多键
  - skills.yaml 的 formula.stat_bonus / aura
理由：这些键是「离散集合」（heal / cure_status / apply_status / damage），
用下拉 + 表达式行比递归子表单更直观。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QComboBox, QHeaderView,
)


class KVTable(QWidget):
    """两列（键 / 值）表格。

    - 键列是 QComboBox（可编辑），options 传入候选键
    - 值列是 QTableWidgetItem，显示/编辑时自动识别 int/float/bool/None/str
    - 变化触发 changed 信号
    """

    changed = Signal()

    def __init__(self, key_options: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._key_options = list(key_options or [])
        self._silent = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["键", "值"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        btns = QHBoxLayout()
        self.add_btn = QPushButton("+ 添加行")
        self.del_btn = QPushButton("− 删除选中")
        btns.addWidget(self.add_btn)
        btns.addWidget(self.del_btn)
        btns.addStretch(1)
        layout.addLayout(btns)

        self.add_btn.clicked.connect(self._on_add)
        self.del_btn.clicked.connect(self._on_delete)
        self.table.itemChanged.connect(self._on_item_changed)

    # ---------- 对外 ----------

    def set_key_options(self, options: list[str]) -> None:
        self._key_options = list(options)

    def load(self, data: dict[str, Any] | None) -> None:
        self._silent = True
        try:
            self.table.setRowCount(0)
            for k, v in (data or {}).items():
                self._append_row(str(k), _to_text(v))
        finally:
            self._silent = False

    def get_data(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for row in range(self.table.rowCount()):
            cb = self.table.cellWidget(row, 0)
            item = self.table.item(row, 1)
            if cb is None:
                continue
            key = cb.currentText().strip()
            if not key:
                continue
            out[key] = _from_text(item.text() if item else "")
        return out

    # ---------- 内部 ----------

    def _append_row(self, key: str, text: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        cb = QComboBox()
        cb.setEditable(True)
        if self._key_options:
            cb.addItems(self._key_options)
        if key:
            idx = cb.findText(key)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            else:
                cb.setEditText(key)
        cb.currentTextChanged.connect(lambda _t: self._emit())
        self.table.setCellWidget(row, 0, cb)

        self.table.setItem(row, 1, QTableWidgetItem(text))

    def _emit(self) -> None:
        if self._silent:
            return
        self.changed.emit()

    def _on_add(self) -> None:
        self._append_row("", "")
        self._emit()

    def _on_delete(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        for r in rows:
            self.table.removeRow(r)
        if rows:
            self._emit()

    def _on_item_changed(self, _item) -> None:
        self._emit()


# ---------- 类型转换 ----------

def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _from_text(text: str) -> Any:
    """从文本推断类型：null / true / false / int / float / 原样字符串（含表达式）。"""
    t = text.strip()
    if t == "" or t.lower() == "null":
        return None
    if t.lower() == "true":
        return True
    if t.lower() == "false":
        return False
    try:
        if "." in t or "e" in t.lower():
            return float(t)
        return int(t)
    except ValueError:
        return text