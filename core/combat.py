"""战斗结算 + 面板/预测数值。

do_combat：真实战斗（带随机命中/暴击）。
unit_combat_stats：单位面板用的自身攻击/防御/命中/回避/必杀。
effective_stats：叠加状态加成后的属性（面板显示 / 技能效果计算用）。
support_bonus_detail：相邻支援对象的加成明细（UI 展示 + 公式累加）。
predict_combat：攻击某敌人前的战斗预测（命中率/伤害/必杀等）。
predict_combat_pair：攻守双方面板（含武器三角关系 + 双方支援加成明细）。

全部数值走 global.yaml 的 formulas，Python 不含硬编码伤害/射程。

状态加成：
    status.yaml 中 formula.stat_bonus 的字段在战斗求值和面板显示时叠加。

支援加成（3b）：
    相邻（曼哈顿距离 1）的同阵营支援对象，按 support_ranks 等级叠加
    global.support_bonus 中的 hit/avoid/crit。双向生效。

技能被动加成（v7）：
    skills.yaml 中 **被动技能**（type != active）的 formula.stat_bonus
    会在战斗求值时叠加，作为 skill_hit_bonus / skill_avoid_bonus /
    skill_crit_bonus / skill_attack_bonus / skill_defense_bonus
    进入 _unit_ctx，由 global.yaml 的 formulas 读取。

    来源包括：
        unit.skills            —— 升级学的 + 事件给的
        class_cfg.class_skills —— 职业授予的（注意：主动技能会被跳过）

    支持字段：hit / avoid / crit / attack / defense
    不影响 max_stats 和 mov —— 那属于"角色成长"，不是"战斗修正"。

    用法示例（skills.yaml）：
        swordmaster_mastery:
          formula: {stat_bonus: {crit: 15}}
    挂到职业（classes.yaml）：
        swordmaster:
          class_skills: [swordmaster_mastery]

    未配置任何 stat_bonus 时，所有 skill_xxx_bonus = 0，公式退化为原值。
"""
from __future__ import annotations

from random import randint

from core.formula import ev

_WEAPON_TYPE_NAMES = {"sword": "剑", "axe": "斧", "lance": "枪",
                      "bow": "弓", "staff": "杖", "fang": "爪",
                      "anima": "理魔法", "light": "光", "dark": "暗"}

_EFFECT_GROUP_NAMES = {"flying": "飞行兵", "dragon": "龙族", "armor": "装甲",
                       "beast": "魔兽", "mounted": "骑兵", "foot": "步兵"}

# 技能被动支持的属性字段（_unit_ctx 里会灌成 skill_{key}_bonus）
_SKILL_BONUS_KEYS = ("hit", "avoid", "crit", "attack", "defense")


def effect_multiplier(atk, dfn, game) -> tuple[float, str]:
    """武器特效：effective_against 命中守方职业 groups 任一类别 → (倍率, 类别名)。"""
    _iid, w = atk.weapon(game.items)
    ea = w.get("effective_against")
    if not ea:
        return 1.0, ""
    if isinstance(ea, str):
        ea = [ea]
    groups = (dfn.class_cfg or {}).get("groups") or []
    for t in ea:
        if t in groups:
            mult = (game.global_cfg.get("effectiveness") or {}).get("multiplier", 2)
            try:
                mult = float(mult)
            except (TypeError, ValueError):
                mult = 2.0
            return mult, _EFFECT_GROUP_NAMES.get(t, t)
    return 1.0, ""


def _weapon_ctx(unit, items_cfg: dict) -> dict:
    _, w = unit.weapon(items_cfg)
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0
    return {
        "ctx": {
            "weapon_might": _num(w.get("might", 0)),
            "weapon_hit": _num(w.get("hit", 0)),
            "weapon_crit": _num(w.get("crit", 0)),
        },
        "is_magic": w.get("damage_type") == "magic",
    }


def effective_stats(unit, status_cfg: dict | None = None) -> dict:
    """叠加状态加成后的属性字典。不改 unit.stats。"""
    base = dict(unit.stats)
    if not status_cfg:
        return base
    for sid in unit.status:
        bonus = (status_cfg.get(sid, {}).get("formula") or {}).get("stat_bonus") or {}
        for k, v in bonus.items():
            base[k] = base.get(k, 0) + v
    return base


