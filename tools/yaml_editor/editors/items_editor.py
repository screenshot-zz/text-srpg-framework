"""config/items.yaml 编辑器。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QVBoxLayout, QTabWidget, QComboBox, QLineEdit
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from ..yaml_io import YamlFile
from ..zh_map import value_zh
from ..widgets.form_base import FormBase
from ._tab_base import TabBase


_WEAPON_TYPES = ["sword", "axe", "lance", "bow", "fang", "anima", "light", "dark"]
_TARGET_OPTIONS = ["self", "ally", "enemy"]
_EFFECT_TYPES = ["heal", "repair", "revive", "summon", "teleport", "script"]


class ItemsEditor(FormBase):
    def __init__(self, items_path: str | Path, registry, parent=None):
        super().__init__(parent)
        self.yaml_file = YamlFile(items_path)
        self.registry = registry

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self._weapon_tab = _WeaponTab(self)
        self._staff_tab = _StaffTab(self)
        self._consumable_tab = _ConsumableTab(self)
        self._key_tab = _KeyTab(self)

        self.tabs.addTab(self._weapon_tab, "武器")
        self.tabs.addTab(self._staff_tab, "杖")
        self.tabs.addTab(self._consumable_tab, "消耗品")
        self.tabs.addTab(self._key_tab, "钥匙")

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


# ============================================================
# Tab 1：武器
# ============================================================
class _WeaponTab(TabBase):
    def tab_name(self) -> str:
        return "武器"

    def matches(self, cfg: dict) -> bool:
        return (cfg.get("type") == "weapon"
                and cfg.get("weapon_type") != "staff")

    _FIELDS = [
        "name", "description", "weapon_type", "damage_type",
        "might", "hit", "crit", "range", "durability", "price",
        "effective_against",
    ]

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        for k in self._FIELDS:
            v = cfg.get(k)
            if k == "weapon_type":
                out.append((k, v if v else "sword"))
            elif k in ("damage_type", "durability", "effective_against"):
                out.append((k, v))
            elif k in ("might", "hit", "crit", "price"):
                out.append((k, v if v is not None else 0))
            elif k == "range":
                out.append((k, v if v is not None else 1))
            else:
                out.append((k, v if v is not None else ""))
        return out

    def default_new_item(self) -> dict:
        return {
            "name": "新武器",
            "description": "",
            "type": "weapon",
            "weapon_type": "sword",
            "might": 5, "hit": 50, "crit": 0,
            "range": 1,
            "price": 300,
            "durability": 20,
        }

    def field_overrides(self, cfg: dict) -> dict:
        overrides = {}

        overrides["weapon_type"] = self.make_combo_override(
            "weapon_type",
            current=cfg.get("weapon_type") or "sword",
            options=[(v, value_zh(v)) for v in _WEAPON_TYPES],
        )

        overrides["damage_type"] = self.make_combo_override(
            "damage_type",
            current=cfg.get("damage_type"),
            options=[(None, "（物理，默认）"), ("magic", "魔法")],
        )

        ea = cfg.get("effective_against")
        if isinstance(ea, str):
            ea_list = [ea]
        elif isinstance(ea, list):
            ea_list = list(ea)
        else:
            ea_list = []
        groups = self.registry.group_ids()
        overrides["effective_against"] = self.make_id_list_override(
            "effective_against",
            ea_list,
            [(g, value_zh(g)) for g in groups],
        )

        # ⭐ 把射程改成输入框
        range_edit = QLineEdit(str(cfg.get("range", "1")))
        range_edit.setPlaceholderText("填纯数字（如 1）或范围（如 1-2）")
        range_edit.textChanged.connect(lambda _t: self.form.notify_change("range"))
        overrides["range"] = (range_edit, lambda: range_edit.text())

        return overrides


# ============================================================
# Tab 2：杖
# ============================================================
class _StaffTab(TabBase):
    def tab_name(self) -> str:
        return "杖"

    def matches(self, cfg: dict) -> bool:
        return (cfg.get("type") == "weapon"
                and cfg.get("weapon_type") == "staff")

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        effect = _get_staff_effect_type(cfg)
        fields: list[tuple[str, Any]] = [
            ("name", cfg.get("name", "")),
            ("description", cfg.get("description", "")),
            ("__effect_type", effect),
        ]
        if effect == "heal":
            fields.append(("formula", cfg.get("formula") or {}))
        elif effect == "summon":
            fields.append(("unit_id", cfg.get("unit_id", "")))
        elif effect == "script":
            fields.append(("story", cfg.get("story", "")))

        fields.extend([
            ("range", cfg.get("range", 1)),
            ("target", cfg.get("target") or ["self", "ally"]),
            ("condition", cfg.get("condition", "")),
            ("aoe_radius", cfg.get("aoe_radius")),
            ("durability", cfg.get("durability")),
            ("price", cfg.get("price", 300)),
        ])
        return fields

    def default_new_item(self) -> dict:
        return {
            "name": "新杖",
            "description": "",
            "type": "weapon",
            "weapon_type": "staff",
            "no_attack": True,
            "formula": {"heal": "8 + int*2"},
            "range": 1,
            "target": ["self", "ally"],
            "condition": "hp < max_hp",
            "durability": 12,
            "price": 300,
        }

    def field_defaults(self):
        return {
            "formula": {
                "heal": DoubleQuotedScalarString("8 + int*2"),
            },
        }

    def field_overrides(self, cfg: dict) -> dict:
        overrides = {}

        overrides["__effect_type"] = self._make_effect_type_override(cfg)

        target = cfg.get("target") or ["self", "ally"]
        if isinstance(target, str):
            target = [target]
        overrides["target"] = self.make_id_list_override(
            "target",
            list(target),
            [(t, value_zh(t)) for t in _TARGET_OPTIONS],
        )

        if _get_staff_effect_type(cfg) == "summon":
            unit_ids = self.registry.unit_ids()
            options = [("", "（未选择）")] + [(uid, f"{n}（{uid}）") for uid, n in unit_ids]
            overrides["unit_id"] = self.make_combo_override(
                "unit_id",
                current=cfg.get("unit_id", ""),
                options=options,
            )

        # ⭐ 把射程改成输入框
        range_edit = QLineEdit(str(cfg.get("range", "1")))
        range_edit.setPlaceholderText("填纯数字（如 1）或范围（如 1-2）")
        range_edit.textChanged.connect(lambda _t: self.form.notify_change("range"))
        overrides["range"] = (range_edit, lambda: range_edit.text())

        return overrides

    def _make_effect_type_override(self, cfg: dict):
        current = _get_staff_effect_type(cfg)

        combo = QComboBox()
        combo.addItem("（无效果）", "")
        for t in _EFFECT_TYPES:
            combo.addItem(f"{value_zh(t)}（{t}）", t)
        for i in range(combo.count()):
            if combo.itemData(i) == current:
                combo.setCurrentIndex(i)
                break

        def on_change(_idx):
            new_type = combo.currentData()
            if new_type == _get_staff_effect_type(cfg):
                return
            _set_staff_effect_type(cfg, new_type)
            self.yaml_file.mark_dirty()
            self.reload_current_form()

        combo.currentIndexChanged.connect(on_change)

        def getter():
            return combo.currentData()
        return combo, getter


# ============================================================
# Tab 3：消耗品
# ============================================================
class _ConsumableTab(TabBase):
    def tab_name(self) -> str:
        return "消耗品"

    def matches(self, cfg: dict) -> bool:
        return cfg.get("type") == "consumable"

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        return [
            ("name", cfg.get("name", "")),
            ("description", cfg.get("description", "")),
            ("formula", cfg.get("formula") or {}),
            ("target", cfg.get("target") or ["self", "ally"]),
            ("range", cfg.get("range", 1)),
            ("condition", cfg.get("condition", "")),
            ("price", cfg.get("price", 150)),
            ("consume", cfg.get("consume", True)),
            ("story", cfg.get("story")),
        ]

    def default_new_item(self) -> dict:
        return {
            "name": "新消耗品",
            "description": "",
            "type": "consumable",
            "formula": {"heal": "10"},
            "price": 150,
            "target": ["self", "ally"],
            "range": 1,
            "condition": "hp < max_hp",
        }

    def field_defaults(self):
        return {
            "formula": {
                "heal": DoubleQuotedScalarString("10"),
                "cure_status": CommentedSeq(),
                "apply_status": DoubleQuotedScalarString(""),
            },
        }

    def field_overrides(self, cfg: dict) -> dict:
        overrides = {}
        target = cfg.get("target") or ["self", "ally"]
        if isinstance(target, str):
            target = [target]
        overrides["target"] = self.make_id_list_override(
            "target",
            list(target),
            [(t, value_zh(t)) for t in _TARGET_OPTIONS],
        )

        # ⭐ 把射程改成输入框
        range_edit = QLineEdit(str(cfg.get("range", "1")))
        range_edit.setPlaceholderText("填纯数字（如 1）或范围（如 1-2）")
        range_edit.textChanged.connect(lambda _t: self.form.notify_change("range"))
        overrides["range"] = (range_edit, lambda: range_edit.text())

        return overrides


# ============================================================
# Tab 4：钥匙
# ============================================================
class _KeyTab(TabBase):
    def tab_name(self) -> str:
        return "钥匙"

    def matches(self, cfg: dict) -> bool:
        return cfg.get("type") == "key"

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        return [
            ("name", cfg.get("name", "")),
            ("description", cfg.get("description", "")),
        ]

    def default_new_item(self) -> dict:
        return {
            "name": "新钥匙",
            "description": "",
            "type": "key",
        }


def _get_staff_effect_type(cfg: dict) -> str:
    special = cfg.get("special")
    if special:
        return str(special)
    f = cfg.get("formula")
    if isinstance(f, (dict, CommentedMap)) and "heal" in f:
        return "heal"
    return ""


def _set_staff_effect_type(cfg: dict, new_type: str) -> None:
    if "special" in cfg:
        del cfg["special"]
    if isinstance(cfg.get("formula"), (dict, CommentedMap)):
        f = cfg["formula"]
        if "heal" in f:
            del f["heal"]
        if not f:
            del cfg["formula"]

    if new_type == "heal":
        if ("formula" not in cfg
                or not isinstance(cfg["formula"], (dict, CommentedMap))):
            cfg["formula"] = CommentedMap()
        cfg["formula"]["heal"] = DoubleQuotedScalarString("8 + int*2")
    elif new_type == "summon":
        cfg["special"] = "summon"
        if "unit_id" not in cfg:
            cfg["unit_id"] = ""
    elif new_type in ("repair", "revive", "teleport", "script"):
        cfg["special"] = new_type