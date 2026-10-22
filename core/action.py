"""ActionMixin：玩家操作入口。

含行动选单 / 移动 / 攻击 / 道具 / 杖 / 技能 / 交换 / 商店 / 偷窃 / 舞蹈。
"攻击"到"选目标"为止在 action，战斗结算进 battle。

v7.1：
    select_and_act 移动时允许穿过并停留在友军格（两人自动交换位置）。
    取消行动时完整还原：被交换的友军先回 target，自己再回 origin。

v7.2：
    商店改为配置驱动（global.yaml::shops）。
    - 地形 shop: <shop_id> → 走对应商店配置
    - 地形 shop: true → 走兜底（全量 items.yaml 带 price 的）
    - map events 的 {trigger: interact, shop: <id>} 也能触发商店
    - map.yaml 的 shops: [{x, y, shop}] 坐标映射优先于地形字段

v7.4：
    经验结算：
    - _do_attack 不再自己算经验（搬到 battle._resolve_battle 内部逐次 strike 结算）
    - _use_staff / _do_dance / _do_steal 末尾调 self._grant_exp 给经验
"""
from __future__ import annotations

from core.combat import (
    effective_stats, predict_combat, predict_combat_pair, triangle_bonus,
)
from core.constants import DIRS
from core.formula import ev, _DotDict
from core.map import IMPASSABLE, is_hostile
from core.ui import (
    STAT_NAMES, _console, read_key, render_screen, show_combat_predict_pair,
)
from core.unit import Unit