def _skill_stat_bonus(unit, skills_cfg: dict | None = None) -> dict:
    """累加所有被动技能的 formula.stat_bonus。

    - 跳过 active 技能（它们是主动使用，不是被动生效）
    - 来源包含 unit.skills（学到的）和 class_cfg.class_skills（职业授予的）
    - 支持的字段：hit / avoid / crit / attack / defense
    """
    total = {k: 0 for k in _SKILL_BONUS_KEYS}
    if not skills_cfg:
        return total
    all_skills = list(unit.skills) + list((unit.class_cfg or {}).get("class_skills") or [])
    seen: set[str] = set()
    for sid in all_skills:
        if sid in seen:
            continue
        seen.add(sid)
        skill = skills_cfg.get(sid, {}) or {}
        if skill.get("type") == "active":
            continue
        f = skill.get("formula") or {}
        sb = f.get("stat_bonus") or {}
        for k, v in sb.items():
            if k in total:
                try:
                    total[k] += int(v)
                except (TypeError, ValueError):
                    pass
    return total


def _unit_ctx(unit, terrain: dict, status_cfg: dict | None = None,
              skills_cfg: dict | None = None) -> dict:
    eff = effective_stats(unit, status_cfg)
    sb = _skill_stat_bonus(unit, skills_cfg)
    return {
        "hp": unit.stats.get("hp", 0), "max_hp": unit.max_stats.get("hp", 0),
        "str": eff.get("str", 0), "def": eff.get("def", 0),
        "spd": eff.get("spd", 0), "skl": eff.get("skl", 0),
        "luk": eff.get("luk", 0), "int": eff.get("int", 0),
        "res": eff.get("res", 0), "mov": eff.get("mov", 0),
        "level": unit.level,
        "terrain_def": terrain.get("def", 0),
        "terrain_res": terrain.get("res", 0),
        "terrain_avoid": terrain.get("avoid", 0),
        # ═══ v7 新增：技能被动加成 ═══
        "skill_hit_bonus": sb["hit"],
        "skill_avoid_bonus": sb["avoid"],
        "skill_crit_bonus": sb["crit"],
        "skill_attack_bonus": sb["attack"],
        "skill_defense_bonus": sb["defense"],
    }


def _terrain(game, x: int, y: int) -> dict:
    return game.map.terrain_at(x, y) if game.map else {}


def _skill_damage_bonus(unit, game) -> float:
    """旧机制：condition + damage_bonus 追加伤害（冲锋等）。
    与新的 stat_bonus 可以共存。"""
    total = 0.0
    for sid in unit.skills:
        f = (game.skills.get(sid, {}) or {}).get("formula") or {}
        if "damage_bonus" not in f:
            continue
        cond = f.get("condition")
        if cond:
            ctx = {"moved_this_turn": unit.moved_this_turn}
            if not ev(str(cond), ctx):
                continue
        total += ev(str(f["damage_bonus"]), {"unit": unit.flags})
    return total


def _aura_hit_bonus(unit, game) -> float:
    total = 0.0
    for u in game.units:
        if not u.alive or u is unit or u.faction != unit.faction:
            continue
        for sid in u.skills:
            aura = ((game.skills.get(sid, {}) or {}).get("formula") or {}).get("aura")
            if not aura:
                continue
            radius = int(aura.get("radius", 1))
            if abs(u.x - unit.x) + abs(u.y - unit.y) <= radius:
                total += aura.get("hit_bonus", 0)
    return total


def support_bonus_detail(unit, game) -> list[dict]:
    """相邻支援对象的加成明细。"""
    details: list[dict] = []
    table = game.global_cfg.get("support_bonus") or {}
    if not table:
        return details
    for other in game.units:
        if not other.alive or other is unit:
            continue
        if other.faction != unit.faction:
            continue
        if abs(other.x - unit.x) + abs(other.y - unit.y) != 1:
            continue
        rank = unit.support_ranks.get(other.uid, 0)
        if rank <= 0:
            continue
        cfg = table.get(rank) or {}
        details.append({
            "uid": other.uid,
            "name": other.name,
            "rank": rank,
            "hit": cfg.get("hit", 0),
            "avoid": cfg.get("avoid", 0),
            "crit": cfg.get("crit", 0),
        })
    return details


def _support_bonus(unit, game) -> dict:
    total = {"hit": 0, "avoid": 0, "crit": 0}
    for d in support_bonus_detail(unit, game):
        total["hit"] += d["hit"]
        total["avoid"] += d["avoid"]
        total["crit"] += d["crit"]
    return total


