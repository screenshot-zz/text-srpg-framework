"""中文字段映射。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

FIELD_ZH: dict[str, str] = {
    "name": "名称", "description": "说明",
    "type": "类型", "level": "等级", "exp": "经验",
    "weapon_type": "武器类型",
    "might": "威力", "hit": "命中", "crit": "必杀",
    "range": "射程", "durability": "耐久", "price": "价格",
    "damage_type": "伤害类型", "no_attack": "不可攻击",
    "effective_against": "特效目标",
    "formula": "效果公式", "special": "特殊效果",
    "target": "目标阵营", "condition": "使用条件", "story": "触发剧情",
    "consume": "消耗", "uses": "次数", "unit_id": "召唤单位",
    "actions": "动作",
    "duration": "持续回合", "aoe_radius": "范围半径",
    "stat_bonus": "属性加成", "turn_damage": "每回合伤害",
    "skip_action": "无法行动",
    "damage_bonus": "追加伤害", "aura": "光环",
    "radius": "光环半径", "hit_bonus": "命中加成",
    "hp": "HP", "str": "力量", "def": "守备", "spd": "速度",
    "skl": "技巧", "luk": "幸运", "int": "魔力", "res": "抗性",
    "mov": "移动",
    "attack": "攻击", "defense": "防御", "avoid": "回避",
    "move_type": "移动类型", "groups": "职业类别",
    "stats": "职业加成", "growth": "成长率",
    "weapon_types": "可用武器", "skill_learn": "升级习得",
    "class_skills": "职业授予", "promote": "转职",
    "to": "转职到", "item": "需要道具",
    "deployable": "可出战", "start_deployed": "初始出战",
    "is_lord": "主角", "skills": "技能", "items": "道具",
    "short": "地图字符", "class": "职业",
    "drop_gold": "掉落金币 (100%)", "drop_item": "掉落道具 (100%)", "drop_items": "多物品掉落",
    "flags": "标记", "ai": "AI",
    "heal": "治疗量", "damage": "伤害量",
    "cure_status": "解除状态", "apply_status": "附加状态",
    "force_base": "强制下位职业",
    "max_level": "强制最高等级",
}

VIRTUAL_FIELD_ZH: dict[str, str] = {
    # skills_editor
    "__enable_damage": "启用追加伤害",
    "__enable_aura": "启用光环",
    "__enable_stat_bonus": "启用属性加成",
    "__damage_bonus_expr": "追加伤害表达式",
    "__damage_condition_expr": "触发条件表达式",
    "__aura": "光环加成内容",
    "__stat_attack": "攻击加成",
    "__stat_defense": "防御加成",
    "__stat_hit": "命中加成",
    "__stat_avoid": "回避加成",
    "__stat_crit": "必杀加成",
    "__special_type": "主动类型",
    "__effect_heal": "启用治疗",
    "__effect_damage": "启用伤害",
    "__heal_expr": "治疗表达式",
    "__damage_expr": "伤害表达式",
    # items_editor
    "__effect_type": "杖效果类型",
    # classes_editor
    "__enable_force_base": "强制下位职业（勾选后不可转职）",
    "__enable_max_level": "强制最高等级",
    "__promote_disabled": "转职",
}

VALUE_ZH: dict[str, str] = {
    "weapon": "武器", "consumable": "消耗品", "key": "钥匙",
    "passive": "被动", "active": "主动",
    "sword": "剑", "axe": "斧", "lance": "枪", "bow": "弓",
    "staff": "杖", "fang": "爪",
    "anima": "理魔法", "light": "光魔法", "dark": "暗魔法",
    "foot": "步兵", "mounted": "骑兵", "flying": "飞行",
    "magic": "魔法", "physical": "物理",
    "self": "自己", "ally": "友军", "enemy": "敌人", "player": "我军",
    "aggressive": "主动进攻", "guard": "驻守", "sentinel": "哨兵",
    "follow": "跟随", "move_to": "前往", "flee_to": "撤退",
    "repair": "修复", "revive": "复活", "summon": "召唤",
    "teleport": "传送", "script": "脚本",
    "steal": "偷窃", "dance": "舞蹈",
    "armor": "装甲", "beast": "魔兽", "dragon": "龙族",
    "lord": "领主",
}

_LOG_PATH: Path | None = None
_SEEN: set[str] = set()

def set_log_path(path: str | Path) -> None:
    global _LOG_PATH
    _LOG_PATH = Path(path)
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        _LOG_PATH = None

def _log_unmapped(tag: str) -> None:
    if tag in _SEEN:
        return
    _SEEN.add(tag)
    if _LOG_PATH is None:
        return
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {tag}\n")
    except OSError:
        pass

def field_zh(key: str) -> str:
    if key.startswith("__"):
        zh = VIRTUAL_FIELD_ZH.get(key)
        if zh:
            return zh
        _log_unmapped(f"virtual_field:{key}")
        return key
    zh = FIELD_ZH.get(key)
    if zh is None:
        _log_unmapped(f"field:{key}")
        return key
    return zh

def value_zh(value: Any) -> str:
    if isinstance(value, str):
        return VALUE_ZH.get(value, value)
    return str(value)

def register_field(key: str, label: str) -> None:
    FIELD_ZH[key] = label

def register_value(value: str, label: str) -> None:
    VALUE_ZH[value] = label