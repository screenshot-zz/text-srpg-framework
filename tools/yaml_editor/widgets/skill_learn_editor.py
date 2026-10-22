"""技能学习表格编辑器（classes.yaml 的 skill_learn 用）。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QComboBox, QSpinBox, QHeaderView,
)

from ..zh_map import value_zh


class SkillLearnEditor(QWidget):
    changed = Signal()

    def __init__(
        self,
        skill_options: list[tuple[str, str]],
        parent=None,
    ):
        super().__init__(parent)
        self._skill_options = list(skill_options)
        self._silent = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["等级", "技能", "操作"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        btns = QHBoxLayout()
        add_btn = QPushButton("+ 添加技能学习")
        btns.addWidget(add_btn)
        btns.addStretch(1)
        layout.addLayout(btns)

        add_btn.clicked.connect(self._on_add)

    # ---------- 对外 ----------

    def refresh_options(self, skill_options: list[tuple[str, str]]) -> None:
        self._skill_options = list(skill_options)
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 1)
            if isinstance(combo, QComboBox):
                current = combo.currentData()
                self._fill_combo(combo, current)

    def load(self, data: list | None) -> None:
        self._silent = True
        try:
            self.table.setRowCount(0)
            for entry in (data or []):
                if not isinstance(entry, dict):
                    continue
                level = int(entry.get("level", 1) or 1)
                skill = str(entry.get("skill", "") or "")
                self._append_row(level, skill)
        finally:
            self._silent = False

    def get_data(self) -> list[dict]:
        out: list[dict] = []
        for row in range(self.table.rowCount()):
            spin = self.table.cellWidget(row, 0)
            combo = self.table.cellWidget(row, 1)
            if not isinstance(spin, QSpinBox) or not isinstance(combo, QComboBox):
                continue
            skill = combo.currentData()
            if not skill:
                continue
            out.append({"level": int(spin.value()), "skill": str(skill)})
        return out

    # ---------- 内部 ----------

    def _append_row(self, level: int, skill: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        spin = QSpinBox()
        spin.setRange(1, 99)
        spin.setValue(int(level) if level else 1)
        # ⭐ Bug 2 修复
        spin.valueChanged.connect(lambda _v: self._emit_changed())
        self.table.setCellWidget(row, 0, spin)

        combo = QComboBox()
        self._fill_combo(combo, skill)
        # ⭐ Bug 2 修复
        combo.currentIndexChanged.connect(lambda _i: self._emit_changed())
        self.table.setCellWidget(row, 1, combo)

        del_btn = QPushButton("×")
        del_btn.setFixedWidth(30)
        del_btn.clicked.connect(
            lambda _c=False, r=row: self._on_delete_row(r))
        self.table.setCellWidget(row, 2, del_btn)

    def _fill_combo(self, combo: QComboBox, current: str) -> None:
        combo.blockSignals(True)
        try:
            combo.clear()
            for key, name in self._skill_options:
                combo.addItem(f"{name}（{key}）", key)
            found = False
            for i in range(combo.count()):
                if combo.itemData(i) == current:
                    combo.setCurrentIndex(i)
                    found = True
                    break
            if not found and current:
                combo.addItem(f"{value_zh(current)}（{current}）", current)
                combo.setCurrentIndex(combo.count() - 1)
        finally:
            combo.blockSignals(False)

    def _on_add(self) -> None:
        default_skill = ""
        if self._skill_options:
            default_skill = self._skill_options[0][0]
        self._append_row(1, default_skill)
        self._emit_changed()

    def _on_delete_row(self, row: int) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        self.table.removeRow(row)
        self._rebind_delete_buttons()
        self._emit_changed()

    def _rebind_delete_buttons(self) -> None:
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, 2)
            if isinstance(w, QPushButton):
                try:
                    w.clicked.disconnect()
                except Exception:
                    pass
                w.clicked.connect(
                    lambda _c=False, r=row: self._on_delete_row(r))

    def _emit_changed(self) -> None:
        if self._silent:
            return
        self.changed.emit()