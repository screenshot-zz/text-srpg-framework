"""config/skills.yaml 编辑器。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QVBoxLayout, QTabWidget, QComboBox, QCheckBox,
)
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from ..yaml_io import YamlFile
from ..zh_map import value_zh
from ..widgets.form_base import FormBase
from ._tab_base import TabBase


_TARGET_OPTIONS = ["self", "ally", "enemy"]
_STAT_BONUS_KEYS = ["attack", "defense", "hit", "avoid", "crit"]


class SkillsEditor(FormBase):
    def __init__(self, skills_path: str | Path, registry, parent=None):
        super().__init__(parent)
        self.yaml_file = YamlFile(skills_path)
        self.registry = registry

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self._passive_tab = _PassiveTab(self)
        self._active_tab = _ActiveTab(self)

        self.tabs.addTab(self._passive_tab, "被动")
        self.tabs.addTab(self._active_tab, "主动")

        layout.addWidget(self.tabs)

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._refresh_all_lists()

    def _on_tab_changed(self, idx: int) -> None:
        self.tabs.widget(idx).refresh_list()

    def _refresh_all_lists(self) -> None:
        for i in range(self.tabs.count()):
            self.tabs.widget(i).refresh_list()

    def refresh(self) -> None:
        self.yaml_file.load()
        self._refresh_all_lists()


class _PassiveTab(TabBase):
    def tab_name(self) -> str:
        return "被动"

    def matches(self, cfg: dict) -> bool:
        return cfg.get("type") != "active"

    def default_new_item(self) -> dict:
        return {
            "name": "新被动技能",
            "description": "",
            "formula": {},
        }

    def field_defaults(self):
        return {
            "__aura": {
                "radius": 2,
                "hit_bonus": 10,
                "avoid_bonus": 0,
                "crit_bonus": 0,
                "damage_bonus": 0,
            },
        }

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        formula = cfg.get("formula") or {}
        fields: list[tuple[str, Any]] = [
            ("name", cfg.get("name", "")),
            ("description", cfg.get("description", "")),
            ("__enable_damage", _has_damage(formula)),
            ("__enable_aura", "aura" in formula),
            ("__enable_stat_bonus", "stat_bonus" in formula),
        ]
        if _has_damage(formula):
            fields.append(
                ("__damage_bonus_expr", formula.get("damage_bonus", "")))
            fields.append(
                ("__damage_condition_expr", formula.get("condition", "")))
        if "aura" in formula:
            aura = formula.get("aura") or {}
            # ⭐ 直接把整个字典丢给子表单
            fields.append(("__aura", aura))
        if "stat_bonus" in formula:
            sb = formula.get("stat_bonus") or {}
            for stat in _STAT_BONUS_KEYS:
                fields.append((f"__stat_{stat}", int(sb.get(stat, 0))))
        return fields

    def field_overrides(self, cfg: dict) -> dict:
        overrides: dict = {}
        formula = cfg.get("formula") or {}

        for cb_key, effect_key in [
            ("__enable_damage", "damage_bonus"),
            ("__enable_aura", "aura"),
            ("__enable_stat_bonus", "stat_bonus"),
        ]:
            enabled = (
                effect_key in formula
                or (effect_key == "damage_bonus" and "condition" in formula)
            )
            cb = QCheckBox()
            cb.setChecked(enabled)
            cb.toggled.connect(
                lambda checked, e=effect_key: self._toggle_effect(e, checked)
            )
            overrides[cb_key] = (cb, lambda c=cb: c.isChecked())

        return overrides

    def _toggle_effect(self, effect_key: str, checked: bool) -> None:
        cfg = self.yaml_file.get(self._current_key)
        if not isinstance(cfg, dict):
            return

        formula = cfg.get("formula")
        if not isinstance(formula, (dict, CommentedMap)):
            formula = CommentedMap()
            cfg["formula"] = formula

        if checked:
            if effect_key == "damage_bonus":
                formula["damage_bonus"] = DoubleQuotedScalarString("2")
                formula["condition"] = DoubleQuotedScalarString(
                    "moved_this_turn")
            elif effect_key == "aura":
                formula["aura"] = self.yaml_file.ensure_commented(
                    {"radius": 2, "hit_bonus": 10})
            elif effect_key == "stat_bonus":
                formula["stat_bonus"] = self.yaml_file.ensure_commented(
                    {"crit": 15})
        else:
            if effect_key == "damage_bonus":
                formula.pop("damage_bonus", None)
                formula.pop("condition", None)
            else:
                formula.pop(effect_key, None)

        self.yaml_file.mark_dirty()
        self.reload_current_form()

    def _on_field_changed(self, key: str, value: Any) -> None:
        if self._loading_form or self._current_key is None:
            return
        if key.startswith("__enable_"):
            return

        cfg = self.yaml_file.get(self._current_key)
        if not isinstance(cfg, dict):
            return

        if not key.startswith("__"):
            super()._on_field_changed(key, value)
            return

        formula = cfg.get("formula")
        if not isinstance(formula, (dict, CommentedMap)):
            formula = CommentedMap()
            cfg["formula"] = formula

        if key == "__damage_bonus_expr":
            formula["damage_bonus"] = value
        elif key == "__damage_condition_expr":
            formula["condition"] = value
        elif key == "__aura":
            # ⭐ 接收整个子表单的字典更新
            formula["aura"] = self.yaml_file.ensure_commented(value)
        elif key.startswith("__stat_"):
            sb = formula.get("stat_bonus")
            if not isinstance(sb, (dict, CommentedMap)):
                sb = CommentedMap()
                formula["stat_bonus"] = sb
            stat_name = key[len("__stat_"):]
            if value == 0:
                sb.pop(stat_name, None)
            else:
                sb[stat_name] = value

        self.yaml_file.mark_dirty()


class _ActiveTab(TabBase):
    def tab_name(self) -> str:
        return "主动"

    def matches(self, cfg: dict) -> bool:
        return cfg.get("type") == "active"

    def default_new_item(self) -> dict:
        return {
            "name": "新主动技能",
            "description": "",
            "type": "active",
            "target": ["self", "ally"],
            "range": 1,
        }

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        special = cfg.get("special") or ""
        fields: list[tuple[str, Any]] = [
            ("name", cfg.get("name", "")),
            ("description", cfg.get("description", "")),
            ("__special_type", special),
        ]
        if special in ("steal", "dance"):
            return fields

        formula = cfg.get("formula") or {}
        fields.append(("__effect_heal", "heal" in formula))
        fields.append(("__effect_damage", "damage" in formula))
        if "heal" in formula:
            fields.append(("__heal_expr", formula.get("heal", "")))
        if "damage" in formula:
            fields.append(("__damage_expr", formula.get("damage", "")))
        fields.append(("target", cfg.get("target") or ["self", "ally"]))
        fields.append(("range", cfg.get("range", 1)))
        fields.append(("condition", cfg.get("condition", "")))
        fields.append(("aoe_radius", cfg.get("aoe_radius", 0)))
        return fields

    def field_overrides(self, cfg: dict) -> dict:
        overrides: dict = {}

        combo = QComboBox()
        combo.addItem("（通用效果）", "")
        combo.addItem("偷窃（steal）", "steal")
        combo.addItem("舞蹈（dance）", "dance")
        current = cfg.get("special") or ""
        for i in range(combo.count()):
            if combo.itemData(i) == current:
                combo.setCurrentIndex(i)
                break
        combo.currentIndexChanged.connect(
            lambda _idx, c=combo: self._on_special_changed(c))
        overrides["__special_type"] = (
            combo, lambda c=combo: c.currentData() or "")

        if not cfg.get("special"):
            formula = cfg.get("formula") or {}
            for cb_key, effect_key, default in [
                ("__effect_heal", "heal", "10 + int*2"),
                ("__effect_damage", "damage", "int*2"),
            ]:
                cb = QCheckBox()
                cb.setChecked(effect_key in formula)
                cb.toggled.connect(
                    lambda checked, e=effect_key, d=default:
                        self._toggle_effect(e, d, checked))
                overrides[cb_key] = (cb, lambda c=cb: c.isChecked())

            target = cfg.get("target") or ["self", "ally"]
            if isinstance(target, str):
                target = [target]
            overrides["target"] = self.make_id_list_override(
                "target", list(target),
                [(t, value_zh(t)) for t in _TARGET_OPTIONS])

        return overrides

    def _on_special_changed(self, combo: QComboBox) -> None:
        new_special = combo.currentData() or ""
        cfg = self.yaml_file.get(self._current_key)
        if not isinstance(cfg, dict):
            return
        old_special = cfg.get("special") or ""
        if old_special == new_special:
            return

        if new_special:
            cfg["special"] = new_special
            for k in ("formula", "target", "range", "condition", "aoe_radius"):
                if k in cfg:
                    del cfg[k]
        else:
            if "special" in cfg:
                del cfg["special"]
            if "target" not in cfg:
                cfg["target"] = self.yaml_file.ensure_commented(
                    ["self", "ally"])
            if "range" not in cfg:
                cfg["range"] = 1

        self.yaml_file.mark_dirty()
        self.reload_current_form()

    def _toggle_effect(
        self, effect_key: str, default_expr: str, checked: bool
    ) -> None:
        cfg = self.yaml_file.get(self._current_key)
        if not isinstance(cfg, dict):
            return
        formula = cfg.get("formula")
        if not isinstance(formula, (dict, CommentedMap)):
            formula = CommentedMap()
            cfg["formula"] = formula
        if checked:
            formula[effect_key] = DoubleQuotedScalarString(default_expr)
        else:
            formula.pop(effect_key, None)
            if not formula:
                del cfg["formula"]
        self.yaml_file.mark_dirty()
        self.reload_current_form()

    def _on_field_changed(self, key: str, value: Any) -> None:
        if self._loading_form or self._current_key is None:
            return
        if key in ("__special_type", "__effect_heal", "__effect_damage"):
            return

        if not key.startswith("__"):
            super()._on_field_changed(key, value)
            return

        cfg = self.yaml_file.get(self._current_key)
        if not isinstance(cfg, dict):
            return

        if key == "__heal_expr":
            formula = cfg.get("formula")
            if not isinstance(formula, (dict, CommentedMap)):
                formula = CommentedMap()
                cfg["formula"] = formula
            formula["heal"] = value
            self.yaml_file.mark_dirty()
        elif key == "__damage_expr":
            formula = cfg.get("formula")
            if not isinstance(formula, (dict, CommentedMap)):
                formula = CommentedMap()
                cfg["formula"] = formula
            formula["damage"] = value
            self.yaml_file.mark_dirty()


def _has_damage(formula: dict) -> bool:
    return "damage_bonus" in formula or "condition" in formula