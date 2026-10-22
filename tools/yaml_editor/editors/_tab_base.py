"""Tab 基类：左侧列表 + 右侧表单 + 增删 + dict 增量合并。"""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QMessageBox, QInputDialog, QComboBox,
)
from ruamel.yaml.comments import CommentedMap

from ..zh_map import field_zh, value_zh
from ..widgets.list_panel import ListPanel
from ..widgets.generic_form import GenericForm
from ..widgets.id_list_editor import IdListEditor


class TabBase(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._current_key: str | None = None
        self._loading_form = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.list_panel = ListPanel(title=self.list_title())
        self.list_panel.setMinimumWidth(200)
        self.list_panel.setMaximumWidth(300)
        layout.addWidget(self.list_panel)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self.header = QLabel("请选择左侧项")
        self.header.setStyleSheet(
            "font-weight: bold; font-size: 14px; padding: 4px;")
        right_layout.addWidget(self.header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #ddd; background: white; }")
        self.form = GenericForm()
        self.form.set_change_callback(self._on_field_changed)
        self.scroll.setWidget(self.form)
        right_layout.addWidget(self.scroll, 1)

        layout.addWidget(right, 1)

        self.list_panel.item_selected.connect(self._on_select)
        self.list_panel.add_requested.connect(self._on_add)
        self.list_panel.delete_requested.connect(self._on_delete)
        self.list_panel.enable_buttons(add=True, delete=True)

    def tab_name(self) -> str:
        raise NotImplementedError

    def list_title(self) -> str:
        return f"{self.tab_name()}列表"

    def matches(self, cfg: dict) -> bool:
        raise NotImplementedError

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        raise NotImplementedError

    def default_new_item(self) -> dict:
        raise NotImplementedError

    def field_defaults(self) -> dict | None:
        return None

    def field_overrides(self, cfg: dict) -> dict:
        return {}

    @property
    def yaml_file(self):
        return self.editor.yaml_file

    @property
    def registry(self):
        return self.editor.registry

    def refresh_list(self, keep_key: str | None = None) -> None:
        items: list[tuple[str, str]] = []
        for key in self.yaml_file.keys():
            cfg = self.yaml_file.get(key) or {}
            if not isinstance(cfg, dict):
                continue
            if not self.matches(cfg):
                continue
            name = str(cfg.get("name", key))
            items.append((key, f"{value_zh(name)}（{key}）"))
        self.list_panel.populate(
            items, current_key=keep_key or self._current_key)

    def _on_select(self, key: str) -> None:
        if key == self._current_key:
            return
        self._current_key = key
        self._load_form(key)

    def _load_form(self, key: str) -> None:
        cfg = self.yaml_file.get(key) or {}
        if not isinstance(cfg, dict):
            self.header.setText(f"{key}（格式异常）")
            self.form.clear()
            return
        name = cfg.get("name", key)
        self.header.setText(f"编辑：{value_zh(str(name))}（{key}）")

        overrides = self.field_overrides(cfg)

        self._loading_form = True
        try:
            self.form.build(
                self.fields_for(cfg),
                field_defaults=self.field_defaults(),
                field_overrides=overrides,
            )
        finally:
            self._loading_form = False

    def reload_current_form(self) -> None:
        if self._current_key:
            self._load_form(self._current_key)

    def _on_field_changed(self, key: str, value: Any) -> None:
        if self._loading_form or self._current_key is None:
            return
        cfg = self.yaml_file.get(self._current_key)
        if not isinstance(cfg, dict):
            return

        if value is None:
            if key in cfg:
                del cfg[key]
            self.yaml_file.mark_dirty()
            return

        existing = cfg.get(key)
        if isinstance(value, dict) and isinstance(existing, (CommentedMap, dict)):
            self._merge_map(existing, value)
        else:
            is_new = key not in cfg
            cfg[key] = self.yaml_file.ensure_commented(value)
            # ⭐ 新增字段时，清除 ruamel 自动加的丑陋空行
            if is_new:
                self.yaml_file.remove_blank_line_before(cfg, key)
                
        self.yaml_file.mark_dirty()

        if key == "name":
            self.refresh_list(keep_key=self._current_key)
            self.header.setText(
                f"编辑：{value_zh(str(value))}（{self._current_key}）")

    def _merge_map(self, target, new_dict):
        for k in list(target.keys()):
            if k not in new_dict:
                del target[k]
        for k, v in new_dict.items():
            old_v = target.get(k)
            if isinstance(v, dict) and isinstance(old_v, (CommentedMap, dict)):
                self._merge_map(old_v, v)
            elif _values_equal(v, old_v):
                continue
            else:
                target[k] = self.yaml_file.ensure_commented(v)

    def _on_add(self) -> None:
        new_id, ok = QInputDialog.getText(
            self, f"新建{self.tab_name()}",
            f"请输入 {self.tab_name()} 的 id（英文，如 my_item）：")
        if not ok:
            return
        new_id = new_id.strip()
        if not new_id:
            return
        if not _is_valid_id(new_id):
            QMessageBox.warning(
                self, "非法 id",
                "id 只能包含字母、数字、下划线，且不能以数字开头。")
            return
        if new_id in self.yaml_file:
            QMessageBox.warning(
                self, "id 重复", f"id「{new_id}」已存在。")
            return

        self.yaml_file.add_with_separator(new_id, self.default_new_item())
        self.refresh_list(keep_key=new_id)

    def _on_delete(self) -> None:
        if self._current_key is None:
            return
        key = self._current_key
        resp = QMessageBox.question(
            self, "删除确认",
            f"确认删除「{key}」？\n"
            f"（仅从内存移除，保存后才会写入文件）",
        )
        if resp != QMessageBox.Yes:
            return
        self.yaml_file.delete(key)
        self._current_key = None
        self.refresh_list()
        self.form.clear()
        self.header.setText("请选择左侧项")

    def make_combo_override(
        self, key: str, current: Any,
        options: list[tuple[Any, str]],
    ) -> tuple[QComboBox, Any]:
        combo = QComboBox()
        for v, label in options:
            combo.addItem(label, v)
        for i in range(combo.count()):
            if combo.itemData(i) == current:
                combo.setCurrentIndex(i)
                break

        combo.currentIndexChanged.connect(
            lambda _idx, k=key: self.form.notify_change(k))

        def getter():
            return combo.currentData()
        return combo, getter

    def make_id_list_override(
        self, key: str, values: list[str],
        options: list[tuple[str, str]],
    ) -> tuple[IdListEditor, Any]:
        w = IdListEditor(options_provider=lambda: list(options))
        w.load(list(values))
        w.changed.connect(lambda: self.form.notify_change(key))

        def getter():
            return w.get_values()
        return w, getter


def _values_equal(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return str(a) == str(b)
    if a is None and b is None:
        return True
    return type(a) is type(b) and a == b


def _is_valid_id(s: str) -> bool:
    if not s:
        return False
    if s[0].isdigit():
        return False
    return all(c.isalnum() or c == "_" for c in s)