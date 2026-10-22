"""BattleMixin：战斗结算。

一次交战的完整链路：战前对话 → 普攻 → 反击 → 追击×N → 战利品 → 战后对话 → 好感度 → 经验。
不包含"选目标"和"换武器"这些玩家操作，它们在 ActionMixin。

v7.4：
    经验在 _resolve_battle 内部逐次 strike 结算。
    - 命中未杀：exp_hit × 等级差惩罚
    - 未命中：exp_miss（不乘惩罚）
    - 击杀：exp_kill × 等级差惩罚
    杖/舞蹈/偷窃的经验由 ActionMixin 调用 _grant_exp 结算。

v7.4b：
    经验公式改用 total_level（总等级），区分上/下位职业。
    - 下位职业：total_level = level
    - 上位职业：total_level = max_level + level
    - 特殊职业（dancer/beast 等 promoted: false）：total_level = level
    这样下位 20 打上位 1 仍有经验（20 vs 21），上位 20 打下位 1 为 0（40 vs 1）。
"""
from __future__ import annotations

from core.combat import do_combat, predict_combat
from core.formula import ev, _DotDict
from core.ui import STAT_NAMES, _console, play_battle_animation
from core.unit import _init_uses


class BattleMixin:
    def _can_double(self, a, b) -> bool:
        cond = (self.global_cfg.get("formulas") or {}).get("double_attack_condition")
        if not cond:
            return False
        return bool(ev(str(cond), {
            "self_spd": a.stats.get("spd", 0),
            "enemy_spd": b.stats.get("spd", 0),
        }))

    def _can_counter(self, dfn, atk) -> bool:
        if not dfn.ai_params.get("can_counter", True):
            return False
        lo, hi = dfn.weapon_range_span(self.items)
        if hi <= 0:
            return False
        return lo <= abs(dfn.x - atk.x) + abs(dfn.y - atk.y) <= hi

    def _battle_talk_ctx(self, atk, dfn) -> dict:
        ctx: dict = {
            "turn": self.turn, "gold": self.gold,
            "vars": _DotDict(self.vars),
            **{f"var_{k}": v for k, v in self.vars.items()},
        }
        for side, u in (("atk", atk), ("dfn", dfn)):
            ctx[f"{side}_uid"] = u.uid
            ctx[f"{side}_hp"] = u.stats.get("hp", 0)
            ctx[f"{side}_max_hp"] = u.max_stats.get("hp", 0)
            ctx[f"{side}_level"] = u.level
            for stat in ("str", "spd", "skl", "luk", "def", "res", "int"):
                ctx[f"{side}_{stat}"] = u.stats.get(stat, 0)
        return ctx

    def _check_battle_talk(self, atk, dfn, timing: str) -> bool:
        talks = self.stories.get("talks") or {}
        if not talks:
            return False
        pair = {atk.uid, dfn.uid}
        played = False
        for talk_id, cfg in talks.items():
            if not isinstance(cfg, dict):
                continue
            units = list(cfg.get("units") or [])
            if len(units) != 2 or set(units) != pair:
                continue
            if str(cfg.get("timing", "pre")) != timing:
                continue
            once = bool(cfg.get("once", True))
            if once and talk_id in self._fired_talks:
                continue
            cond = str(cfg.get("condition", "") or "")
            if cond and not ev(cond, self._battle_talk_ctx(atk, dfn)):
                continue
            self._fired_talks.add(talk_id)
            played = True
            from core.event import _run_dialogue_list, run_action
            _console.print(
                f"[magenta]—— 战斗对话：{cfg.get('name', talk_id)} ——[/magenta]"
            )
            _run_dialogue_list(list(cfg.get("dialogue") or []), self)
            for act in (cfg.get("actions") or []):
                run_action(act, self)
            self._log_battle(f"战斗对话：{cfg.get('name', talk_id)}")
            break
        return played

    def _record_battle_result(self, result: dict) -> None:
        gs = self.global_vars["global_stats"]
        if result.get("hit"):
            dmg = result.get("damage", 0)
            if dmg > self.stats.get("max_damage", 0):
                self.stats["max_damage"] = dmg
            if dmg > gs.get("total_max_damage", 0):
                gs["total_max_damage"] = dmg
            if result.get("crit"):
                self.stats["crits"] += 1
                gs["total_crits"] += 1
        else:
            self.stats["misses"] += 1
            gs["total_misses"] += 1

    def _settle_gold_drop(self, atk, dfn) -> list[str]:
        """结算击杀掉落。

        v7.4c 支持三种掉落：
        - drop_gold:  金币（100% 必掉）
        - drop_item:  单个物品 id（100% 必掉，旧字段）
        - drop_items: 列表 [{id, chance, uses}]，chance 0-100，不写=100
        全部进仓库（warehouse）。
        """
        from random import randint
        out: list[str] = []
        gs = self.global_vars["global_stats"]

        for killer, victim in ((atk, dfn), (dfn, atk)):
            if not (not victim.alive
                    and victim.faction == "enemy"
                    and killer.faction in ("player", "ally")):
                continue

            self.stats["kills"] += 1
            gs["total_kills"] += 1

            # ── 金币（旧字段，100%）──
            if getattr(victim, "drop_gold", 0) > 0:
                self.gold += victim.drop_gold
                self.stats["gold_earned"] += victim.drop_gold
                gs["total_gold_earned"] += victim.drop_gold
                out.append(f"击败 {victim.name}，获得 {victim.drop_gold}G！")
                victim.drop_gold = 0

            # ── 单物品（旧字段，100%）──
            di = getattr(victim, "drop_item", "")
            if di and di in self.items:
                self.warehouse.append({
                    "id": di,
                    "uses": _init_uses(self.items.get(di, {})),
                })
                victim.drop_item = ""
                out.append(f"缴获战利品：{self.items[di].get('name', di)}（已入仓库）")

            # ── 多物品 + 几率（新字段）──
            drops = list(getattr(victim, "drop_items", []) or [])
            for drop in drops:
                if not isinstance(drop, dict):
                    continue
                iid = drop.get("id")
                if not iid or iid not in self.items:
                    continue
                chance = int(drop.get("chance", 100))
                chance = max(0, min(100, chance))
                if chance < 100 and randint(1, 100) > chance:
                    continue
                uses = drop.get("uses", _init_uses(self.items.get(iid, {})))
                self.warehouse.append({"id": iid, "uses": uses})
                out.append(f"缴获战利品：{self.items[iid].get('name', iid)}（已入仓库）")
            # 清空，防止重复掉落（如果单位被复活再杀）
            victim.drop_items = []

        return out
    # ---------------- 经验（v7.4 / v7.4b） ----------------

    def _total_level(self, unit) -> int:
        """总等级 = 层级偏移 + 当前等级。

        层级偏移：
        - 上位职业：offset = 全局 max_level（默认 20）→ total = 20 + level
        - 下位 / 特殊职业：offset = 0 → total = level

        判定优先级：
        1. class_cfg.force_base == true      → 强制下位（推荐，语义明确）
        2. class_cfg 显式配了 promoted       → 按 promoted 布尔值（旧字段兼容）
        3. 其他                              → 自动判断：
           - unit.has_promoted（转过职）→ 上位
           - 无 promote 段、无 special → 上位
           - 有 promote 段 / special → 下位
        """
        formulas = self.global_cfg.get("formulas", {})
        base = int(ev(str(formulas.get("max_level", "20")), {}))
        cc = unit.class_cfg or {}

        # 优先级 1：force_base 强制下位
        if cc.get("force_base"):
            promoted = False
        # 优先级 2：旧的 promoted 字段显式配了，按它（兼容）
        elif "promoted" in cc:
            promoted = bool(cc["promoted"])
        # 优先级 3：自动判断
        else:
            promoted = (
                unit.has_promoted
                or (
                    not cc.get("promote")
                    and not cc.get("special")
                )
            )

        offset = base if promoted else 0
        return offset + unit.level
    def _calc_combat_exp(self, attacker, defender, result: dict) -> int:
        """单次 strike 的经验（只对玩家攻击敌人有效）。

        v7.4b：ctx 里同时提供裸 level 和 total_level，公式默认用 total_level。
        - 击杀：exp_kill × penalty
        - 命中未杀：exp_hit × penalty
        - 未命中：exp_miss（不乘 penalty）
        最低 0。
        """
        if attacker.faction != "player" or defender.faction != "enemy":
            return 0
        formulas = self.global_cfg.get("formulas", {})
        ctx = {
            # 裸等级（兼容旧公式）
            "self_level": attacker.level,
            "enemy_level": defender.level,
            # 总等级（v7.4b 新增，推荐用这个）
            "self_total_level": self._total_level(attacker),
            "enemy_total_level": self._total_level(defender),
        }
        if not result.get("hit"):
            base = float(ev(str(formulas.get("exp_miss", "1")), ctx))
            return max(0, int(base))
        if result.get("dead"):
            base = float(ev(str(formulas.get("exp_kill", "30")), ctx))
        else:
            base = float(ev(str(formulas.get("exp_hit", "10")), ctx))
        penalty = float(ev(str(formulas.get("exp_level_penalty", "1.0")), ctx))
        return max(0, int(base * penalty))

    def _grant_exp(self, unit, lines: list[str], amount: int) -> None:
        """给单位加经验并写入 lines（含升级信息）。amount <= 0 时静默跳过。"""
        if amount <= 0 or not unit.alive:
            return
        lines.append(f"{unit.name} 获得 {amount} 点经验。")
        ups = unit.gain_exp(amount, self.global_cfg)
        for r in ups:
            lines.append(f"升级到 Lv {r['level']}！")
            gains = r.get("gains", {})
            if gains:
                lines.append("　".join(
                    f"{STAT_NAMES.get(k, k)}+{v}" for k, v in gains.items() if v
                ))
            gb = r.get("guarantee_bonus")
            if gb:
                lines.append(f"（成长保底）{STAT_NAMES.get(gb[0], gb[0])}+{gb[1]}")
            if r.get("new_skills"):
                lines.append(f"习得技能：{'、'.join(r['new_skills'])}")

    # ---------------- 战斗主流程 ----------------

    def _resolve_battle(self, atk, dfn) -> list[str]:
        """一次交战：战前对话 → 普攻 → 反击 → 追击 → 战利品 → 战后对话 → 好感度 → 经验。"""
        lines: list[str] = []
        self._check_battle_talk(atk, dfn, "pre")
        total_exp = 0

        def strike(src, dst, label: str = "") -> None:
            nonlocal total_exp
            if label:
                lines.append(label)
            pred = predict_combat(src, dst, self)
            play_battle_animation(src, dst, pred)
            result = do_combat(src, dst, self)
            self._record_battle_result(result)
            lines.append(self._battle_lines(src, dst, result))
            total_exp += self._calc_combat_exp(src, dst, result)
            broken = src.consume_weapon_uses(self.items)
            if broken:
                name = self.items.get(broken, {}).get("name", broken)
                lines.append(f"{src.name} 的{name}已损坏！")

        strike(atk, dfn)
        if dfn.alive and self._can_counter(dfn, atk):
            strike(dfn, atk, f"{dfn.name} 反击！")
        if atk.alive and dfn.alive and self._can_double(atk, dfn):
            strike(atk, dfn, f"{atk.name} 速度优势，再次攻击！")
        if atk.alive and dfn.alive and self._can_double(dfn, atk):
            strike(dfn, atk, f"{dfn.name} 速度优势，再次反击！")
        lines.extend(self._settle_gold_drop(atk, dfn))
        self._check_battle_talk(atk, dfn, "post")
        self._gain_support_points_from_battle(atk, dfn)

        # 经验结算（只给玩家攻击者）
        if total_exp > 0 and atk.alive and atk.faction == "player":
            self._grant_exp(atk, lines, total_exp)

        return lines

    def _battle_lines(self, atk, dfn, result: dict) -> str:
        if not result.get("hit"):
            return f"{atk.name} 的攻击落空了！"
        line = f"{atk.name} 命中 {dfn.name}，造成 {result.get('damage', 0)} 点伤害！"
        if result.get("crit"):
            line += "（暴击 ×3）"
        if result.get("dead"):
            line += f"　{dfn.name} 被击败了！"
        else:
            mx = dfn.max_stats.get("hp", 0)
            line += f"　{dfn.name} 剩余 HP {dfn.stats['hp']}/{mx}"
        return line