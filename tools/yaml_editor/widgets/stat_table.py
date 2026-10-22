"""属性表格编辑器（classes/units 的 stats / growth 用）。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QCheckBox, QLabel, QSpinBox,
)

from ..zh_map import field_zh


class StatTable(QWidget):
    changed = Signal()

    STATS = ["hp", "str", "def", "spd", "skl", "luk", "int", "res", "mov"]

    def __init__(
        self,
        min_val: int = -99,
        max_val: int = 999,
        parent=None,
    ):
        super().__init__(parent)
        self._rows: dict[str, tuple[QCheckBox, QSpinBox]] = {}
        self._silent = False

        layout = QGridLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.setColumnStretch(1, 1)

        for row, stat in enumerate(self.STATS):
            cb = QCheckBox()
            label = QLabel(field_zh(stat))
            spin = QSpinBox()
            spin.setRange(min_val, max_val)
            spin.setEnabled(False)

            cb.toggled.connect(
                lambda checked, s=spin: self._on_toggle(s, checked))
            # ⭐ Bug 2 修复：valueChanged 带 int 参数，用 lambda 丢弃
            spin.valueChanged.connect(lambda _v: self._emit_changed())

            layout.addWidget(cb, row, 0)
            layout.addWidget(label, row, 1)
            layout.addWidget(spin, row, 2)

            self._rows[stat] = (cb, spin)

    def load(self, data: dict | None) -> None:
        self._silent = True
        try:
            data = data or {}
            for stat, (cb, spin) in self._rows.items():
                if stat in data:
                    cb.setChecked(True)
                    spin.setEnabled(True)
                    try:
                        spin.setValue(int(data[stat]))
                    except (TypeError, ValueError):
                        spin.setValue(0)
                else:
                    cb.setChecked(False)
                    spin.setEnabled(False)
                    spin.setValue(0)
        finally:
            self._silent = False

    def get_data(self) -> dict:
        return {
            stat: spin.value()
            for stat, (cb, spin) in self._rows.items()
            if cb.isChecked()
        }

    def _on_toggle(self, spin: QSpinBox, checked: bool) -> None:
        spin.setEnabled(checked)
        self._emit_changed()

    def _emit_changed(self) -> None:
        if self._silent:
            return
        self.changed.emit()