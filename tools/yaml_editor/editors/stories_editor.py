"""config/stories.yaml 编辑器。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QMessageBox, QInputDialog, QComboBox, QSpinBox, QPushButton,
    QFrame, QTabWidget,
)
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from ..yaml_io import YamlFile
from ..zh_map import value_zh
from ..widgets.form_base import FormBase
from ..widgets.list_panel import ListPanel
from ..widgets.generic_form import GenericForm
from ..widgets.id_list_editor import IdListEditor
from ..widgets.dialogue_list_editor import (
    DialogueListEditor, ROW_QSS,
)
from ..widgets.action_list_editor import ActionListEditor


_SPECIAL_KEYS = {"supports", "talks"}


# ============================================================
# 顶层编辑器
# ============================================================
class StoriesEditor(FormBase):
    def __init__(self, stories_path: str | Path, registry, parent=None):
        super().__init__(parent)
        self.yaml_file = YamlFile(stories_path)
        self.registry = registry

        self._ensure_special_keys()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self._plot_tab = _PlotTab(self)
        self._support_tab = _SupportTab(self)
        self._talk_tab = _TalkTab(self)

        self.tabs.addTab(self._plot_tab, "剧情")
        self.tabs.addTab(self._support_tab, "支援")
        self.tabs.addTab(self._talk_tab, "战斗对话")

        layout.addWidget(self.tabs)

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._refresh_all_lists()

    def _ensure_special_keys(self) -> None:
        data = self.yaml_file.data
        if "supports" not in data:
            data["supports"] = CommentedMap()
        if "talks" not in data:
            data["talks"] = CommentedMap()

    def _on_tab_changed(self, idx: int) -> None:
        self.tabs.widget(idx).refresh_list()

    def _refresh_all_lists(self) -> None:
        self._plot_tab.refresh_list()
        self._support_tab.refresh_list()
        self._talk_tab.refresh_list()

    def refresh(self) -> None:
        self.yaml_file.load()
        self._ensure_special_keys()
        self._refresh_all_lists()


# ============================================================
# 3 个 Tab 的公共基类
# ============================================================
class _SubMapTabBase(QWidget):
    KEEP_ORIGINAL_ON_NONE: set[str] = {"dialogue", "actions", "dialogues"}
    FLOW_STYLE_KEYS: set[str] = {"dialogue", "actions", "dialogues"}

    def __init__(self, editor: "StoriesEditor", parent=None):
        super().__init__(parent)
        self.editor = editor
        self._current_key: str | None = None
        self._loading_form = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.list_panel = ListPanel(title=self.list_title())
        self.list_panel.setMinimumWidth(220)
        self.list_panel.setMaximumWidth(320)
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

    def get_submap(self) -> CommentedMap:
        raise NotImplementedError

    def exclude_keys(self) -> set[str]:
        return set()

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        raise NotImplementedError

    def default_new_item(self) -> dict:
        raise NotImplementedError

    def field_overrides(self, cfg: dict) -> dict:
        return {}

    @property
    def yaml_file(self) -> YamlFile:
        return self.editor.yaml_file

    @property
    def registry(self):
        return self.editor.registry

    # ---------- 列表 ----------

    def refresh_list(self, keep_key: str | None = None) -> None:
        submap = self.get_submap()
        excluded = self.exclude_keys()
        items: list[tuple[str, str]] = []
        for key in submap.keys():
            key_str = str(key)
            if key_str in excluded:
                continue
            cfg = submap.get(key)
            if isinstance(cfg, dict) and cfg.get("name"):
                items.append(
                    (key_str, f"{value_zh(str(cfg['name']))}（{key_str}）"))
            else:
                items.append((key_str, key_str))
        self.list_panel.populate(
            items, current_key=keep_key or self._current_key)

    def _on_select(self, key: str) -> None:
        if key == self._current_key:
            return
        self._current_key = key
        self._load_form(key)

    # ---------- 表单 ----------

    def _load_form(self, key: str) -> None:
        submap = self.get_submap()
        cfg = submap.get(key) or {}
        if not isinstance(cfg, dict):
            self.header.setText(f"{key}（格式异常）")
            self.form.clear()
            return
        name = cfg.get("name") or key
        self.header.setText(f"编辑：{value_zh(str(name))}（{key}）")

        overrides = self.field_overrides(cfg)

        self._loading_form = True
        try:
            self.form.build(
                self.fields_for(cfg),
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
        submap = self.get_submap()
        cfg = submap.get(self._current_key)
        if not isinstance(cfg, dict):
            return

        if value is None and key in self.KEEP_ORIGINAL_ON_NONE:
            return

        if value is None:
            if key in cfg:
                del cfg[key]
            self.yaml_file.mark_dirty()
            return

        existing = cfg.get(key)
        if isinstance(value, dict) and isinstance(
                existing, (CommentedMap, dict)):
            self._merge_map(existing, value)
        elif key in self.FLOW_STYLE_KEYS:
            # 强制流式，与原作者手写习惯一致
            cfg[key] = self.yaml_file.ensure_flow_style(value)
        else:
            cfg[key] = self.yaml_file.ensure_commented(value)
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

    # ---------- 新建 / 删除 ----------

    def _on_add(self) -> None:
        new_id, ok = QInputDialog.getText(
            self, f"新建{self.tab_name()}",
            f"请输入 {self.tab_name()} 的 id（英文，如 my_story）：")
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
        if new_id in _SPECIAL_KEYS:
            QMessageBox.warning(
                self, "保留 key",
                f"「{new_id}」是保留 key，请到对应 Tab 编辑。")
            return

        submap = self.get_submap()
        if new_id in submap:
            QMessageBox.warning(
                self, "id 重复", f"id「{new_id}」已存在。")
            return

        # ⭐ 修复：使用 add_to_map 自动在前方加空行
        self.yaml_file.add_to_map(submap, new_id, self.default_new_item())
        self.refresh_list(keep_key=new_id)

    def _on_delete(self) -> None:
        if self._current_key is None:
            return
        key = self._current_key
        resp = QMessageBox.question(
            self, "删除确认",
            f"确认删除「{key}」？\n（仅从内存移除，保存后才会写入文件）")
        if resp != QMessageBox.Yes:
            return
        submap = self.get_submap()
        if key in submap:
            del submap[key]
            self.yaml_file.mark_dirty()
        self._current_key = None
        self.refresh_list()
        self.form.clear()
        self.header.setText("请选择左侧项")


# ============================================================
# Tab 1：剧情
# ============================================================
class _PlotTab(_SubMapTabBase):
    def tab_name(self) -> str:
        return "剧情"

    def get_submap(self) -> CommentedMap:
        return self.yaml_file.data

    def exclude_keys(self) -> set[str]:
        return _SPECIAL_KEYS

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        return [
            ("dialogue", cfg.get("dialogue") or []),
            ("actions", cfg.get("actions") or []),
        ]

    def default_new_item(self) -> dict:
        return {
            "dialogue": [{"speaker": "旁白", "text": ""}],
            "actions": [],
        }

    def field_overrides(self, cfg: dict) -> dict:
        overrides: dict = {}

        dlg_w = DialogueListEditor()
        dlg_w.load(cfg.get("dialogue") or [])
        dlg_w.changed.connect(
            lambda: self.form.notify_change("dialogue"))

        def dlg_getter():
            return dlg_w.get_data()
        overrides["dialogue"] = (dlg_w, dlg_getter)

        act_w = ActionListEditor()
        act_w.load(cfg.get("actions") or [])
        act_w.changed.connect(
            lambda: self.form.notify_change("actions"))

        def act_getter():
            return act_w.get_data()
        overrides["actions"] = (act_w, act_getter)

        return overrides


# ============================================================
# Tab 2：支援
# ============================================================
class _SupportTab(_SubMapTabBase):
    def tab_name(self) -> str:
        return "支援"

    def get_submap(self) -> CommentedMap:
        return self.yaml_file.data["supports"]

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        return [
            ("max_level", int(cfg.get("max_level", 1) or 1)),
            ("dialogues", cfg.get("dialogues") or []),
        ]

    def default_new_item(self) -> dict:
        return {
            "max_level": 1,
            "dialogues": [
                {"level": 1,
                 "dialogue": [{"speaker": "旁白", "text": ""}]},
            ],
        }

    def field_overrides(self, cfg: dict) -> dict:
        overrides: dict = {}

        d_w = SupportsDialoguesEditor()
        d_w.load(cfg.get("dialogues") or [])
        d_w.changed.connect(
            lambda: self.form.notify_change("dialogues"))

        def getter():
            return d_w.get_data()
        overrides["dialogues"] = (d_w, getter)

        return overrides


# ============================================================
# Tab 3：战斗对话
# ============================================================
class _TalkTab(_SubMapTabBase):
    def tab_name(self) -> str:
        return "战斗对话"

    def get_submap(self) -> CommentedMap:
        return self.yaml_file.data["talks"]

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        return [
            ("name", cfg.get("name", "")),
            ("units", cfg.get("units") or []),
            ("timing", cfg.get("timing", "pre")),
            ("condition", cfg.get("condition", "")),
            ("once", bool(cfg.get("once", True))),
            ("dialogue", cfg.get("dialogue") or []),
            ("actions", cfg.get("actions") or []),
        ]

    def default_new_item(self) -> dict:
        return {
            "name": "新战斗对话",
            "units": [],
            "timing": "pre",
            "condition": "",
            "once": True,
            "dialogue": [{"speaker": "旁白", "text": ""}],
            "actions": [],
        }

    def field_overrides(self, cfg: dict) -> dict:
        overrides: dict = {}

        units_w = IdListEditor(
            options_provider=lambda: [
                (uid, f"{uname}（{uid}）")
                for uid, uname in self.registry.unit_ids()
            ]
        )
        units_w.load(list(cfg.get("units") or []))
        units_w.changed.connect(
            lambda: self.form.notify_change("units"))

        def units_getter():
            return units_w.get_values()
        overrides["units"] = (units_w, units_getter)

        combo = QComboBox()
        combo.addItem("战前（pre）", "pre")
        combo.addItem("战后（post）", "post")
        current = cfg.get("timing", "pre")
        for i in range(combo.count()):
            if combo.itemData(i) == current:
                combo.setCurrentIndex(i)
                break
        combo.currentIndexChanged.connect(
            lambda _idx: self.form.notify_change("timing"))

        def timing_getter():
            return combo.currentData()
        overrides["timing"] = (combo, timing_getter)

        dlg_w = DialogueListEditor()
        dlg_w.load(cfg.get("dialogue") or [])
        dlg_w.changed.connect(
            lambda: self.form.notify_change("dialogue"))

        def dlg_getter():
            return dlg_w.get_data()
        overrides["dialogue"] = (dlg_w, dlg_getter)

        act_w = ActionListEditor()
        act_w.load(cfg.get("actions") or [])
        act_w.changed.connect(
            lambda: self.form.notify_change("actions"))

        def act_getter():
            return act_w.get_data()
        overrides["actions"] = (act_w, act_getter)

        return overrides


# ============================================================
# 支援 Tab 专用：dialogues 列表编辑器
# ============================================================
class SupportsDialoguesEditor(QWidget):
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
        self._scroll.setMinimumHeight(160)

        self._content = QWidget()
        self._rows_layout = QVBoxLayout(self._content)
        self._rows_layout.setContentsMargins(4, 4, 4, 4)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch(1)
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll)

        add_btn = QPushButton("+ 添加等级")
        add_btn.clicked.connect(self._on_add)
        layout.addWidget(add_btn)

        self._rows: list[_SupportLevelRow] = []
        self._silent = False

    def load(self, data: list | None) -> None:
        self._silent = True
        try:
            self._clear()
            for item in (data or []):
                if isinstance(item, dict):
                    self._append_row(_SupportLevelRow(
                        level=int(item.get("level", 1) or 1),
                        dialogue=item.get("dialogue") or [],
                    ))
        finally:
            self._silent = False

    def get_data(self) -> list | None:
        out: list[dict] = []
        for row in self._rows:
            d = row.get_data()
            if d is None:
                return None
            out.append(d)
        return out

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

    def _append_row(self, row: "_SupportLevelRow") -> None:
        row.changed.connect(self._on_row_changed)
        row.delete_requested.connect(lambda r=row: self._delete_row(r))
        idx = self._rows_layout.count() - 1
        self._rows_layout.insertWidget(idx, row)
        self._rows.append(row)

    def _delete_row(self, row: "_SupportLevelRow") -> None:
        if row in self._rows:
            self._rows.remove(row)
            row.setParent(None)
            row.deleteLater()
            self._on_row_changed()

    def _on_add(self) -> None:
        next_level = 1
        if self._rows:
            next_level = max(r.get_level() for r in self._rows) + 1
        self._append_row(_SupportLevelRow(
            level=next_level,
            dialogue=[{"speaker": "旁白", "text": ""}],
        ))
        self._on_row_changed()

    def _on_row_changed(self) -> None:
        if self._silent:
            return
        self.changed.emit()


class _SupportLevelRow(QFrame):
    changed = Signal()
    delete_requested = Signal()

    def __init__(self, level: int, dialogue: list, parent=None):
        super().__init__(parent)
        self.setObjectName("RowFrame")
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(ROW_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        top = QHBoxLayout()
        level_label = QLabel("支援等级：")
        top.addWidget(level_label)
        self.level_spin = QSpinBox()
        self.level_spin.setRange(1, 5)
        self.level_spin.setValue(level)
        self.level_spin.valueChanged.connect(
            lambda _v: self.changed.emit())
        top.addWidget(self.level_spin)
        top.addStretch(1)

        del_btn = QPushButton("×")
        del_btn.setFixedWidth(28)
        del_btn.setToolTip("删除该等级")
        del_btn.clicked.connect(self.delete_requested.emit)
        top.addWidget(del_btn)
        layout.addLayout(top)

        self.dialogue_editor = DialogueListEditor()
        self.dialogue_editor.load(dialogue)
        self.dialogue_editor.changed.connect(self.changed.emit)
        layout.addWidget(self.dialogue_editor)

    def get_level(self) -> int:
        return self.level_spin.value()

    def get_data(self) -> dict | None:
        dlg = self.dialogue_editor.get_data()
        if dlg is None:
            return None
        return {"level": self.level_spin.value(), "dialogue": dlg}


# ============================================================
# 辅助
# ============================================================
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