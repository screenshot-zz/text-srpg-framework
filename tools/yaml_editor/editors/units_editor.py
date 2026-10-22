"""config/units.yaml 编辑器。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QVBoxLayout

from ..yaml_io import YamlFile
from ..zh_map import value_zh
from ..widgets.form_base import FormBase
from ..widgets.stat_table import StatTable
from ..widgets.promote_editor import PromoteEditor
from ..widgets.coords_table import CoordsTable
from ._tab_base import TabBase


class UnitsEditor(FormBase):
    def __init__(self, units_path: str | Path, registry, parent=None):
        super().__init__(parent)
        self.yaml_file = YamlFile(units_path)
        self.registry = registry

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tab = _UnitsTab(self)
        layout.addWidget(self._tab)

        self._tab.refresh_list()

    def refresh(self) -> None:
        self.yaml_file.load()
        self._tab.refresh_list()


# ============================================================
# 单 Tab
# ============================================================
class _UnitsTab(TabBase):
    def tab_name(self) -> str:
        return "单位"

    def matches(self, cfg: dict) -> bool:
        return True

    def default_new_item(self) -> dict:
        return {
            "name": "新单位",
            "short": "新",
            "class": "",
            "level": 1,
            "exp": 0,
            "deployable": False,
            "start_deployed": False,
            "is_lord": False,
            "stats": {},
            "growth": {},
            "skills": [],
            "items": [],
            "ai": "aggressive",
            "drop_gold": 0,
            "description": "",
        }

    def fields_for(self, cfg: dict) -> list[tuple[str, Any]]:
        return [
            ("name", cfg.get("name", "")),
            ("short", cfg.get("short", "")),
            ("class", cfg.get("class", "")),
            ("level", int(cfg.get("level", 1) or 1)),
            ("exp", int(cfg.get("exp", 0) or 0)),
            ("deployable", bool(cfg.get("deployable", False))),
            ("start_deployed", bool(cfg.get("start_deployed", False))),
            ("is_lord", bool(cfg.get("is_lord", False))),
            ("stats", cfg.get("stats") or {}),
            ("growth", cfg.get("growth") or {}),
            ("skills", cfg.get("skills") or []),
            ("items", cfg.get("items") or []),
            ("ai", cfg.get("ai", "aggressive")),
            ("drop_gold", int(cfg.get("drop_gold", 0) or 0)),
            ("drop_item", cfg.get("drop_item", "") or ""),
            ("drop_items", cfg.get("drop_items") or []),
            ("promote", cfg.get("promote") or {}),
            ("description", cfg.get("description", "")),
            ("flags", cfg.get("flags") or {}),
        ]

    def field_overrides(self, cfg: dict) -> dict:
        overrides: dict = {}

        class_ids = self.registry.class_ids()
        class_opts = [("", "（未选择）")] + [
            (cid, f"{cname}（{cid}）") for cid, cname in class_ids
        ]
        overrides["class"] = self.make_combo_override(
            "class",
            current=cfg.get("class", "") or "",
            options=class_opts,
        )

        overrides["stats"] = self._make_stat_table_override(
            "stats", cfg.get("stats") or {},
            min_val=-99, max_val=999,
        )
        overrides["growth"] = self._make_stat_table_override(
            "growth", cfg.get("growth") or {},
            min_val=0, max_val=200,
        )

        overrides["skills"] = self.make_id_list_override(
            "skills",
            list(cfg.get("skills") or []),
            [(sid, f"{sname}（{sid}）")
             for sid, sname in self.registry.skill_ids()],
        )

        overrides["items"] = self.make_id_list_override(
            "items",
            list(cfg.get("items") or []),
            [(iid, f"{iname}（{iid}）")
             for iid, iname in self.registry.item_ids()],
        )

        overrides["ai"] = self.make_combo_override(
            "ai",
            current=cfg.get("ai", "aggressive") or "aggressive",
            options=[(aid, f"{aname}（{aid}）")
                     for aid, aname in self.registry.ai_profile_ids()],
        )

        item_ids = self.registry.item_ids()
        drop_opts = [("", "（无）")] + [
            (iid, f"{iname}（{iid}）") for iid, iname in item_ids
        ]
        overrides["drop_item"] = self.make_combo_override(
            "drop_item",
            current=cfg.get("drop_item", "") or "",
            options=drop_opts,
        )

        # ⭐ 多物品掉落表
        drop_table = CoordsTable(columns=[
            {"key": "id", "label": "物品", "type": "combo", "options": item_ids},
            {"key": "chance", "label": "概率(%)", "type": "int", "min": 1, "max": 100, "default": 100},
        ])
        drop_table.load(cfg.get("drop_items") or [])
        drop_table.changed.connect(lambda: self.form.notify_change("drop_items"))
        
        def drop_items_getter():
            data = drop_table.get_data()
            out = []
            for item in data:
                if not item.get("id"):
                    continue
                # 如果概率是 100，就删掉 chance 字段，保持 YAML 简洁
                if item.get("chance") == 100:
                    item.pop("chance", None)
                out.append(item)
            return out
            
        overrides["drop_items"] = (drop_table, drop_items_getter)

        overrides["promote"] = self._make_promote_override(
            cfg.get("promote"),
            allow_empty_item=True,
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