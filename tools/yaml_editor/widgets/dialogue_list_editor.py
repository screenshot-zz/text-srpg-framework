"""对话列表编辑器（stories.yaml 的 dialogue 字段用）。

每行是下列两种之一：
    普通对话    {speaker: "...", text: "..."}
    分支对话    {choices: [{text, actions, story}, ...]}

显示策略（方案 A）：
    普通对话 → speaker QLineEdit + text QPlainTextEdit（可视化）
    分支对话 → 一个 QPlainTextEdit 显示 JSON（兜底）

数据安全：
    get_data() 返回 None 时表示「解析失败，保留原值」
"""
from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton,
)
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString, ScalarString,
)


# 明确浅色控件样式 —— 避免深色系统主题下控件与容器融合
ROW_QSS = """
QFrame#RowFrame {
    background: #f5f5f5;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
}
QLineEdit {
    background: white;
    color: black;
    border: 1px solid #999;
    border-radius: 3px;
    padding: 3px 6px;
}
QPlainTextEdit {
    background: white;
    color: black;
    border: 1px solid #999;
    border-radius: 3px;
    padding: 3px 6px;
}
QPushButton {
    background: #e5e5e5;
    color: #333;
    border: 1px solid #999;
    border-radius: 3px;
    padding: 3px 8px;
    font-weight: bold;
}
QPushButton:hover {
    background: #d0d0d0;
}
QPushButton:pressed {
    background: #b8b8b8;
}
QPushButton:disabled {
    background: #f0f0f0;
    color: #999;
}
QLabel {
    color: #333;
}
QComboBox {
    background: white;
    color: black;
    border: 1px solid #999;
    border-radius: 3px;
    padding: 2px 6px;
}
QSpinBox {
    background: white;
    color: black;
    border: 1px solid #999;
    border-radius: 3px;
    padding: 2px 6px;
}
QCheckBox {
    color: #333;
}
"""


class DialogueListEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #ddd; background: #fafafa; }")
        self._scroll.setMinimumHeight(180)

        self._content = QWidget()
        self._rows_layout = QVBoxLayout(self._content)
        self._rows_layout.setContentsMargins(4, 4, 4, 4)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch(1)
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll, 1)

        btns = QHBoxLayout()
        add_normal_btn = QPushButton("+ 普通对话")
        add_choice_btn = QPushButton("+ 分支对话")
        add_normal_btn.setStyleSheet(
            "QPushButton { background: #e5e5e5; color: #333;"
            " border: 1px solid #999; border-radius: 3px;"
            " padding: 4px 10px; font-weight: bold; }"
            "QPushButton:hover { background: #d0d0d0; }")
        add_choice_btn.setStyleSheet(add_normal_btn.styleSheet())
        btns.addWidget(add_normal_btn)
        btns.addWidget(add_choice_btn)
        btns.addStretch(1)
        layout.addLayout(btns)

        add_normal_btn.clicked.connect(self._add_normal)
        add_choice_btn.clicked.connect(self._add_choices)

        self._rows: list[_DialogueRow] = []
        self._silent = False

    # ---------- 对外 ----------

    def load(self, data: list | None) -> None:
        self._silent = True
        try:
            self._clear()
            for item in (data or []):
                if isinstance(item, dict):
                    self._append_row(_DialogueRow(item))
        finally:
            self._silent = False

    def get_data(self) -> list | None:
        out: list[dict] = []
        for row in self._rows:
            data = row.get_data()
            if data is None:
                return None
            out.append(data)
        return out

    # ---------- 内部 ----------

    def _clear(self) -> None:
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _append_row(self, row: "_DialogueRow") -> None:
        row.changed.connect(self._on_row_changed)
        row.delete_requested.connect(lambda r=row: self._delete_row(r))
        idx = self._rows_layout.count() - 1
        self._rows_layout.insertWidget(idx, row)
        self._rows.append(row)

    def _delete_row(self, row: "_DialogueRow") -> None:
        if row in self._rows:
            self._rows.remove(row)
            row.setParent(None)
            row.deleteLater()
            self._on_row_changed()

    def _add_normal(self) -> None:
        self._append_row(_DialogueRow({"speaker": "旁白", "text": ""}))
        self._on_row_changed()

    def _add_choices(self) -> None:
        template = {
            "choices": [
                {"text": "选项 1", "actions": [], "story": ""},
            ]
        }
        self._append_row(_DialogueRow(template))
        self._on_row_changed()

    def _on_row_changed(self) -> None:
        if self._silent:
            return
        self.changed.emit()


