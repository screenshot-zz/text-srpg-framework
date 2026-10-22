"""config/classes.yaml 编辑器。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QVBoxLayout, QCheckBox, QLabel

from ..yaml_io import YamlFile
from ..zh_map import value_zh
from ..widgets.form_base import FormBase
from ..widgets.stat_table import StatTable
from ..widgets.skill_learn_editor import SkillLearnEditor
from ..widgets.promote_editor import PromoteEditor
from ._tab_base import TabBase


_MOVE_TYPES = ["foot", "mounted", "flying"]
_WEAPON_TYPES = ["sword", "axe", "lance", "bow", "fang",
                 "anima", "light", "dark", "staff"]


class ClassesEditor(FormBase):
    def __init__(self, classes_path: str | Path, registry, parent=None):
        super().__init__(parent)
        self.yaml_file = YamlFile(classes_path)
        self.registry = registry

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tab = _ClassesTab(self)
        layout.addWidget(self._tab)

        self._tab.refresh_list()

    def refresh(self) -> None:
        self.yaml_file.load()
        self._tab.refresh_list()


# ============================================================
# 单 Tab
# ============================================================
class _ClassesTab(TabBase):
    def tab_name(self) -> str:
        return "职业"

    def matches(self, cfg: dict) -> bool:
        return True

    def default_new_item(self) -> dict:
        return {
            "name": "新职业",
            "description": "",
            "move_type": "foot",
            "groups": ["foot"],
            "stats": {},
            "growth": {},
            "weapon_types": [],
            "skill_learn": [],
            "class_skills": [],
        }

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        fields: list[tuple[str, Any]] = [
            ("name", cfg.get("name", "")),
            ("description", cfg.get("description", "")),
            ("__enable_force_base", "force_base" in cfg),
            ("__enable_max_level", "max_level" in cfg),
        ]
        if "max_level" in cfg:
            fields.append(("max_level", int(cfg.get("max_level", 40))))
            
        fields.extend([
            ("move_type", cfg.get("move_type", "foot")),
            ("groups", cfg.get("groups") or []),
            ("stats", cfg.get("stats") or {}),
            ("growth", cfg.get("growth") or {}),
            ("weapon_types", cfg.get("weapon_types") or []),
            ("skill_learn", cfg.get("skill_learn") or []),
            ("class_skills", cfg.get("class_skills") or []),
        ])
        
        # ⭐ 冲突处理：如果勾选了强制下位，就不显示转职配置，改为灰字
        if "force_base" not in cfg:
            fields.append(("promote", cfg.get("promote") or {}))
        else:
            fields.append(("__promote_disabled", "（已勾选强制下位职业，无法配置转职）"))
            
        return fields

    def field_overrides(self, cfg: dict) -> dict:
        overrides: dict = {}

        # ⭐ 强制下位职业 (只写 true)
        cb_fb = QCheckBox()
        cb_fb.setChecked("force_base" in cfg)
        def on_fb_toggled(checked):
            # 先获取最新的 cfg，防止闭包变量被意外覆盖
            cur_cfg = self.yaml_file.get(self._current_key)
            if not cur_cfg:
                return
            if checked == ("force_base" in cur_cfg):
                return
            if checked:
                cur_cfg["force_base"] = True
                if "promote" in cur_cfg:
                    del cur_cfg["promote"]  # 自动删掉冲突的转职配置
            else:
                if "force_base" in cur_cfg:
                    del cur_cfg["force_base"]
            self.yaml_file.mark_dirty()
            self.reload_current_form()
        cb_fb.toggled.connect(on_fb_toggled)
        overrides["__enable_force_base"] = (cb_fb, lambda: cb_fb.isChecked())

        # ⭐ 强制最高等级
        cb_ml = QCheckBox()
        cb_ml.setChecked("max_level" in cfg)
        def on_ml_toggled(checked):
            cur_cfg = self.yaml_file.get(self._current_key)
            if not cur_cfg:
                return
            if checked == ("max_level" in cur_cfg):
                return
            if checked:
                cur_cfg["max_level"] = 40
            else:
                if "max_level" in cur_cfg:
                    del cur_cfg["max_level"]
            self.yaml_file.mark_dirty()
            self.reload_current_form()
        cb_ml.toggled.connect(on_ml_toggled)
        overrides["__enable_max_level"] = (cb_ml, lambda: cb_ml.isChecked())

        # 灰字提示覆盖
        if "__promote_disabled" in [k for k, _ in self.fields_for(cfg)]:
            lbl = QLabel("（已勾选强制下位职业，无法配置转职）")
            lbl.setStyleSheet("color: #888; font-style: italic;")
            overrides["__promote_disabled"] = (lbl, lambda: None)

        # 移动类型下拉
        overrides["move_type"] = self.make_combo_override(
            "move_type",
            current=cfg.get("move_type", "foot"),
            options=[(v, value_zh(v)) for v in _MOVE_TYPES],
        )

        # groups 多选
        overrides["groups"] = self.make_id_list_override(
            "groups",
            list(cfg.get("groups") or []),
            [(g, value_zh(g)) for g in self.registry.group_ids()],
        )

        # stats / growth
        overrides["stats"] = self._make_stat_table_override(
            "stats", cfg.get("stats") or {},
            min_val=-99, max_val=999,
        )
        overrides["growth"] = self._make_stat_table_override(
            "growth", cfg.get("growth") or {},
            min_val=0, max_val=200,
        )

        # weapon_types 多选
        overrides["weapon_types"] = self.make_id_list_override(
            "weapon_types",
            list(cfg.get("weapon_types") or []),
            [(w, value_zh(w)) for w in _WEAPON_TYPES],
        )

        # skill_learn
        overrides["skill_learn"] = self._make_skill_learn_override(
            cfg.get("skill_learn") or [])

        # class_skills
        overrides["class_skills"] = self.make_id_list_override(
            "class_skills",
            list(cfg.get("class_skills") or []),
            [(sid, f"{sname}（{sid}）")
             for sid, sname in self.registry.skill_ids()],
        )

        # promote（如果没有被禁用的话）
        if "force_base" not in cfg:
            overrides["promote"] = self._make_promote_override(
                cfg.get("promote"),
                allow_empty_item=False,
            )

        return overrides

    def _make_stat_table_override(
        self, key: str, data: dict, min_val: int, max_val: int,
    ):
        table = StatTable(min_val=min_val, max_val=max_val)
        table.load(data)
        table.changed.connect(lambda: self.form.notify_change(key))

        def getter():
            return table.get_data()
        return table, getter

    def _make_skill_learn_override(self, data: list):
        skill_opts = [(sid, sname)
                      for sid, sname in self.registry.skill_ids()]
        w = SkillLearnEditor(skill_options=skill_opts)
        w.load(data)
        w.changed.connect(
            lambda: self.form.notify_change("skill_learn"))

        def getter():
            return w.get_data()
        return w, getter

    def _make_promote_override(
        self, data: dict | None, allow_empty_item: bool,
    ):
        item_opts = self.registry.key_item_ids()
        class_opts = self.registry.class_ids()
        w = PromoteEditor(
            item_options=item_opts,
            class_options=class_opts,
            allow_empty_item=allow_empty_item,
        )
        w.load(data or {})
        w.changed.connect(lambda: self.form.notify_change("promote"))

        def getter():
            return w.get_data()
        return w, getter