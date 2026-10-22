"""转职编辑器（classes/units 的 promote 字段用）。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QSpinBox, QComboBox,
)

from ..zh_map import value_zh
from .id_list_editor import IdListEditor


class PromoteEditor(QWidget):
    changed = Signal()

    def __init__(
        self,
        item_options: list[tuple[str, str]],
        class_options: list[tuple[str, str]],
        allow_empty_item: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._allow_empty_item = allow_empty_item
        self._silent = False

        layout = QFormLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.level_spin = QSpinBox()
        self.level_spin.setRange(1, 99)
        self.level_spin.setValue(10)
        # ⭐ Bug 2 修复
        self.level_spin.valueChanged.connect(
            lambda _v: self._emit_changed())
        layout.addRow("等级", self.level_spin)

        self.item_combo = QComboBox()
        if allow_empty_item:
            self.item_combo.addItem("（沿用职业默认）", "")
        for key, name in item_options:
            self.item_combo.addItem(f"{name}（{key}）", key)
        # ⭐ Bug 2 修复
        self.item_combo.currentIndexChanged.connect(
            lambda _i: self._emit_changed())
        layout.addRow("需要道具", self.item_combo)

        self.to_editor = IdListEditor(
            options_provider=lambda: list(class_options))
        self.to_editor.load([])
        self.to_editor.changed.connect(self._emit_changed)
        layout.addRow("转职到", self.to_editor)

    def load(self, data: dict | None) -> None:
        self._silent = True
        try:
            data = data or {}
            self.level_spin.setValue(int(data.get("level", 10) or 10))

            item = str(data.get("item", "") or "")
            found = False
            for i in range(self.item_combo.count()):
                if self.item_combo.itemData(i) == item:
                    self.item_combo.setCurrentIndex(i)
                    found = True
                    break
            if not found:
                if self._allow_empty_item and item:
                    self.item_combo.addItem(
                        f"{value_zh(item)}（{item}）", item)
                    self.item_combo.setCurrentIndex(
                        self.item_combo.count() - 1)
                else:
                    self.item_combo.setCurrentIndex(0)

            to_list = data.get("to") or []
            if isinstance(to_list, str):
                to_list = [to_list]
            self.to_editor.load(list(to_list))
        finally:
            self._silent = False

    def get_data(self) -> dict | None:
        item = self.item_combo.currentData() or ""
        to_list = self.to_editor.get_values()
        level = int(self.level_spin.value())

        if not item and not to_list:
            return None
        out: dict = {"level": level}
        if item:
            out["item"] = item
        if to_list:
            out["to"] = to_list
        return out

    def _emit_changed(self) -> None:
        if self._silent:
            return
        self.changed.emit()