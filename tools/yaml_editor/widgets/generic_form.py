"""根据值类型自动生成控件。

类型 → 控件：
    bool             → QCheckBox
    int              → QSpinBox（范围 ±999999）
    float            → QDoubleSpinBox（4 位小数）
    str 短(≤50)      → QLineEdit
    str 长 / 含换行  → QPlainTextEdit
    None             → QLineEdit（空 或 "null" 视为 None）
    dict             → 递归子表单（QGroupBox + 「+ 添加字段」+ 每字段「×」）
    list             → 逗号分隔 QLineEdit（P2 里部分字段被 field_overrides 替换）

field_overrides（P2 新增）：
    {key: (widget, getter)}
    指定 key 的字段直接用给定 widget，不走自动生成。
    用于替换 QLineEdit 为 QComboBox / IdListEditor 等专用控件。

引号保持：
    ScalarString 子类（DoubleQuotedScalarString / SingleQuotedScalarString）
    改回时用原类型构造，保证 name: "铁剑" 不会退化成 name: 铁剑。
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import (
    QWidget, QFormLayout, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPlainTextEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QLabel,
    QGroupBox, QPushButton, QInputDialog, QMessageBox,
)

from ruamel.yaml.scalarstring import ScalarString

from ..zh_map import field_zh


_LONG_STR_THRESHOLD = 50
_CUSTOM_OPTION_LABEL = "── 自定义字段名 ──"


class GenericForm(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self._getters: dict[str, Callable[[], Any]] = {}
        self._change_cb: Callable[[str, Any], None] | None = None
        self._parent_changed_cb: Callable[[], None] | None = None

        self._pending_fields: list[tuple[str, Any]] = []
        self._field_defaults: dict[str, Any] | None = None
        self._field_overrides: dict[str, tuple[QWidget, Callable]] = {}
        self._in_subform = False

        self._silent = False

    # ---------- 回调 ----------

    def set_change_callback(
        self, cb: Callable[[str, Any], None] | None
    ) -> None:
        self._change_cb = cb

    def set_parent_changed_callback(
        self, cb: Callable[[], None] | None
    ) -> None:
        self._parent_changed_cb = cb

    def notify_change(self, key: str) -> None:
        """公开接口：外部 override 控件（QComboBox/IdListEditor）修改后调用。"""
        self._emit(key)

    def _emit(self, key: str) -> None:
        if self._silent or self._change_cb is None:
            return
        self._change_cb(key, self.get_value(key))

    def _notify_parent_changed(self) -> None:
        if self._parent_changed_cb:
            self._parent_changed_cb()

    # ---------- 构建 ----------

    def clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._getters.clear()

    def build(
        self,
        fields: list[tuple[str, Any]],
        field_defaults: dict[str, Any] | None = None,
        in_subform: bool = False,
        field_overrides: dict[str, tuple[QWidget, Callable]] | None = None,
    ) -> None:
        self._pending_fields = list(fields)
        self._field_defaults = field_defaults
        self._in_subform = in_subform
        self._field_overrides = dict(field_overrides or {})
        self._rebuild()

    def _rebuild(self) -> None:
        self._silent = True
        try:
            self.clear()
            if self._in_subform and not self._pending_fields:
                hint = QLabel("（暂无字段，点击下方「+ 添加字段」）")
                hint.setStyleSheet("color: #999; font-style: italic;")
                self._layout.addRow(hint)
            for key, value in self._pending_fields:
                self._add_field(key, value)
        finally:
            self._silent = False

    def _add_field(self, key: str, value: Any) -> None:
        # override 优先
        if key in self._field_overrides:
            widget, getter = self._field_overrides[key]
            label = QLabel(field_zh(key))
            label.setToolTip(key)
            label.setStyleSheet("color: #444;")
            if self._in_subform:
                container = QWidget()
                row = QHBoxLayout(container)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(4)
                row.addWidget(widget, 1)
                del_btn = QPushButton("×")
                del_btn.setFixedWidth(26)
                del_btn.clicked.connect(
                    lambda _c=False, k=key: self._delete_field(k))
                row.addWidget(del_btn)
                self._layout.addRow(label, container)
            else:
                self._layout.addRow(label, widget)
            self._getters[key] = getter
            return

        # 原有逻辑
        label = QLabel(field_zh(key))
        label.setToolTip(key)
        label.setStyleSheet("color: #444;")

        hints_for_this = (
            self._field_defaults.get(key)
            if self._field_defaults is not None else None
        )
        widget, getter = self._make_widget(key, value, hints_for_this)
        if widget is None:
            return

        if self._in_subform:
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(widget, 1)
            del_btn = QPushButton("×")
            del_btn.setFixedWidth(26)
            del_btn.setToolTip(f"删除字段「{key}」")
            del_btn.clicked.connect(
                lambda _checked=False, k=key: self._delete_field(k)
            )
            row.addWidget(del_btn)
            self._layout.addRow(label, container)
        else:
            self._layout.addRow(label, widget)

        self._getters[key] = getter

    def _make_widget(
        self, key: str, value: Any, hints_for_this: Any = None
    ):
        # ---- bool ----
        if isinstance(value, bool):
            w = QCheckBox()
            w.setChecked(value)
            w.toggled.connect(lambda _v: self._emit(key))

            def getter_bool() -> bool:
                return w.isChecked()
            return w, getter_bool

        # ---- int ----
        if isinstance(value, int):
            w = QSpinBox()
            w.setRange(-999999, 999999)
            w.setValue(value)
            w.valueChanged.connect(lambda _v: self._emit(key))

            def getter_int() -> int:
                return int(w.value())
            return w, getter_int

        # ---- float ----
        if isinstance(value, float):
            w = QDoubleSpinBox()
            w.setRange(-1e9, 1e9)
            w.setDecimals(4)
            w.setValue(value)
            w.valueChanged.connect(lambda _v: self._emit(key))

            def getter_float() -> float:
                return float(w.value())
            return w, getter_float

        # ---- str ----
        if isinstance(value, str):
            orig_type = (
                type(value) if isinstance(value, ScalarString) else str
            )

            def wrap(text: str):
                if orig_type is not str:
                    try:
                        return orig_type(text)
                    except Exception:
                        return text
                return text

            if len(value) > _LONG_STR_THRESHOLD or "\n" in value:
                w = QPlainTextEdit()
                w.setPlainText(str(value))
                w.setMinimumHeight(80)
                w.textChanged.connect(lambda: self._emit(key))

                def getter_multiline():
                    return wrap(w.toPlainText())
                return w, getter_multiline

            w = QLineEdit(str(value))
            w.textChanged.connect(lambda _t: self._emit(key))

            def getter_line():
                return wrap(w.text())
            return w, getter_line

        # ---- None ----
        if value is None:
            w = QLineEdit()
            w.setPlaceholderText("（null）—— 留空或填 null 表示无")
            w.textChanged.connect(lambda _t: self._emit(key))

            def getter_nullable():
                t = w.text().strip()
                return None if t == "" or t.lower() == "null" else t
            return w, getter_nullable

        # ---- dict ----
        if isinstance(value, dict):
            box = QGroupBox(field_zh(key))
            box.setToolTip(key)
            inner = QVBoxLayout(box)
            inner.setContentsMargins(8, 8, 8, 8)
            inner.setSpacing(4)

            sub = GenericForm(box)
            sub.build(
                list(value.items()),
                field_defaults=hints_for_this,
                in_subform=True,
            )
            sub.set_change_callback(lambda _sk, _sv: self._emit(key))
            sub.set_parent_changed_callback(lambda: self._emit(key))
            inner.addWidget(sub)

            add_btn = QPushButton("+ 添加字段")
            add_btn.clicked.connect(
                lambda _c=False, s=sub: self._on_add_subfield(s)
            )
            inner.addWidget(add_btn)

            def getter_dict() -> dict:
                return sub.get_values()
            return box, getter_dict

        # ---- list ----
        if isinstance(value, list):
            w = QLineEdit(", ".join(_display_list_item(x) for x in value))
            w.setPlaceholderText("多项用逗号分隔")
            w.textChanged.connect(lambda _t: self._emit(key))

            def getter_list() -> list[str]:
                t = w.text().strip()
                if not t:
                    return []
                return [x.strip() for x in t.split(",") if x.strip()]
            return w, getter_list

        # ---- 兜底 ----
        w = QLineEdit(str(value))
        w.textChanged.connect(lambda _t: self._emit(key))

        def getter_fallback() -> str:
            return w.text()
        return w, getter_fallback

    # ---------- 子表单字段增删 ----------

    def _on_add_subfield(self, sub: "GenericForm") -> None:
        candidates: list[tuple[str, str]] = []
        if sub._field_defaults:
            for k in sub._field_defaults.keys():
                if k in sub._getters:
                    continue
                zh = field_zh(k)
                candidates.append((k, f"{zh}（{k}）"))

        key: str | None = None

        if candidates:
            items = [label for _k, label in candidates]
            items.append(_CUSTOM_OPTION_LABEL)
            choice, ok = QInputDialog.getItem(
                self, "添加字段",
                "选择要添加的字段（带中文说明）：",
                items, 0, False,
            )
            if not ok:
                return
            idx = items.index(choice)
            if idx < len(candidates):
                key = candidates[idx][0]
            else:
                key, ok = QInputDialog.getText(
                    self, "自定义字段名",
                    "字段名（英文，如 turn_damage）：",
                )
                if not ok:
                    return
                key = key.strip()
                if not key:
                    return
                if not _is_valid_field_name(key):
                    QMessageBox.warning(
                        self, "非法字段名",
                        "字段名只能包含字母、数字、下划线，"
                        "且不能以数字开头。")
                    return
        else:
            key, ok = QInputDialog.getText(
                self, "添加字段",
                "字段名（英文，如 hp / str / def）：",
            )
            if not ok:
                return
            key = key.strip()
            if not key:
                return
            if not _is_valid_field_name(key):
                QMessageBox.warning(
                    self, "非法字段名",
                    "字段名只能包含字母、数字、下划线，"
                    "且不能以数字开头。")
                return

        if key is None:
            return
        if key in sub._getters:
            QMessageBox.warning(
                self, "字段已存在", f"字段「{key}」已存在。")
            return

        default = sub._default_for_new_field(key)
        sub._pending_fields.append((key, default))
        sub._rebuild()
        sub._notify_parent_changed()

    def _delete_field(self, key: str) -> None:
        self._pending_fields = [
            f for f in self._pending_fields if f[0] != key
        ]
        self._rebuild()
        self._notify_parent_changed()

    def _default_for_new_field(self, key: str) -> Any:
        if self._field_defaults and key in self._field_defaults:
            v = self._field_defaults[key]
            if isinstance(v, dict) and len(v) > 1:
                preferred = "str" if "str" in v else next(iter(v))
                return {preferred: v[preferred]}
            return v
        if self._field_defaults:
            vals = list(self._field_defaults.values())
            if vals and all(
                isinstance(x, (int, float)) and not isinstance(x, bool)
                for x in vals
            ):
                return 0
        return ""

    # ---------- 取值 ----------

    def get_value(self, key: str) -> Any:
        getter = self._getters.get(key)
        return getter() if getter else None

    def get_values(self) -> dict[str, Any]:
        return {k: g() for k, g in self._getters.items()}


# ---------- 辅助 ----------

def _display_list_item(x: Any) -> str:
    if isinstance(x, dict):
        return "{" + ", ".join(f"{k}: {v}" for k, v in x.items()) + "}"
    return str(x)


def _is_valid_field_name(s: str) -> bool:
    if not s:
        return False
    if s[0].isdigit():
        return False
    return all(c.isalnum() or c == "_" for c in s)