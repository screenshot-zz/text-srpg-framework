"""config/status.yaml 编辑器。

结构：{status_id: {name, description, formula, duration}}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QMessageBox, QInputDialog,
)
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from ..yaml_io import YamlFile
from ..zh_map import value_zh
from ..widgets.form_base import FormBase
from ..widgets.list_panel import ListPanel
from ..widgets.generic_form import GenericForm


_NEW_STATUS_TEMPLATE: dict = {
    "name": "新状态",
    "description": "",
    "formula": {},
    "duration": 1,
}

_STAT_BONUS_CANDIDATES: dict = {
    "hp": 0, "str": 0, "def": 0, "spd": 0, "skl": 0,
    "luk": 0, "int": 0, "res": 0, "mov": 0,
    "attack": 0, "defense": 0, "hit": 0, "avoid": 0, "crit": 0,
}

_STATUS_FIELD_DEFAULTS: dict = {
    "formula": {
        "turn_damage": DoubleQuotedScalarString("max_hp * 0.05"),
        "skip_action": False,
        "stat_bonus": _STAT_BONUS_CANDIDATES,
    },
}


class StatusEditor(FormBase):
    def __init__(self, status_path: str | Path, parent=None):
        super().__init__(parent)
        self.yaml_file = YamlFile(status_path)
        self._current_key: str | None = None
        self._loading_form = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.list_panel = ListPanel(title="状态列表")
        self.list_panel.setMinimumWidth(220)
        self.list_panel.setMaximumWidth(320)
        outer.addWidget(self.list_panel)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self.header = QLabel("请选择左侧状态")
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

        outer.addWidget(right, 1)

        self.list_panel.item_selected.connect(self._on_select)
        self.list_panel.add_requested.connect(self._on_add)
        self.list_panel.delete_requested.connect(self._on_delete)
        self.list_panel.enable_buttons(add=True, delete=True)

        self._refresh_list()

    # ---------- 列表 ----------

    def _refresh_list(self, keep_key: str | None = None) -> None:
        items: list[tuple[str, str]] = []
        for key in self.yaml_file.keys():
            cfg = self.yaml_file.get(key) or {}
            if isinstance(cfg, dict):
                name = str(cfg.get("name", key))
            else:
                name = key
            items.append((key, f"{value_zh(name)}（{key}）"))
        self.list_panel.populate(
            items, current_key=keep_key or self._current_key)

    def _on_select(self, key: str) -> None:
        if key == self._current_key:
            return
        self._current_key = key
        self._load_form(key)

    # ---------- 表单 ----------

    def _load_form(self, key: str) -> None:
        cfg = self.yaml_file.get(key) or {}
        if not isinstance(cfg, dict):
            self.header.setText(f"{key}（数据格式异常，跳过编辑）")
            self.form.clear()
            return
        name = cfg.get("name", key)
        self.header.setText(f"编辑：{value_zh(str(name))}（{key}）")

        self._loading_form = True
        try:
            self.form.build(
                list(cfg.items()),
                field_defaults=_STATUS_FIELD_DEFAULTS,
            )
        finally:
            self._loading_form = False

    def _on_field_changed(self, key: str, value: Any) -> None:
        if self._loading_form or self._current_key is None:
            return
        cfg = self.yaml_file.get(self._current_key)
        if not isinstance(cfg, dict):
            return

        existing = cfg.get(key)
        if isinstance(value, dict) and isinstance(
                existing, (CommentedMap, dict)):
            self._merge_map(existing, value)
        else:
            cfg[key] = self.yaml_file.ensure_commented(value)
        self.yaml_file.mark_dirty()

        if key == "name":
            self._refresh_list(keep_key=self._current_key)
            self.header.setText(
                f"编辑：{value_zh(str(value))}（{self._current_key}）")

    def _merge_map(self, target: CommentedMap | dict,
                   new_dict: dict) -> None:
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

    # ---------- 新建 / 删除 ----------

    def _on_add(self) -> None:
        new_id, ok = QInputDialog.getText(
            self, "新建状态",
            "请输入状态 id（英文，如 poison / stun / my_status）：")
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
                self, "id 重复", f"状态 id「{new_id}」已存在。")
            return

        # ⭐ 新增：用 add_with_separator（前面插入空行）
        self.yaml_file.add_with_separator(
            new_id, dict(_NEW_STATUS_TEMPLATE))
        self._refresh_list(keep_key=new_id)

    def _on_delete(self) -> None:
        if self._current_key is None:
            return
        key = self._current_key
        resp = QMessageBox.question(
            self, "删除确认",
            f"确认删除状态「{key}」？\n"
            f"（仅从内存移除，保存后才会写入文件）",
        )
        if resp != QMessageBox.Yes:
            return
        self.yaml_file.delete(key)
        self._current_key = None
        self._refresh_list()
        self.form.clear()
        self.header.setText("请选择左侧状态")

    # ---------- FormBase 接口 ----------

    def refresh(self) -> None:
        self.yaml_file.load()
        self._current_key = None
        self.form.clear()
        self.header.setText("请选择左侧状态")
        self._refresh_list()


# ---------- 辅助 ----------

def _values_equal(a: Any, b: Any) -> bool:
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