def triangle_bonus(atk, dfn, game) -> tuple[int, int, str]:
    """武器三角克制（攻方视角）。"""
    _, atk_w = atk.weapon(game.items)
    _, dfn_w = dfn.weapon(game.items)
    atk_type = atk_w.get("weapon_type")
    dfn_type = dfn_w.get("weapon_type")
    if not atk_type or not dfn_type:
        return 0, 0, ""
    tri = game.global_cfg.get("weapon_triangle") or {}
    formulas = game.global_cfg.get("formulas", {})
    hit_b = int(ev(str(formulas.get("weapon_triangle_hit", "0")), {}))
    dmg_b = int(ev(str(formulas.get("weapon_triangle_damage", "0")), {}))
    if tri.get(atk_type) == dfn_type:
        return hit_b, dmg_b, "advantage"
    if tri.get(dfn_type) == atk_type:
        return -hit_b, -dmg_b, "disadvantage"
    return 0, 0, "neutral"


def unit_combat_stats(unit, game) -> dict:
    """单位面板用：自身攻击/防御/命中/回避/必杀（不含敌方回避）。

    命中/回避/必杀 已叠加相邻支援加成（双向生效）。
    额外返回 support 字段（{hit, avoid, crit}），供 UI 显示成 "命中 40(+5)"。
    技能被动加成已通过 _unit_ctx 进入公式，直接体现在数值上。
    """
    formulas = game.global_cfg.get("formulas", {})
    w = _weapon_ctx(unit, game.items)
    ctx = {
        **_unit_ctx(unit, _terrain(game, unit.x, unit.y), game.status, game.skills),
        **w["ctx"],
    }
    sup = _support_bonus(unit, game)
    if w["is_magic"]:
        attack = ev(formulas.get("magic_attack", "0"), ctx)
        defense = ev(formulas.get("magic_defense", "0"), ctx)
    else:
        attack = ev(formulas.get("attack", "0"), ctx)
        defense = ev(formulas.get("defense", "0"), ctx)
    return {
        "attack": attack,
        "defense": defense,
        "hit": ev(formulas.get("hit_rate", "0"), {**ctx, "enemy_avoid": 0}) + sup["hit"],
        "avoid": ev(formulas.get("avoid", "0"), ctx) + sup["avoid"],
        "crit": ev(formulas.get("crit_rate", "0"), ctx) + sup["crit"],
        "support": sup,
    }


def predict_combat(atk, dfn, game) -> dict:
    """攻击前的战斗预测。"""
    formulas = game.global_cfg.get("formulas", {})
    atk_w = _weapon_ctx(atk, game.items)
    dfn_w = _weapon_ctx(dfn, game.items)
    atk_ctx = {
        **_unit_ctx(atk, _terrain(game, atk.x, atk.y), game.status, game.skills),
        **atk_w["ctx"],
    }
    dfn_ctx = {
        **_unit_ctx(dfn, _terrain(game, dfn.x, dfn.y), game.status, game.skills),
        **dfn_w["ctx"],
    }

    atk_sup_detail = support_bonus_detail(atk, game)
    dfn_sup_detail = support_bonus_detail(dfn, game)
    atk_sup = _sum_support(atk_sup_detail)
    dfn_sup = _sum_support(dfn_sup_detail)

    avoid = ev(formulas.get("avoid", "0"), dfn_ctx) + dfn_sup["avoid"]
    hit = ev(formulas.get("hit_rate", "0"), {**atk_ctx, "enemy_avoid": avoid})
    hit += _aura_hit_bonus(atk, game)
    tri_hit, tri_dmg, _relation = triangle_bonus(atk, dfn, game)
    hit += tri_hit
    hit += atk_sup["hit"]

    crit = ev(formulas.get("crit_rate", "0"), atk_ctx) + atk_sup["crit"]

    if atk_w["is_magic"]:
        attack = ev(formulas.get("magic_attack", "0"), atk_ctx)
        defense = ev(formulas.get("magic_defense", "0"), dfn_ctx)
    else:
        attack = ev(formulas.get("attack", "0"), atk_ctx)
        defense = ev(formulas.get("defense", "0"), dfn_ctx)
    damage = ev(formulas.get("damage", "0"), {"attack": attack, "defense": defense})
    damage += _skill_damage_bonus(atk, game)
    damage += tri_dmg
    damage = max(0, damage)
    _em, _ = effect_multiplier(atk, dfn, game)
    if _em > 1.0:
        damage = int(damage * _em)
    return {
        "attack": attack, "defense": defense, "avoid": avoid,
        "hit_rate": hit, "crit_rate": crit, "damage": int(damage),
        "support_bonus_details": atk_sup_detail,
        "support_bonus_totals": atk_sup,
    }


def _sum_support(details: list[dict]) -> dict:
    total = {"hit": 0, "avoid": 0, "crit": 0}
    for d in details:
        total["hit"] += d.get("hit", 0)
        total["avoid"] += d.get("avoid", 0)
        total["crit"] += d.get("crit", 0)
    return total


