"""坐标表格控件（units / deploy_points / shops 通用）。"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QComboBox, QSpinBox, QHeaderView, QDialog,
    QPlainTextEdit, QMessageBox, QLabel,
)


class _ExtraJsonDialog(QDialog):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑其他参数（JSON）")
        self.resize(480, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        hint = QLabel(
            "在此填入附加参数，如:\n"
            "{ \"move_to\": {\"x\": 14, \"y\": 4}, \"reached_action\": \"story\" }")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        self.text = QPlainTextEdit()
        self.text.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
        self.text.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px;")
        layout.addWidget(self.text)

        btns = QHBoxLayout()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def _on_ok(self):
        txt = self.text.toPlainText().strip()
        try:
            data = json.loads(txt) if txt else {}
            if not isinstance(data, dict):
                raise ValueError("必须是 JSON 对象（花括号 {} 包裹）")
        except Exception as e:
            QMessageBox.warning(self, "格式错误", f"JSON 解析失败：\n{e}")
            return
        self.extra_data = data
        self.accept()

    def get_data(self) -> dict:
        return getattr(self, "extra_data", {})


class CoordsTable(QWidget):
    changed = Signal()

    def __init__(self, columns: list[dict], allow_extra: bool = False,
                 parent=None):
        super().__init__(parent)
        self._columns = list(columns)
        self._allow_extra = allow_extra
        self._row_extras: list[dict] = []
        self._silent = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        cols_count = len(self._columns) + (1 if allow_extra else 0) + 1
        self.table = QTableWidget(0, cols_count)

        headers = [c.get("label", c["key"]) for c in self._columns]
        if allow_extra:
            headers.append("其他参数")
        headers.append("操作")

        self.table.setHorizontalHeaderLabels(headers)
        
        # 固定行高，足够容纳控件
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.verticalHeader().setVisible(False)

        hdr = self.table.horizontalHeader()
        for i in range(len(self._columns)):
            hdr.setSectionResizeMode(i, QHeaderView.Stretch)
            
        if allow_extra:
            hdr.setSectionResizeMode(len(self._columns), QHeaderView.Stretch)
            
        del_idx = len(self._columns) + (1 if allow_extra else 0)
        hdr.setSectionResizeMode(del_idx, QHeaderView.Fixed)
        self.table.setColumnWidth(del_idx, 50)

        layout.addWidget(self.table)

        btns = QHBoxLayout()
        self.add_btn = QPushButton("+ 添加行")
        self.add_btn.clicked.connect(self._on_add)
        btns.addWidget(self.add_btn)
        btns.addStretch(1)
        layout.addLayout(btns)

        # ⭐ 修复文本编辑不生效的问题
        self.table.itemChanged.connect(self._on_item_changed)

    def update_bounds(self, width: int, height: int) -> None:
        for row in range(self.table.rowCount()):
            for col_idx, col in enumerate(self._columns):
                if col.get("type") != "int":
                    continue
                w = self.table.cellWidget(row, col_idx)
                if not isinstance(w, QSpinBox):
                    continue
                key = col["key"]
                if key == "x":
                    w.setMaximum(max(0, width - 1))
                    if w.value() > width - 1:
                        w.setValue(max(0, width - 1))
                elif key == "y":
                    w.setMaximum(max(0, height - 1))
                    if w.value() > height - 1:
                        w.setValue(max(0, height - 1))

    def load(self, data: list | None) -> None:
        self._silent = True
        try:
            self.table.setRowCount(0)
            self._row_extras = []
            for item in (data or []):
                if isinstance(item, dict):
                    self._append_row(item)
            self.table.resizeRowsToContents()
        finally:
            self._silent = False

    def get_data(self) -> list[dict]:
        out: list[dict] = []
        for row in range(self.table.rowCount()):
            item = (dict(self._row_extras[row])
                    if self._allow_extra and row < len(self._row_extras)
                    else {})

            for col_idx, col in enumerate(self._columns):
                key = col["key"]
                ctype = col.get("type", "text")
                if ctype == "combo":
                    w = self.table.cellWidget(row, col_idx)
                    if isinstance(w, QComboBox):
                        item[key] = w.currentData()
                    else:
                        item[key] = ""
                elif ctype == "int":
                    w = self.table.cellWidget(row, col_idx)
                    if isinstance(w, QSpinBox):
                        item[key] = int(w.value())
                    else:
                        item[key] = 0
                else:
                    cell = self.table.item(row, col_idx)
                    item[key] = cell.text() if cell else ""
            out.append(item)
        return out

    def _append_row(self, data: dict) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        declared_keys = {c["key"] for c in self._columns}
        extras = {k: v for k, v in data.items() if k not in declared_keys}
        self._row_extras.append(extras)

        for col_idx, col in enumerate(self._columns):
            key = col["key"]
            value = data.get(key, col.get("default"))
            widget = self._make_widget(col, value)
            if isinstance(widget, QWidget):
                self.table.setCellWidget(row, col_idx, widget)
            else:
                self.table.setItem(row, col_idx, widget)

        if self._allow_extra:
            extra_btn = QPushButton("编辑参数...")
            extra_btn.clicked.connect(
                lambda _c=False, r=row: self._on_edit_extra(r))
            self.table.setCellWidget(row, len(self._columns), extra_btn)

        del_idx = len(self._columns) + (1 if self._allow_extra else 0)
        del_btn = QPushButton("×")
        del_btn.setFixedWidth(32)
        del_btn.clicked.connect(
            lambda _c=False, r=row: self._on_delete(r))
        self.table.setCellWidget(row, del_idx, del_btn)
        
        self.table.resizeRowsToContents()

    def _make_widget(self, col: dict, value):
        ctype = col.get("type", "text")
        if ctype == "combo":
            w = QComboBox()
            w.setMinimumWidth(100)
            for v, label in col.get("options", []):
                w.addItem(str(label), v)
            if value is not None:
                for i in range(w.count()):
                    if w.itemData(i) == value:
                        w.setCurrentIndex(i)
                        break
            w.currentIndexChanged.connect(lambda _i: self._emit())
            return w

        if ctype == "int":
            w = QSpinBox()
            w.setMinimumWidth(80)
            w.setRange(col.get("min", 0), col.get("max", 999))
            try:
                w.setValue(int(value) if value is not None
                           else col.get("default", 0))
            except (TypeError, ValueError):
                w.setValue(0)
            w.valueChanged.connect(lambda _v: self._emit())
            return w

        item = QTableWidgetItem("" if value is None else str(value))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        return item

    def _on_add(self) -> None:
        default: dict = {}
        for col in self._columns:
            if "default" in col:
                default[col["key"]] = col["default"]
        self._append_row(default)
        self._emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._silent:
            return
        self._emit()

    def _on_edit_extra(self, row: int) -> None:
        if row < 0 or row >= len(self._row_extras):
            return
        dlg = _ExtraJsonDialog(self._row_extras[row], self)
        if dlg.exec() == QDialog.Accepted:
            self._row_extras[row] = dlg.get_data()
            self._emit()

    def _on_delete(self, row: int) -> None:
        if 0 <= row < self.table.rowCount():
            self.table.removeRow(row)
            if self._allow_extra and row < len(self._row_extras):
                del self._row_extras[row]
            self._rebind_delete_btns()
            self._emit()

    def _rebind_delete_btns(self) -> None:
        del_idx = len(self._columns) + (1 if self._allow_extra else 0)
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, del_idx)
            if isinstance(w, QPushButton):
                try:
                    w.clicked.disconnect()
                except Exception:
                    pass
                w.clicked.connect(
                    lambda _c=False, r=row: self._on_delete(r))

    def _emit(self) -> None:
        if self._silent:
            return
        self.changed.emit()