class ActionMixin:
    # ---------------- 行动菜单 ----------------

    def _interact_available(self, unit) -> bool:
        for e in self.map.cfg.get("events", []):
            if e.get("trigger") != "interact":
                continue
            if e.get("x") != unit.x or e.get("y") != unit.y:
                continue
            # v7.2：interact 事件必须带 story 或 shop 才有意义
            if not e.get("story") and not e.get("shop"):
                continue
            ev_id = e.get("id") or e.get("story") or e.get("shop")
            once = e.get("once", True)
            if once and ev_id in self._fired_events:
                continue
            cond = e.get("condition", "")
            if cond:
                try:
                    if not ev(str(cond), self._event_condition_ctx(unit)):
                        continue
                except Exception:
                    continue
            return True
        return False

    def _has_adjacent_ally(self, unit) -> bool:
        for u in self.units:
            if u is unit or not u.alive or u.faction != unit.faction:
                continue
            if abs(u.x - unit.x) + abs(u.y - unit.y) == 1:
                return True
        return False

    def _active_skills(self, unit) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        seen: set[str] = set()
        for sid in list(unit.skills) + list((unit.class_cfg or {}).get("class_skills") or []):
            if sid in seen:
                continue
            cfg = self.skills.get(sid)
            if cfg and cfg.get("type") == "active":
                seen.add(sid)
                out.append((sid, cfg))
        return out

    def select_and_act(self, unit) -> None:
        rng = self.map.move_range(unit, allow_ally_stay=True)
        origin = (unit.x, unit.y)
        prev_moved_this_turn = unit.moved_this_turn
        target = self._pick_cell(rng, unit)
        if target is None:
            return
        moved = target != origin
        # 目标格有友军 → 交换位置（可穿可停）；记录以便取消时完整还原
        occupant = self.map.unit_at(*target) if target != origin else None
        swapped = False
        if (occupant is not None and occupant is not unit
                and occupant.faction == unit.faction):
            unit.x, unit.y = target
            occupant.x, occupant.y = origin
            swapped = True
        else:
            unit.x, unit.y = target
        if moved:
            unit.moved_this_turn = True
        self._check_events(unit, "enter")
        if not unit.alive:
            return

        while True:
            options: list[tuple[str, str]] = []
            terrain = self.map.terrain_at(unit.x, unit.y)
            # 商店判定优先级：坐标映射 > 地形字符字段
            shop_id = self._shop_id_at(unit.x, unit.y)
            terrain_shop = terrain.get("shop")
            if shop_id is None and isinstance(terrain_shop, str):
                shop_id = terrain_shop
            has_shop = bool(terrain_shop) or bool(shop_id)
            if self._interact_available(unit):
                options.append(("visit", "访问"))
            if has_shop:
                options.append(("shop", "商店"))
            if self._has_adjacent_ally(unit):
                options.append(("trade", "交换"))
            options.append(("attack", "攻击"))
            if self._active_skills(unit):
                options.append(("skill", "技能"))
            if unit.usable_staves(self.items):
                options.append(("staff", "杖"))
            options.append(("item", "道具"))
            options.append(("wait", "待机"))

            action = self._action_menu(unit, options)
            if action is None:
                # 完整还原：先挪走自己（让出 target），再把友军放回 target 格
                if not unit.alive:
                    return
                unit.x, unit.y = origin
                if swapped and occupant.alive:
                    occupant.x, occupant.y = target
                unit.moved_this_turn = prev_moved_this_turn
                return
            if action == "visit":
                self._check_events(unit, "interact")
                unit.acted = True
                return
            if action == "shop":
                self.open_shop(unit, shop_id)
                unit.acted = True
                return
            if action == "trade":
                if self._exchange_item(unit):
                    unit.acted = True
                    return
                continue
            if action == "attack":
                if self._do_attack(unit):
                    unit.acted = True
                    return
                continue
            if action == "skill":
                if self._use_skill(unit):
                    unit.acted = True
                    return
                continue
            if action == "staff":
                if self._use_staff(unit):
                    unit.acted = True
                    return
                continue
            if action == "item":
                if self._use_item(unit):
                    unit.acted = True
                    return
                continue
            if action == "wait":
                unit.acted = True
                return

    def _action_menu(self, unit, options: list[tuple[str, str]]) -> str | None:
        while True:
            msg = "请选择行动：" + "　".join(f"{i}.{name}" for i, (_k, name) in enumerate(options, 1))
            render_screen(self, selected=unit, message=msg + "　Q.取消")
            k = read_key()
            if k in ("esc", "quit"):
                return None
            if k.isdigit():
                i = int(k)
                if 1 <= i <= len(options):
                    return options[i - 1][0]

    def _pick_cell(self, allowed: dict, unit) -> tuple[int, int] | None:
        cx, cy = unit.x, unit.y
        while True:
            cost = allowed.get((cx, cy))
            hint = f"　移动消耗 {cost}" if cost is not None else ""
            render_screen(self, highlight=set(allowed.keys()), cursor=(cx, cy), selected=unit,
                          message=f"方向键移动，回车确认，Q 取消{hint}")
            k = read_key()
            if k == "enter":
                return (cx, cy)
            if k in ("esc", "quit"):
                return None
            d = DIRS.get(k)
            if d:
                nx, ny = cx + d[0], cy + d[1]
                if (nx, ny) in allowed:
                    cx, cy = nx, ny

    # ---------------- 攻击 ----------------

    def _choose_target(self, unit, targets: list) -> object | None:
        if not targets:
            return None
        target_cells = {(t.x, t.y): t for t in targets}
        cx, cy = targets[0].x, targets[0].y
        while True:
            current = target_cells.get((cx, cy))
            msg_parts = ["方向键移动光标到敌人格，回车确认攻击，Q 取消"]
            if current is not None:
                if not unit.can_attack_at(self.items,
                                          abs(unit.x - current.x) + abs(unit.y - current.y)):
                    msg_parts.append("（当前武器打不到此目标）")
                    render_screen(self, cursor=(cx, cy), selected=current,
                                  message="\n".join(msg_parts))
                    k = read_key()
                    if k in ("esc", "quit"):
                        return None
                    d = DIRS.get(k)
                    if d:
                        nx, ny = cx + d[0], cy + d[1]
                        if 0 <= nx < self.map.width and 0 <= ny < self.map.height:
                            cx, cy = nx, ny
                    continue
                unit.auto_equip_for(self.items,
                                    abs(unit.x - current.x) + abs(unit.y - current.y))
                pred = predict_combat(unit, current, self)
                msg_parts.append(f"目标：{current.name}（HP {current.stats['hp']}/{current.max_stats['hp']}）")
                msg_parts.append(f"我方 命中{int(pred['hit_rate'])}% 伤害{int(pred['damage'])} 必杀{int(pred['crit_rate'])}%")
                if self._can_counter(current, unit):
                    back = predict_combat(current, unit, self)
                    msg_parts.append(f"反击 命中{int(back['hit_rate'])}% 伤害{int(back['damage'])}")
                else:
                    msg_parts.append("反击 射程外，不会反击")
                _th, _td, relation = triangle_bonus(unit, current, self)
                if relation == "advantage":
                    msg_parts.append(f"武器克制：命中+{_th} 伤害+{_td}")
                elif relation == "disadvantage":
                    msg_parts.append(f"武器被克：命中{_th} 伤害{_td}")
                atk_sup = pred.get("support_bonus_details") or []
                if atk_sup:
                    parts = []
                    for d in atk_sup:
                        pieces = []
                        if d.get("hit"):
                            pieces.append(f"命中+{d['hit']}")
                        if d.get("crit"):
                            pieces.append(f"必杀+{d['crit']}")
                        if pieces:
                            parts.append(f"{d['name']} Lv{d['rank']}（{' '.join(pieces)}）")
                    if parts:
                        msg_parts.append(f"支援：{'、'.join(parts)}")
            render_screen(self, cursor=(cx, cy), selected=current or unit,
                          message="\n".join(msg_parts))
            k = read_key()
            if k == "enter":
                if current is not None:
                    return current
            elif k in ("esc", "quit"):
                return None
            else:
                d = DIRS.get(k)
                if d:
                    nx, ny = cx + d[0], cy + d[1]
                    if 0 <= nx < self.map.width and 0 <= ny < self.map.height:
                        cx, cy = nx, ny

    def _all_attack_targets(self, unit) -> list:
        out = []
        for u in self.units:
            if not u.alive or not is_hostile(unit, u):
                continue
            if unit.can_attack_at(self.items, abs(u.x - unit.x) + abs(u.y - unit.y)):
                out.append(u)
        return out

    def _covering_weapons(self, unit, victim) -> list[tuple[str, dict]]:
        dist = abs(unit.x - victim.x) + abs(unit.y - victim.y)
        out: list[tuple[str, dict]] = []
        for iid, cfg in unit.usable_weapons(self.items):
            lo, hi = Unit.range_span(cfg.get("range"))
            if lo <= dist <= hi:
                out.append((iid, cfg))
        return out

    def _pick_weapon_for(self, unit, victim) -> bool:
        covering = self._covering_weapons(unit, victim)
        if not covering:
            weps = unit.usable_weapons(self.items)
            if not weps:
                self._pause("没有可用的武器。", cursor=(unit.x, unit.y))
            else:
                names = "、".join(c.get("name", i) for i, c in weps)
                dist = abs(unit.x - victim.x) + abs(unit.y - victim.y)
                self._pause(f"{victim.name} 在 {dist} 格外，现有武器（{names}）都打不到。",
                            cursor=(unit.x, unit.y))
            return False
        ids = [i for i, _c in covering]
        if unit.equipped in ids:
            return True
        unit.equipped = covering[0][0]
        return True

    def _do_attack(self, unit) -> bool:
        targets = self._all_attack_targets(unit)
        if not targets:
            self._pause("射程内没有可攻击的敌人。", cursor=(unit.x, unit.y))
            return False
        victim = self._choose_target(unit, targets)
        if victim is None:
            return False
        if not self._pick_weapon_for(unit, victim):
            return False
        while True:
            covering = self._covering_weapons(unit, victim)
            wname = self.items.get(unit.equipped, {}).get("name", "裸手")
            hint = "　W 换武器" if len(covering) > 1 else ""
            can_counter = self._can_counter(victim, unit)
            atk_doubles = self._can_double(unit, victim)
            dfn_doubles = self._can_double(victim, unit) and can_counter
            pair = predict_combat_pair(unit, victim, self,
                                       can_counter=can_counter,
                                       atk_doubles=atk_doubles, dfn_doubles=dfn_doubles)
            render_screen(self, cursor=(victim.x, victim.y), selected=unit,
                          message=f"武器：{wname}{hint}　回车确认攻击　Q 取消")
            show_combat_predict_pair(unit, victim, pair)
            k = read_key()
            if k == "enter":
                break
            if k in ("esc", "quit"):
                return False
            if k == "w" and len(covering) > 1:
                parts = []
                for i, (iid, cfg) in enumerate(covering, 1):
                    lo, hi = Unit.range_span(cfg.get("range"))
                    rr = str(lo) if lo == hi else f"{lo}-{hi}"
                    mark = "*" if iid == unit.equipped else " "
                    parts.append(f"{mark}{i}.{cfg.get('name', iid)}(射程{rr} 威力{cfg.get('might', 0)} 命中{cfg.get('hit', 0)})")
                _console.print("切换武器：" + "　".join(parts))
                k2 = read_key()
                if k2.isdigit() and 1 <= int(k2) <= len(covering):
                    unit.equipped = covering[int(k2) - 1][0]
        # 经验在 _resolve_battle 内部结算（battle.py::_resolve_battle → _calc_combat_exp）
        lines = self._resolve_battle(unit, victim)
        self._append_achievement_lines(lines)
        for line in lines:
            self._log_battle(line)
        self._pause("\n".join(lines), cursor=(unit.x, unit.y))
        return True

    # ---------------- 技能 ----------------

    def _use_skill(self, unit) -> bool:
        active = self._active_skills(unit)
        if not active:
            self._pause("没有可用的主动技能。", cursor=(unit.x, unit.y))
            return False
        while True:
            msg = "选择技能：" + "　".join(
                f"{i}.{sk.get('name', sid)}" for i, (sid, sk) in enumerate(active, 1)
            ) + "　Q.取消"
            render_screen(self, selected=unit, message=msg)
            k = read_key()
            if k in ("esc", "quit"):
                return False
            if k.isdigit() and 1 <= int(k) <= len(active):
                sid, skill = active[int(k) - 1]
                break
        sp = skill.get("special")
        if sp == "steal":
            return self._do_steal(unit)
        if sp == "dance":
            return self._do_dance(unit)
        target_factions = skill.get("target", ["self", "ally"])
        rng = int(skill.get("range", 1))
        candidates: list = []
        for u in self.units:
            if not u.alive:
                continue
            if u is unit:
                if "self" in target_factions:
                    candidates.append(u)
                continue
            if is_hostile(unit, u):
                if "enemy" not in target_factions:
                    continue
            else:
                if "ally" not in target_factions:
                    continue
            if abs(u.x - unit.x) + abs(u.y - unit.y) > rng:
                continue
            candidates.append(u)
        if not candidates:
            self._pause(f"{skill.get('name', sid)} 无可用目标。", cursor=(unit.x, unit.y))
            return False
        target = self._pick_target(unit, skill, candidates)
        if target is None:
            return False
        cond = skill.get("condition", "")
        if cond and not ev(str(cond), self._item_condition_ctx(unit, target, skill)):
            self._pause(f"无法对 {target.name} 使用 {skill.get('name', sid)}：条件不满足。",
                        cursor=(target.x, target.y))
            return False
        aoe_r = int(skill.get("aoe_radius", 0))
        if aoe_r > 0:
            target_is_enemy = is_hostile(unit, target)
            affected = [u for u in self.units if u.alive
                        and is_hostile(unit, u) == target_is_enemy
                        and abs(u.x - target.x) + abs(u.y - target.y) <= aoe_r]
        else:
            affected = [target]
        lines: list[str] = []
        f = skill.get("formula") or {}
        eff = effective_stats(unit, self.status)
        killed: list = []
        if "heal" in f:
            for u in affected:
                heal = int(ev(str(f["heal"]), {
                    "max_hp": u.max_stats.get("hp", 0),
                    "hp": u.stats.get("hp", 0),
                    "int": eff.get("int", 0), "level": unit.level,
                }))
                before = u.stats.get("hp", 0)
                u.stats["hp"] = min(before + heal, u.max_stats.get("hp", before))
                lines.append(f"{u.name} 恢复了 {u.stats['hp'] - before} 点生命。"
                             f"（HP {u.stats['hp']}/{u.max_stats.get('hp', 0)}）")
        if "damage" in f:
            for v in affected:
                dmg = int(ev(str(f["damage"]), {
                    "int": eff.get("int", 0), "level": unit.level,
                    "max_hp": v.max_stats.get("hp", 0), "hp": v.stats.get("hp", 0),
                }))
                v.stats["hp"] = max(0, v.stats.get("hp", 0) - dmg)
                lines.append(f"{unit.name} 用 {skill.get('name', sid)} 对 {v.name} 造成 {dmg} 点伤害！")
                if v.stats["hp"] <= 0:
                    v.alive = False
                    lines.append(f"{v.name} 被击败了！")
                    killed.append(v)
        self.stats["skills_used"] += 1
        self.global_vars["global_stats"]["total_skills_used"] += 1
        if unit.faction in ("player", "ally"):
            for v in killed:
                if v.faction == "enemy":
                    self.stats["kills"] += 1
                    self.global_vars["global_stats"]["total_kills"] += 1
                    if getattr(v, "drop_gold", 0) > 0:
                        self.gold += v.drop_gold
                        self.stats["gold_earned"] += v.drop_gold
                        self.global_vars["global_stats"]["total_gold_earned"] += v.drop_gold
                        lines.append(f"击败 {v.name}，获得 {v.drop_gold}G！")
                        v.drop_gold = 0
        if not lines:
            lines.append(f"{unit.name} 使用了 {skill.get('name', sid)}，但没有效果。")
        self._append_achievement_lines(lines)
        for line in lines:
            self._log_battle(line)
        self._pause("\n".join(lines), cursor=(unit.x, unit.y))
        return True

    # ---------------- 道具 ----------------

    def _item_condition_ctx(self, user, target, item: dict | None = None) -> dict:
        target_hp = target.stats.get("hp", 0)
        target_max_hp = target.max_stats.get("hp", 0)
        dist = abs(user.x - target.x) + abs(user.y - target.y)
        rng = int((item or {}).get("range", 1))
        in_range = 1 if (target is user or dist <= rng) else 0
        ctx = {
            "hp": target_hp, "max_hp": target_max_hp,
            "user_hp": user.stats.get("hp", 0),
            "user_max_hp": user.max_stats.get("hp", 0),
            "target_hp": target_hp, "target_max_hp": target_max_hp,
            "target_uid": target.uid,
            "target_can_recruit": 1 if target.flags.get("can_recruit") else 0,
            "target_is_enemy": 1 if target.faction == "enemy" else 0,
            "target_is_ally": 1 if target.faction in ("player", "ally") else 0,
            "has_poison": 1 if "poison" in target.status else 0,
            "in_range": in_range,
            "vars": _DotDict(self.vars),
        }
        for k, v in self.vars.items():
            ctx[f"var_{k}"] = v
        return ctx

    def _pick_target(self, user, item: dict, candidates: list):
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        target_cells = {(t.x, t.y): t for t in candidates}
        cx, cy = candidates[0].x, candidates[0].y
        item_name = item.get("name", "")
        rng = int(item.get("range", 1))
        while True:
            current = target_cells.get((cx, cy))
            msg = f"选择 {item_name} 的目标（方向键，回车确认，Q 取消）"
            if current is not None:
                dist = abs(user.x - current.x) + abs(user.y - current.y)
                if current is user:
                    range_note = "（自身）"
                elif dist > rng:
                    range_note = f"（距离 {dist}/{rng}，✗超出范围）"
                else:
                    range_note = f"（距离 {dist}/{rng}，✓在范围内）"
                cond = item.get("condition", "")
                cond_ok = True
                if cond:
                    cond_ok = bool(ev(str(cond), self._item_condition_ctx(user, current, item)))
                msg += (f"\n当前：{current.name}（HP {current.stats['hp']}/{current.max_stats['hp']}）"
                        f" {range_note}　{'✓可用' if cond_ok else '✗条件不满足'}")
            render_screen(self, cursor=(cx, cy), selected=current or user, message=msg)
            k = read_key()
            if k == "enter" and current is not None:
                return current
            elif k in ("esc", "quit"):
                return None
            else:
                d = DIRS.get(k)
                if d:
                    nx, ny = cx + d[0], cy + d[1]
                    if 0 <= nx < self.map.width and 0 <= ny < self.map.height:
                        cx, cy = nx, ny

    def _use_item(self, unit) -> bool:
        usable: list[tuple[str, dict, int | None]] = []
        for it in unit.items:
            iid = it["id"] if isinstance(it, dict) else it
            icfg = self.items.get(iid, {})
            if icfg.get("type") != "consumable":
                continue
            uses = it.get("uses") if isinstance(it, dict) else None
            usable.append((iid, icfg, uses))
        if not usable:
            self._pause("没有可用的消耗品。", cursor=(unit.x, unit.y))
            return False
        while True:
            parts = []
            for i, (iid, icfg, uses) in enumerate(usable, 1):
                name = icfg.get("name", iid)
                if uses is not None:
                    name += f"（剩{uses}）"
                parts.append(f"{i}.{name}")
            msg = "选择道具：" + "　".join(parts) + "　Q.取消"
            render_screen(self, selected=unit, message=msg)
            k = read_key()
            if k in ("esc", "quit"):
                return False
            if k.isdigit() and 1 <= int(k) <= len(usable):
                iid, it, _uses = usable[int(k) - 1]
                break
        target_factions = it.get("target", ["self", "ally"])
        rng = int(it.get("range", 1))
        candidates: list = []
        for u in self.units:
            if not u.alive:
                continue
            if u is unit:
                if "self" in target_factions:
                    candidates.append(u)
                continue
            if is_hostile(unit, u):
                if "enemy" not in target_factions:
                    continue
            else:
                if "ally" not in target_factions:
                    continue
            if abs(u.x - unit.x) + abs(u.y - unit.y) > rng:
                continue
            candidates.append(u)
        if not candidates:
            self._pause(f"{it.get('name', iid)} 无可用目标（射程 {rng}）。", cursor=(unit.x, unit.y))
            return False
        target = self._pick_target(unit, it, candidates)
        if target is None:
            return False
        cond = it.get("condition", "")
        if cond and not ev(str(cond), self._item_condition_ctx(unit, target, it)):
            self._pause(f"无法对 {target.name} 使用 {it.get('name', iid)}：条件不满足。",
                        cursor=(target.x, target.y))
            return False
        lines: list[str] = []
        f = it.get("formula") or {}
        if "heal" in f:
            heal = int(ev(str(f["heal"]), {
                "max_hp": target.max_stats.get("hp", 0),
                "hp": target.stats.get("hp", 0),
            }))
            before = target.stats.get("hp", 0)
            target.stats["hp"] = min(before + heal, target.max_stats.get("hp", before))
            lines.append(f"{target.name} 恢复了 {target.stats['hp'] - before} 点生命。")
            lines.append(f"当前 HP：{target.stats['hp']}/{target.max_stats.get('hp', 0)}")
        if "cure_status" in f:
            to_cure = f["cure_status"]
            if isinstance(to_cure, str):
                to_cure = [to_cure]
            cured = []
            for sid in to_cure:
                if sid in target.status:
                    target.status.remove(sid)
                    target.status_turns.pop(sid, None)
                    cured.append(self.status.get(sid, {}).get("name", sid))
            if cured:
                lines.append(f"{target.name} 的 {'、'.join(cured)} 状态解除了。")
            else:
                lines.append(f"{target.name} 没有需要解除的状态。")
        if "apply_status" in f:
            sid = f["apply_status"]
            cfg = self.status.get(sid, {})
            if cfg:
                if sid not in target.status:
                    target.status.append(sid)
                target.status_turns[sid] = int(cfg.get("duration", 1))
                lines.append(f"{target.name} 获得了 {cfg.get('name', sid)} 状态。")
            else:
                lines.append(f"[配置错误] 状态 {sid} 未在 status.yaml 中定义。")
        self.stats["items_used"] += 1
        self.global_vars["global_stats"]["total_items_used"] += 1
        unit.consume_uses(iid, 1)
        if target is not unit and self._is_support_pair(unit.uid, target.uid):
            g = int((self._support_cfg().get("gain") or {}).get("use_item", 0))
            self._add_support_points(unit, target, g)
        story_id = it.get("story")
        if story_id and story_id in self.stories:
            if lines:
                self._pause("\n".join(lines), cursor=(target.x, target.y))
            from core.event import run_story
            run_story(story_id, self)
            self._check_achievements()
            return True
        if not lines:
            lines.append(f"{target.name} 受到了 {it.get('name', iid)} 的影响。")
        self._append_achievement_lines(lines)
        for line in lines:
            self._log_battle(line)
        self._pause("\n".join(lines), cursor=(target.x, target.y))
        return True

    # ---------------- 转职道具 / 偷窃 ----------------

    def _consume_promote_item(self, unit) -> tuple[bool, str]:
        iid = unit.promote_item
        if not iid:
            return True, ""
        for i, it in enumerate(unit.items):
            cur = it.get("id") if isinstance(it, dict) else it
            if cur == iid:
                unit.items.pop(i)
                return True, "unit"
        for i, it in enumerate(self.warehouse):
            cur = it.get("id") if isinstance(it, dict) else it
            if cur == iid:
                self.warehouse.pop(i)
                return True, "warehouse"
        return False, ""

    def _stealable_targets(self, unit) -> list:
        out = []
        for u in self.units:
            if not u.alive or u is unit or not is_hostile(unit, u):
                continue
            if abs(u.x - unit.x) + abs(u.y - unit.y) != 1:
                continue
            if u.flags.get("already_stolen"):
                continue
            if bool(u.items):
                out.append(u)
        return out

    def _do_steal(self, unit) -> bool:
        targets = self._stealable_targets(unit)
        if not targets:
            self._pause("身边没有值得下手且带东西的目标。", cursor=(unit.x, unit.y))
            return False
        if len(targets) == 1:
            victim = targets[0]
        else:
            while True:
                parts = [f"{i}.{u.name}" for i, u in enumerate(targets, 1)]
                render_screen(self, selected=unit,
                              message="偷谁？（数字键）" + "　".join(parts) + "　Q.取消")
                k = read_key()
                if k in ("esc", "quit"):
                    return False
                if k.isdigit() and 1 <= int(k) <= len(targets):
                    victim = targets[int(k) - 1]
                    break
        formulas = self.global_cfg.get("formulas", {})
        expr = str(formulas.get("steal_rate", "40"))
        ctx = {
            "user_spd": unit.stats.get("spd", 0),
            "user_level": unit.level,
            "user_luk": unit.stats.get("luk", 0),
            "target_spd": victim.stats.get("spd", 0),
            "target_hp": victim.stats.get("hp", 0),
            "target_max_hp": victim.max_stats.get("hp", 0),
        }
        import random as _rnd
        rate = int(max(5, min(95, ev(expr, ctx))))
        roll = _rnd.randint(1, 100)
        lines: list[str] = []
        if roll <= rate:
            it = victim.items[_rnd.randrange(len(victim.items))]
            victim.items.remove(it)
            unit.items.append(it)
            iid = it.get("id", "") if isinstance(it, dict) else str(it)
            iname = self.items.get(iid, {}).get("name", iid)
            lines.append(f"{unit.name} 妙手一探（{rate}%）→ 成功！偷到了 {victim.name} 的{iname}！")
            # v7.4：偷窃成功给经验（只给玩家）
            if unit.faction == "player":
                exp = int(ev(str(formulas.get("exp_steal", "10")), {}))
                self._grant_exp(unit, lines, exp)
        else:
            lines.append(f"{unit.name} 试图行窃（{rate}%）→ 被 {victim.name} 发现了！")
        victim.flags["already_stolen"] = True
        self._append_achievement_lines(lines)
        for line in lines:
            self._log_battle(line)
        self._pause("\n".join(lines), cursor=(unit.x, unit.y))
        return True

    # ---------------- 杖 ----------------

    def _staff_candidates(self, unit, scfg):
        rng = Unit.range_span(scfg.get("range"))[1]
        special = scfg.get("special")
        if special in ("summon", "script"):
            return [], False
        if special == "revive":
            c = [u for u in self.units
                 if not u.alive and u.faction == unit.faction
                 and abs(u.x - unit.x) + abs(u.y - unit.y) <= rng]
            return c, True
        c = [u for u in self.units
             if u.alive and u.faction == unit.faction
             and abs(u.x - unit.x) + abs(u.y - unit.y) <= rng]
        if special == "teleport":
            c = [u for u in c if u is not unit]
        return c, True

    def _staff_heal_amount(self, unit, scfg, v) -> int:
        eff = effective_stats(unit, self.status)
        return int(ev(str(scfg["formula"]["heal"]), {
            "int": eff.get("int", 0), "level": unit.level,
            "max_hp": v.max_stats.get("hp", 0), "hp": v.stats.get("hp", 0),
        }))

    def _free_cell_near_staff(self, unit, rng: int):
        best = None
        for y in range(self.map.height):
            for x in range(self.map.width):
                d = abs(x - unit.x) + abs(y - unit.y)
                if d < 1 or d > rng:
                    continue
                if self.map.unit_at(x, y) is not None:
                    continue
                if self.map.move_cost(x, y, unit.move_type) >= IMPASSABLE:
                    continue
                if best is None or d < best[0]:
                    best = (d, x, y)
        return (best[1], best[2]) if best else None

    def _teleport_dest(self, unit, target):
        for dx, dy in DIRS.values():
            nx, ny = target.x + dx, target.y + dy
            if not self.map.in_bounds(nx, ny):
                continue
            if self.map.unit_at(nx, ny) is not None:
                continue
            if self.map.move_cost(nx, ny, unit.move_type) >= IMPASSABLE:
                continue
            return (nx, ny)
        return None

    def _use_staff(self, unit) -> bool:
        staves = unit.usable_staves(self.items)
        if not staves:
            self._pause("没有可使用的杖（或职业无法使用）。", cursor=(unit.x, unit.y))
            return False
        while True:
            parts = []
            for i, (iid, cfg) in enumerate(staves, 1):
                uses = unit.get_item_uses(iid)
                nm = cfg.get("name", iid) + (f"（剩{uses}）" if uses is not None else "")
                parts.append(f"{i}.{nm}")
            render_screen(self, selected=unit,
                          message="选择杖：" + "　".join(parts) + "　Q.取消")
            k = read_key()
            if k in ("esc", "quit"):
                return False
            if k.isdigit() and 1 <= int(k) <= len(staves):
                iid, scfg = staves[int(k) - 1]
                break
        name = scfg.get("name", iid)
        special = scfg.get("special")
        lines: list[str] = []

        def _staff_exp() -> None:
            """v7.4：使用杖给经验（只给玩家）。"""
            if unit.faction == "player":
                formulas = self.global_cfg.get("formulas", {})
                exp = int(ev(str(formulas.get("exp_staff", "15")), {}))
                self._grant_exp(unit, lines, exp)

        if special == "script":
            if scfg.get("story") and scfg.get("story") in self.stories:
                from core.event import run_story
                run_story(scfg["story"], self)
            from core.event import run_action
            for act in (scfg.get("actions") or []):
                run_action(act, self)
            lines.append(f"{unit.name} 使用了 {name}，奇异的低语回荡在战场上……")
            unit.consume_uses(iid, 1)
            _staff_exp()
            self._after_staff(unit, iid, name, lines)
            return True
        if special == "summon":
            mid = scfg.get("unit_id")
            if not mid or mid not in self.units_cfg:
                self._pause(f"[配置错误] 召唤目标 {mid} 未在 units.yaml 定义",
                            cursor=(unit.x, unit.y))
                return False
            if any(u.uid == mid for u in self.units):
                self._pause("魔物已在场（或残魂未散），无法再次召唤。",
                            cursor=(unit.x, unit.y))
                return False
            rng = Unit.range_span(scfg.get("range"))[1]
            cell = self._free_cell_near_staff(unit, rng)
            if cell is None:
                self._pause("周围没有可落脚的空格。", cursor=(unit.x, unit.y))
                return False
            m = self._instantiate_unit(mid, {"x": cell[0], "y": cell[1],
                                             "faction": unit.faction})
            m.deployable = False
            m.deployed = False
            m.flags["summoned"] = True
            self.units.append(m)
            self.map.units = self.units
            lines.append(f"{unit.name} 使用 {name}，{m.name} 在 ({cell[0]},{cell[1]}) 应召而来！")
            unit.consume_uses(iid, 1)
            _staff_exp()
            self._after_staff(unit, iid, name, lines)
            return True

        candidates, need = self._staff_candidates(unit, scfg)
        if need and not candidates:
            self._pause(f"{name} 范围内没有可用目标。", cursor=(unit.x, unit.y))
            return False
        if special == "revive":
            while True:
                parts = [f"{i}.{u.name}（Lv{u.level}）" for i, u in enumerate(candidates, 1)]
                render_screen(self, selected=unit,
                              message=f"复活谁？{name}　" + "　".join(parts) + "　Q.取消")
                k = read_key()
                if k in ("esc", "quit"):
                    return False
                if k.isdigit() and 1 <= int(k) <= len(candidates):
                    target = candidates[int(k) - 1]
                    break
            if self.map.unit_at(target.x, target.y) is not None:
                self._pause("遗体所在格已被占用，无处安放。", cursor=(unit.x, unit.y))
                return False
            target.alive = True
            target.stats["hp"] = max(1, target.max_stats.get("hp", 1) // 2)
            target.status = []
            target.status_turns = {}
            target.acted = True
            target.moved_this_turn = False
            lines.append(f"{unit.name} 使用 {name}，{target.name} 以半血复活了！")
        else:
            target = self._pick_target(unit, scfg, candidates)
            if target is None:
                return False
            cond = scfg.get("condition", "")
            if cond and not ev(str(cond), self._item_condition_ctx(unit, target, scfg)):
                self._pause(f"无法对 {target.name} 使用 {name}：条件不满足。",
                            cursor=(target.x, target.y))
                return False
            if special == "teleport":
                dest = self._teleport_dest(unit, target)
                if dest is None:
                    self._pause(f"{target.name} 身边无处落脚，传送失败。",
                                cursor=(unit.x, unit.y))
                    return False
                lines.append(f"{unit.name} 化作一道白光，传送到 {target.name} 身边 "
                             f"({dest[0]},{dest[1]})！")
                unit.x, unit.y = dest
            elif special == "repair":
                done = False
                best = None
                for it in target.items:
                    wiid = it.get("id") if isinstance(it, dict) else it
                    wcfg = self.items.get(wiid, {})
                    dur = wcfg.get("durability")
                    if wcfg.get("type") != "weapon" or dur in (None, 0) or wcfg.get("no_attack"):
                        continue
                    cur = target.get_item_uses(wiid)
                    if cur is not None and cur < dur:
                        if best is None or (cur / dur) < (best[1] / best[2]):
                            best = (wiid, cur, dur)
                if best:
                    wiid, cur, dur = best
                    for it in target.items:
                        if isinstance(it, dict) and it.get("id") == wiid:
                            it["uses"] = dur
                            break
                    wnm = self.items.get(wiid, {}).get("name", wiid)
                    lines.append(f"{name} 的光芒流淌过 {wnm}，裂痕尽复（耐久回满 {dur}）！")
                    done = True
                if not done:
                    self._pause(f"{target.name} 没有需要修复的武器。", cursor=(unit.x, unit.y))
                    return False
            else:
                f = scfg.get("formula") or {}
                if "heal" in f:
                    r = int(scfg.get("aoe_radius", 0) or 0)
                    pool = [target]
                    if r > 0:
                        pool = [u for u in self.units
                                if u.alive and u.faction == unit.faction
                                and abs(u.x - target.x) + abs(u.y - target.y) <= r]
                    for v in pool:
                        heal = self._staff_heal_amount(unit, scfg, v)
                        before = v.stats.get("hp", 0)
                        v.stats["hp"] = min(before + heal, v.max_stats.get("hp", before))
                        gained = v.stats["hp"] - before
                        tag = f"（范围治疗 {len(pool)} 人）" if r > 0 and v is not target else ""
                        lines.append(f"{v.name} 恢复 {gained} 点生命"
                                     f"（HP {v.stats['hp']}/{v.max_stats.get('hp', 0)}）{tag}")
                else:
                    self._pause(f"{name} 未配置效果。", cursor=(unit.x, unit.y))
                    return False
        unit.consume_uses(iid, 1)
        if (target is not None and target is not unit
                and self._is_support_pair(unit.uid, target.uid)):
            g = int((self._support_cfg().get("gain") or {}).get("use_staff", 0))
            self._add_support_points(unit, target, g)
        _staff_exp()
        self._after_staff(unit, iid, name, lines)
        return True

    def _after_staff(self, unit, iid, name, lines) -> None:
        if unit.get_item_uses(iid) is None and iid not in unit.items_ids():
            lines.append(f"{unit.name} 的{name}已耗尽！")
        self.stats["items_used"] += 1
        self.global_vars["global_stats"]["total_items_used"] += 1
        for line in lines:
            self._log_battle(line)
        self._pause("\n".join(lines), cursor=(unit.x, unit.y))

    # ---------------- 舞蹈 / 交换 ----------------

    def _do_dance(self, unit) -> bool:
        partners = [u for u in self.units
                    if u.alive and u is not unit and u.faction == unit.faction
                    and abs(u.x - unit.x) + abs(u.y - unit.y) == 1]
        if not partners:
            self._pause("身边没有可以共舞的同伴。", cursor=(unit.x, unit.y))
            return False
        while True:
            parts = [f"{i}.{u.name}" for i, u in enumerate(partners, 1)]
            render_screen(self, selected=unit,
                          message="为谁而舞？（数字键）" + "　".join(parts) + "　Q.取消")
            k = read_key()
            if k in ("esc", "quit"):
                return False
            if k.isdigit() and 1 <= int(k) <= len(partners):
                target = partners[int(k) - 1]
                break
        target.acted = False
        target.moved_this_turn = False
        lines = [f"{unit.name} 翩翩起舞！{target.name} 重获行动的机会！"]
        # v7.4：舞蹈给经验（只给玩家）
        if unit.faction == "player":
            formulas = self.global_cfg.get("formulas", {})
            exp = int(ev(str(formulas.get("exp_dance", "10")), {}))
            self._grant_exp(unit, lines, exp)
        for line in lines:
            self._log_battle(line)
        self._pause("\n".join(lines), cursor=(unit.x, unit.y))
        return True

    def _exchange_item(self, unit) -> bool:
        allies = [u for u in self.units
                  if u.alive and u is not unit and u.faction == unit.faction
                  and abs(u.x - unit.x) + abs(u.y - unit.y) == 1]
        if not allies:
            self._pause("周围没有可交换的队友。", cursor=(unit.x, unit.y))
            return False
        if len(allies) == 1:
            partner = allies[0]
        else:
            while True:
                msg = "选择交换对象：" + "　".join(
                    f"{i}.{u.name}" for i, u in enumerate(allies, 1)
                ) + "　Q.取消"
                render_screen(self, selected=unit, message=msg)
                k = read_key()
                if k in ("esc", "quit"):
                    return False
                if k.isdigit() and 1 <= int(k) <= len(allies):
                    partner = allies[int(k) - 1]
                    break
        if not unit.items:
            self._pause(f"{unit.name} 没有可交换的道具。", cursor=(unit.x, unit.y))
            return False
        while True:
            msg = f"把 {unit.name} 的哪件道具交给 {partner.name}？　Q.取消"
            lines = [msg]
            for i, it in enumerate(unit.items, 1):
                iid = it["id"] if isinstance(it, dict) else it
                name = self.items.get(iid, {}).get("name", iid)
                if isinstance(it, dict):
                    uses = it.get("uses")
                    if uses is not None:
                        name += f"（剩{uses}）"
                lines.append(f"  {i}. {name}")
            render_screen(self, selected=unit, message="\n".join(lines))
            k = read_key()
            if k in ("esc", "quit"):
                return False
            if k.isdigit() and 1 <= int(k) <= len(unit.items):
                idx = int(k) - 1
                it = unit.items.pop(idx)
                partner.items.append(it)
                iid = it["id"] if isinstance(it, dict) else it
                name = self.items.get(iid, {}).get("name", iid)
                self._pause(f"{unit.name} 把 {name} 交给了 {partner.name}。",
                            cursor=(unit.x, unit.y))
                return True

    # ---------------- 商店（v7.2 配置驱动） ----------------

    def _shop_id_at(self, x: int, y: int) -> str | None:
        """按坐标查 map.yaml 的 shops 段。

        优先级：坐标映射 > 地形字段（调用方处理）> 兜底全量
        """
        for entry in (self.map.cfg.get("shops") or []):
            if not isinstance(entry, dict):
                continue
            if int(entry.get("x", -1)) == x and int(entry.get("y", -1)) == y:
                return entry.get("shop")
        return None

    def _shop_cfg(self, shop_id: str | None) -> dict | None:
        """归一化商店配置。

        shop_id 有值且在 global.yaml::shops 里 → 用配置
        shop_id 为 None / 找不到 → 兜底：所有 items.yaml 里带 price 的
        返回 None → 商店无商品

        归一化后的 goods 每项：{item, price, name, description}
        """
        shops = self.global_cfg.get("shops") or {}

        if shop_id and shop_id in shops:
            raw = shops[shop_id] or {}
            goods: list[dict] = []
            for g in (raw.get("goods") or []):
                if isinstance(g, str):
                    iid = g
                    override: dict = {}
                elif isinstance(g, dict):
                    iid = g.get("item")
                    override = g
                else:
                    continue
                if not iid:
                    continue
                if iid not in self.items:
                    print(f"[商店配置] {shop_id} 里的 {iid} 不存在于 items.yaml，已跳过")
                    continue
                icfg = self.items[iid]
                price = override.get("price", icfg.get("price"))
                if price is None:
                    print(f"[商店配置] {shop_id} 里的 {iid} 没有价格，已跳过")
                    continue
                goods.append({
                    "item": iid,
                    "price": int(price),
                    "name": override.get("name", icfg.get("name", iid)),
                    "description": override.get("description", icfg.get("description", "")),
                })
            if not goods:
                print(f"[商店配置] {shop_id} 商品列表为空")
                return None
            return {"name": raw.get("name", shop_id), "goods": goods}

        # ── 兜底：旧行为（全量 price） ──
        goods = []
        for iid, cfg in self.items.items():
            if "price" not in cfg:
                continue
            if cfg.get("shop") is False:
                continue
            goods.append({
                "item": iid,
                "price": int(cfg["price"]),
                "name": cfg.get("name", iid),
                "description": cfg.get("description", ""),
            })
        if not goods:
            return None
        return {"name": "商店", "goods": goods}

    def open_shop(self, unit, shop_id: str | None = None) -> None:
        """打开商店。

        shop_id 来自地形字段 shop: <id> / map.yaml::shops 坐标映射 / events 的 shop 字段。
        None 表示走兜底（全量 price）。
        """
        cfg = self._shop_cfg(shop_id)
        if not cfg:
            self._pause("商店暂无商品。", cursor=(unit.x, unit.y))
            return
        shop_name = cfg["name"]
        goods = cfg["goods"]

        while True:
            render_screen(self, selected=unit,
                          message=f"{shop_name}　金钱 {self.gold}G　数字键购买　Q 离开")
            lines = [f"{shop_name}　金钱：{self.gold}G"]
            for i, g in enumerate(goods, 1):
                desc = g.get("description", "")
                tail = f"　{desc}" if desc else ""
                lines.append(f"  {i}. {g['name']}　{g['price']}G{tail}")
            _console.print("\n".join(lines))
            k = read_key()
            if k in ("esc", "quit"):
                return
            if k.isdigit() and 1 <= int(k) <= len(goods):
                g = goods[int(k) - 1]
                price = int(g["price"])
                if self.gold >= price:
                    self.gold -= price
                    unit.add_item(g["item"], self.items)
                    self._pause(f"购买了 {g['name']}！剩余金钱：{self.gold}G",
                                cursor=(unit.x, unit.y))
                else:
                    self._pause(f"金钱不足！需要 {price}G，当前 {self.gold}G",
                                cursor=(unit.x, unit.y))