def predict_combat_pair(
    atk, dfn, game,
    can_counter: bool,
    atk_doubles: bool,
    dfn_doubles: bool,
) -> dict:
    """攻守双方预测（含双方支援加成明细，供 UI 展示）。"""
    atk_side = predict_combat(atk, dfn, game)
    dfn_side = predict_combat(dfn, atk, game) if can_counter else None

    tri_hit, tri_dmg, relation = triangle_bonus(atk, dfn, game)
    note = ""
    if relation in ("advantage", "disadvantage"):
        _, atk_w = atk.weapon(game.items)
        _, dfn_w = dfn.weapon(game.items)
        at_name = _WEAPON_TYPE_NAMES.get(atk_w.get("weapon_type", ""), "")
        df_name = _WEAPON_TYPE_NAMES.get(dfn_w.get("weapon_type", ""), "")
        if relation == "advantage":
            note = f"{at_name}克{df_name}：{atk.name} 命中+{tri_hit} 伤害+{tri_dmg}"
        else:
            note = f"{df_name}克{at_name}：{atk.name} 命中{tri_hit} 伤害{tri_dmg}"
    _em, _el = effect_multiplier(atk, dfn, game)
    if _el and _em > 1.0:
        eff_note = f"特效({_el} ×{int(_em)})"
        note = (note + "　" + eff_note) if note else eff_note

    return {
        "atk_side": atk_side,
        "dfn_side": dfn_side,
        "triangle_relation": relation,
        "triangle_note": note,
        "can_counter": can_counter,
        "atk_doubles": atk_doubles,
        "dfn_doubles": dfn_doubles,
        "atk_support_details": atk_side.get("support_bonus_details", []),
        "dfn_support_details": (dfn_side or {}).get("support_bonus_details", []),
    }


def do_combat(atk, dfn, game) -> dict:
    """攻守双方结算一次攻击（不含反击，不含经验结算）。"""
    formulas = game.global_cfg.get("formulas", {})
    atk_w = _weapon_ctx(atk, game.items)
    dfn_w = _weapon_ctx(dfn, game.items)
    t_atk = _terrain(game, atk.x, atk.y)
    t_dfn = _terrain(game, dfn.x, dfn.y)

    atk_ctx = {
        **_unit_ctx(atk, t_atk, game.status, game.skills),
        **atk_w["ctx"],
    }
    dfn_ctx = {
        **_unit_ctx(dfn, t_dfn, game.status, game.skills),
        **dfn_w["ctx"],
    }

    atk_sup = _support_bonus(atk, game)
    dfn_sup = _support_bonus(dfn, game)

    enemy_avoid = ev(formulas.get("avoid", "0"), dfn_ctx) + dfn_sup["avoid"]
    hit_rate = ev(formulas.get("hit_rate", "0"), {**atk_ctx, "enemy_avoid": enemy_avoid})
    hit_rate += _aura_hit_bonus(atk, game)
    tri_hit, tri_dmg, _relation = triangle_bonus(atk, dfn, game)
    hit_rate += tri_hit
    hit_rate += atk_sup["hit"]

    result: dict = {
        "hit": False, "damage": 0, "crit": False, "dead": False,
        "hit_rate": hit_rate, "crit_rate": 0, "attacker": atk.name, "defender": dfn.name,
    }
    if randint(1, 100) > hit_rate:
        return result
    result["hit"] = True

    if atk_w["is_magic"]:
        attack = ev(formulas.get("magic_attack", "0"), atk_ctx)
        defense = ev(formulas.get("magic_defense", "0"), dfn_ctx)
    else:
        attack = ev(formulas.get("attack", "0"), atk_ctx)
        defense = ev(formulas.get("defense", "0"), dfn_ctx)
    damage = ev(formulas.get("damage", "0"), {"attack": attack, "defense": defense})
    damage += _skill_damage_bonus(atk, game)
    damage += tri_dmg
    damage = max(0, damage)
    _em, _ = effect_multiplier(atk, dfn, game)
    if _em > 1.0:
        damage = int(damage * _em)
    result["damage"] = int(damage)

    crit_rate = ev(formulas.get("crit_rate", "0"), atk_ctx) + atk_sup["crit"]
    result["crit_rate"] = crit_rate
    if randint(1, 100) <= crit_rate:
        result["crit"] = True
        result["damage"] = int(damage * 3)

    dfn.stats["hp"] = dfn.stats.get("hp", 0) - result["damage"]
    if dfn.stats["hp"] <= 0:
        dfn.stats["hp"] = 0
        dfn.alive = False
        result["dead"] = True
    return result