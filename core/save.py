"""SaveMixin：存档 / 读档 / 轮转 / 迁移。

所有 save/load/migrate/rotate 相关逻辑集中在此。
_unit_to_dict / _unit_from_dict 也在这里，它们是持久化的一部分。

v7.1 修复：
    load_game 改为"以存档的 extra_units 为准，地图配置只作兜底"。
    之前地图初始敌人会被地图配置覆盖，导致读档后位置/HP/存活状态全部重置。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from core.constants import (
    GLOBAL_SAVE_PATH, LEGACY_SAVE_PATH, SAVE_DIR,
    default_global_stats, default_global_vars, default_stats,
)
from core.unit import Unit, _init_uses
from core.ui import _console, read_key, show_save_list


class SaveMixin:
    # ---------------- 全局存档 ----------------

    def _save_global(self) -> None:
        os.makedirs(SAVE_DIR, exist_ok=True)
        try:
            with open(GLOBAL_SAVE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.global_vars, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[global_save 写入失败] {e}")

    def _load_global(self) -> None:
        if not os.path.exists(GLOBAL_SAVE_PATH):
            self.global_vars = default_global_vars()
            return
        try:
            with open(GLOBAL_SAVE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self.global_vars = default_global_vars()
            return
        if not isinstance(data, dict):
            data = default_global_vars()
        data.setdefault("achievements", [])
        gs = data.setdefault("global_stats", {})
        for k, v in default_global_stats().items():
            gs.setdefault(k, v)
        self.global_vars = data

    # ---------------- 存档槽管理 ----------------

    def _max_saves(self) -> int:
        return int((self.global_cfg.get("economy") or {}).get("max_saves", 4))

    def _save_slots(self) -> list[str]:
        if not os.path.isdir(SAVE_DIR):
            return []
        files: list[tuple[float, str]] = []
        for fn in os.listdir(SAVE_DIR):
            if not fn.endswith(".json") or fn == "global_save.json":
                continue
            path = os.path.join(SAVE_DIR, fn)
            try:
                files.append((os.path.getmtime(path), path))
            except OSError:
                continue
        files.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in files]

    def _next_save_path(self) -> str:
        os.makedirs(SAVE_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(SAVE_DIR, f"save_{ts}.json")
        n = 1
        while os.path.exists(path):
            path = os.path.join(SAVE_DIR, f"save_{ts}_{n}.json")
            n += 1
        return path

    def _save_label(self, kind: str) -> str:
        map_name = self.map.cfg.get("name", "") if self.map else ""
        if kind == "section":
            return f"{map_name}·章节开始"
        return f"{map_name}·第{self.turn}回合"

    def _rotate_saves(self) -> None:
        slots = self._save_slots()
        max_n = self._max_saves()
        if len(slots) <= max_n:
            return
        entries: list[tuple[str, str]] = []
        for p in slots:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                entries.append((p, d.get("kind", "manual")))
            except (json.JSONDecodeError, OSError):
                entries.append((p, "manual"))
        keep: set[str] = set()
        for p, kind in entries:
            if kind == "section":
                keep.add(p)
                break
        for p, _ in entries:
            if len(keep) >= max_n:
                break
            keep.add(p)
        for p, _ in entries:
            if p not in keep:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def _migrate_legacy_save(self) -> None:
        if not os.path.exists(LEGACY_SAVE_PATH):
            return
        try:
            with open(LEGACY_SAVE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        try:
            mtime = os.path.getmtime(LEGACY_SAVE_PATH)
            data["timestamp"] = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            data.setdefault("label", f"{data.get('map_id', '')}·旧存档")
            data.setdefault("kind", "manual")
            data.setdefault("vars", {})
            data.setdefault("battle_log", [])
            ts = datetime.fromtimestamp(mtime).strftime("%Y%m%d_%H%M%S")
            new_path = os.path.join(SAVE_DIR, f"save_{ts}_legacy.json")
            n = 1
            while os.path.exists(new_path):
                new_path = os.path.join(SAVE_DIR, f"save_{ts}_legacy_{n}.json")
                n += 1
            with open(new_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.remove(LEGACY_SAVE_PATH)
        except (json.JSONDecodeError, OSError):
            pass

    def _list_saves(self) -> list[dict]:
        out: list[dict] = []
        for path in self._save_slots():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                out.append({
                    "path": path,
                    "label": data.get("label", os.path.basename(path)),
                    "turn": data.get("turn", 0),
                    "timestamp": data.get("timestamp", ""),
                    "kind": data.get("kind", "manual"),
                })
            except (json.JSONDecodeError, OSError) as e:
                print(f"[跳过存档 {os.path.basename(path)}] {e}")
                continue
        return out

    # ---------------- 单元序列化 ----------------

    def _unit_to_dict(self, u: Unit) -> dict:
        return {
            "uid": u.uid, "name": u.name, "short": u.short, "faction": u.faction,
            "level": u.level, "exp": u.exp,
            "class_id": getattr(u, "class_id", '') or '',
            "base_stats": dict(u.base_stats),
            "class_stats": dict(u.class_stats),
            "level_gains": dict(u.level_gains),
            "stats": dict(u.stats), "max_stats": dict(u.max_stats),
            "x": u.x, "y": u.y, "alive": u.alive,
            "skills": list(u.skills),
            "items": [dict(it) if isinstance(it, dict) else it for it in u.items],
            "status": list(u.status), "status_turns": dict(u.status_turns),
            "description": u.description, "flags": dict(u.flags),
            "move_type": u.move_type,
            "ai": u.ai, "ai_params": dict(u.ai_params), "retreat_done": u.retreat_done,
            "deployable": u.deployable, "deployed": u.deployed, "is_lord": u.is_lord,
            "drop_gold": u.drop_gold, "drop_item": u.drop_item,
            "drop_items": [dict(d) for d in (u.drop_items or [])],
            "_lv_since_guarantee": u._lv_since_guarantee,
            "_gain_since_guarantee": u._gain_since_guarantee,
            "has_promoted": u.has_promoted,
            "support_ranks": dict(u.support_ranks),
            "support_points": dict(u.support_points),
            "equipped": getattr(u, "equipped", None),
        }

    def _unit_from_dict(self, ud: dict) -> Unit:
        uid = ud.get("uid", "")
        if uid and uid in self.units_cfg:
            u = self._instantiate_unit(uid, {
                "x": ud["x"], "y": ud["y"], "faction": ud["faction"],
                "ai": ud.get("ai", "aggressive"),
            })
            cid = ud.get("class_id") or ""
            if cid and cid in self.classes and cid != u.class_id:
                new_cls = self.classes[cid]
                u.class_cfg = new_cls
                u.class_id = cid
        else:
            u = Unit(name=ud["name"], short=ud["short"], faction=ud["faction"],
                     level=ud["level"], exp=ud["exp"])
            u.uid = uid
        _cid2 = ud.get("class_id") or ""
        if _cid2 and _cid2 in self.classes:
            _c = self.classes[_cid2]
            u.class_stats = dict(_c.get("stats", {}) or {})
            _cg = dict(_c.get("growth", {}) or {})
            u.class_growth = _cg
            u.growth = {k: u.base_growth.get(k, 0) + _cg.get(k, 0)
                        for k in set(u.base_growth) | set(_cg)}
            u.move_type = _c.get("move_type", u.move_type)
            u._recompute_stats()
        if "base_stats" in ud:
            u.base_stats = dict(ud["base_stats"])
            u.class_stats = dict(ud.get("class_stats", {})) if not (_cid2 and _cid2 in self.classes) else u.class_stats
            u.level_gains = dict(ud.get("level_gains", {}))
        else:
            old_max = ud.get("max_stats") or ud.get("stats") or {}
            u.base_stats = dict(old_max)
            u.class_stats = {}
            u.level_gains = {}
        u._recompute_stats()
        u.level = ud["level"]
        u.exp = ud["exp"]
        old_cur_hp = (ud.get("stats") or {}).get("hp", u.max_stats.get("hp", 1))
        u.stats["hp"] = min(old_cur_hp, u.max_stats.get("hp", 1))
        u.x, u.y = ud["x"], ud["y"]
        u.alive = ud.get("alive", True)
        u.skills = list(ud.get("skills", []))
        u.items = list(ud.get("items", []))
        u.normalize_items(self.items)
        u.status = list(ud.get("status", []))
        u.status_turns = dict(ud.get("status_turns", {}))
        u.description = ud.get("description", u.description)
        u.flags = dict(ud.get("flags", {}))
        u.move_type = ud.get("move_type", u.move_type)
        u.ai = ud.get("ai", u.ai)
        u.ai_params = dict(ud.get("ai_params", u.ai_params))
        u.retreat_done = bool(ud.get("retreat_done", False))
        u.deployable = bool(ud.get("deployable", u.deployable))
        u.deployed = bool(ud.get("deployed", u.deployed))
        u.is_lord = bool(ud.get("is_lord", u.is_lord))
        u.drop_gold = int(ud.get("drop_gold", 0))
        u.drop_item = str(ud.get("drop_item", ""))
        u.drop_items = [dict(d) for d in (ud.get("drop_items") or [])]
        u._lv_since_guarantee = int(ud.get("_lv_since_guarantee", 0))
        u._gain_since_guarantee = int(ud.get("_gain_since_guarantee", 0))
        u.has_promoted = bool(ud.get("has_promoted", False))
        u.support_ranks = dict(ud.get("support_ranks", {}))
        u.support_points = dict(ud.get("support_points", {}))
        eq = ud.get("equipped")
        u.equipped = eq if eq and eq in u.items_ids() else None
        u.acted = False
        u.moved_this_turn = False
        if ud.get("class_id"):
            u._recompute_stats()
            _hp = int((ud.get("stats") or {}).get("hp", u.stats.get("hp", 1)))
            u.stats["hp"] = max(1 if u.alive else 0, min(_hp, u.max_stats.get("hp", 1)))
            if u.equipped and u.equipped not in [i for i, _c in u.usable_weapons(self.items)]:
                _wu = u.usable_weapons(self.items)
                u.equipped = _wu[0][0] if _wu else None
        return u

    def _normalize_warehouse(self, raw: list) -> list[dict]:
        out: list[dict] = []
        for it in raw:
            if isinstance(it, str):
                out.append({"id": it, "uses": _init_uses(self.items.get(it, {}))})
            elif isinstance(it, dict) and "id" in it:
                if "uses" in it:
                    out.append({"id": it["id"], "uses": it["uses"]})
                else:
                    out.append({"id": it["id"],
                                "uses": _init_uses(self.items.get(it["id"], {}))})
        return out

    # ---------------- 存档 / 读档 ----------------

    def save_game(self, kind: str = "manual") -> str:
        if not self.map_id:
            return ""
        os.makedirs(SAVE_DIR, exist_ok=True)
        path = self._next_save_path()
        roster_uids = {u.uid for u in self.roster}
        extra_units = [self._unit_to_dict(u) for u in self.units
                       if u.uid not in roster_uids
                       and not u.flags.get("summoned")]
        data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label": self._save_label(kind),
            "kind": kind,
            "map_id": self.map_id, "turn": self.turn, "gold": self.gold,
            "difficulty": self.difficulty,
            "mode": self.mode,
            "vars": dict(self.vars),
            "battle_log": list(self.battle_log)[-100:],
            "_had_enemies": self._had_enemies,
            "_victory_handled": self._victory_handled,
            "fired_events": sorted(self._fired_events),
            "fired_talks": sorted(self._fired_talks),
            "warehouse": [dict(it) if isinstance(it, dict) else it for it in self.warehouse],
            "roster": [self._unit_to_dict(u) for u in self.roster],
            "extra_units": extra_units,
            "stats": dict(self.stats),
            "pending_blessings": list(self.pending_blessings),
            "fired_terrain": [list(k) for k in self._fired_terrain],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            print(f"[存档失败] {e}")
            try:
                os.remove(path)
            except OSError:
                pass
            return ""
        self._save_global()
        self._rotate_saves()
        return path

    def load_game(self, path: str) -> str | None:
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[读档失败] {e}")
            return None
        map_id = data.get("map_id")
        if map_id not in self.maps:
            print(f"[读档失败] 地图 {map_id} 不存在")
            return None
        self._build_map_only(map_id)
        self.difficulty = str(data.get("difficulty") or "normal")
        self.mode = str(data.get("mode") or self._legacy_mode_id())
        self.turn = int(data.get("turn", 1))
        self.gold = int(data.get("gold", self._initial_gold()))
        self.warehouse = self._normalize_warehouse(list(data.get("warehouse", [])))
        self.vars = dict(data.get("vars", {}))
        self.battle_log = list(data.get("battle_log", []))
        self._had_enemies = bool(data.get("_had_enemies", True))
        self._victory_handled = bool(data.get("_victory_handled", False))
        self._fired_events = set(data.get("fired_events", []))
        self._fired_talks = set(data.get("fired_talks", []))
        self._fired_terrain = {tuple(k) for k in data.get("fired_terrain", [])}
        self.pending_blessings = list(data.get("pending_blessings", []))
        self.roster = [self._unit_from_dict(ud) for ud in data.get("roster", [])]

        saved_stats = dict(data.get("stats", {}))
        for k, v in default_stats().items():
            saved_stats.setdefault(k, v)
        self.stats = saved_stats

        # ── 单位恢复：以存档的 extra_units 为准，地图配置只作兜底 ──
        cfg = self.maps[map_id]
        roster_uids = {u.uid for u in self.roster}

        # 地图配置里的非 roster 单位（基线）
        map_unit_cfgs: dict[str, dict] = {}
        for u in cfg.get("units", []):
            uid = u["id"]
            if uid in roster_uids:
                continue
            map_unit_cfgs[uid] = u

        # 存档里的非 roster 单位（含敌人/友军/增援）
        saved_by_uid: dict[str, dict] = {}
        for ud in data.get("extra_units", []):
            uid = ud.get("uid", "")
            if not uid or uid in roster_uids:
                continue
            saved_by_uid[uid] = ud

        self.units = []
        # 1. 地图配置单位：有存档用存档（位置/HP/状态/存活以存档为准），
        #    旧存档没有 extra_units 时回退到地图初始配置
        for uid, u_cfg in map_unit_cfgs.items():
            if uid in saved_by_uid:
                self.units.append(self._unit_from_dict(saved_by_uid[uid]))
            else:
                self.units.append(self._instantiate_unit(uid, u_cfg))

        # 2. 存档里多出来的单位（剧情增援，地图配置里没有）
        for uid, ud in saved_by_uid.items():
            if uid not in map_unit_cfgs:
                self.units.append(self._unit_from_dict(ud))

        # 3. 部署的 roster 单位
        for u in self.roster:
            if u.deployed and u.alive:
                self.units.append(u)

        self.map.units = self.units
        self.state = "play"
        return data.get("kind", "manual")

    # ---------------- 读档选择界面 ----------------

    def _show_save_select(self) -> str | None:
        while True:
            saves = self._list_saves()
            result = show_save_list(saves, self._max_saves())
            if result == "back":
                return None
            if result.startswith("delete:"):
                idx = int(result.split(":")[1])
                if 0 <= idx < len(saves):
                    try:
                        os.remove(saves[idx]["path"])
                    except OSError as e:
                        print(f"[删除失败] {e}")
                continue
            if result.startswith("load:"):
                idx = int(result.split(":")[1])
                if 0 <= idx < len(saves):
                    kind = self.load_game(saves[idx]["path"])
                    if kind is not None:
                        return kind
                    _console.print("[red]读档失败[/red]")
                    read_key()