# ============================================================
# 单行 widget
# ============================================================
class _DialogueRow(QFrame):
    changed = Signal()
    delete_requested = Signal()

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._is_choices = "choices" in data

        self.setObjectName("RowFrame")
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(ROW_QSS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        # 顶部工具栏
        top = QHBoxLayout()
        kind = "分支对话（JSON）" if self._is_choices else "普通对话"
        kind_label = QLabel(kind)
        kind_label.setStyleSheet(
            "color: #666; font-size: 11px; font-weight: bold;")
        top.addWidget(kind_label)
        top.addStretch(1)

        up_btn = QPushButton("↑")
        up_btn.setFixedWidth(28)
        up_btn.setToolTip("上移")
        up_btn.clicked.connect(self._emit_move_up)
        top.addWidget(up_btn)

        down_btn = QPushButton("↓")
        down_btn.setFixedWidth(28)
        down_btn.setToolTip("下移")
        down_btn.clicked.connect(self._emit_move_down)
        top.addWidget(down_btn)

        del_btn = QPushButton("×")
        del_btn.setFixedWidth(28)
        del_btn.setToolTip("删除此对话")
        del_btn.clicked.connect(self.delete_requested.emit)
        top.addWidget(del_btn)

        outer.addLayout(top)

        # 内容
        if self._is_choices:
            self._json_edit = QPlainTextEdit()
            self._json_edit.setPlainText(
                _dump_json(data.get("choices") or []))
            self._json_edit.setMinimumHeight(100)
            self._json_edit.setStyleSheet(
                "font-family: Consolas, monospace; font-size: 11px;")
            # QPlainTextEdit.textChanged 无参数，直接 connect 也行
            self._json_edit.textChanged.connect(
                lambda: self._on_text_changed())
            outer.addWidget(self._json_edit)
            self._speaker_edit = None
            self._text_edit = None
        else:
            row = QHBoxLayout()
            speaker_label = QLabel("说话人：")
            self._speaker_edit = QLineEdit(str(data.get("speaker", "")))
            self._speaker_edit.setPlaceholderText("如：旁白 / 艾伦")
            self._speaker_edit.setMinimumWidth(150)
            # ⭐ Bug 2 修复：textChanged 带 str 参数，用 lambda 丢弃
            self._speaker_edit.textChanged.connect(
                lambda _t: self._on_text_changed())
            row.addWidget(speaker_label)
            row.addWidget(self._speaker_edit)
            row.addStretch(1)
            outer.addLayout(row)

            self._text_edit = QPlainTextEdit()
            self._text_edit.setPlainText(str(data.get("text", "")))
            self._text_edit.setPlaceholderText("台词内容（可多行）")
            self._text_edit.setMinimumHeight(60)
            self._text_edit.setMaximumHeight(140)
            self._text_edit.textChanged.connect(
                lambda: self._on_text_changed())
            outer.addWidget(self._text_edit)
            self._json_edit = None

    def _on_text_changed(self) -> None:
        self.changed.emit()

    def get_data(self) -> dict | None:
        if self._is_choices:
            text = self._json_edit.toPlainText() if self._json_edit else ""
            try:
                choices = json.loads(text) if text.strip() else []
            except json.JSONDecodeError:
                return None
            if not isinstance(choices, list):
                return None
            return {"choices": choices}
        return {
            "speaker": _wrap_str(self._speaker_edit.text()),
            "text": _wrap_str(self._text_edit.toPlainText()),
        }

    def _emit_move_up(self) -> None:
        self._emit_move(-1)

    def _emit_move_down(self) -> None:
        self._emit_move(1)

    def _emit_move(self, direction: int) -> None:
        if hasattr(self, "_on_move_cb") and callable(self._on_move_cb):
            self._on_move_cb(self, direction)

    def set_move_callback(self, cb) -> None:
        self._on_move_cb = cb


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


def _wrap_str(text: str):
    return DoubleQuotedScalarString(text)