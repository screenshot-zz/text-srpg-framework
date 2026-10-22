"""单位数据模型：属性三段、成长率、升级、转职、支援等级、道具耐久。

道具结构（P1-1）：
    items: list[dict]  —— 每项 {"id": str, "uses": int | None}
    uses = None 表示无限（无限耐久武器 / 无限使用消耗品）
    uses > 0   表示剩余次数，归零后自动从 items 移除

初始化规则（_init_uses）：
    - 配置显式 uses → 用该值（None 表示无限）
    - 武器有 durability → durability
    - 消耗品 consume=true（默认）→ 1
    - 消耗品 consume=false → None
    - 其余 → None

攻击扣耐久（consume_weapon_uses）：
    每次攻击扣当前武器 1 点；归零移除并返回 id 供 UI 提示「XX已损坏」
"""
from __future__ import annotations

from dataclasses import dataclass, field
from random import randint

from core.formula import ev

AI_OVERRIDE_KEYS = (
    # 旧字段（flee_to 用）
    "retreat_to", "retreat_story", "retreat_reached",
    # 通用
    "can_move", "can_attack", "can_counter", "move_mode",
    # v7 新参数
    "move_to", "reached_action", "reached_story",
    "follow_target", "follow_distance",
    "aggro_range",
)


def _init_uses(cfg: dict) -> int | None:
    """从配置推断道具初始 uses。"""
    if not cfg:
        return None
    if "uses" in cfg:
        return cfg["uses"]  # 可以是 None
    t = cfg.get("type")
    if t == "weapon":
        return cfg.get("durability")  # None 表示无限
    if t == "consumable":
        return 1 if cfg.get("consume", True) else None
    return None


@dataclass
class Unit:
    name: str
    short: str
    faction: str
    level: int
    exp: int = 0
    # ---- 属性三段 ----
    base_stats: dict = field(default_factory=dict)
    class_stats: dict = field(default_factory=dict)
    level_gains: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    max_stats: dict = field(default_factory=dict)
    # ---- 职业与成长 ----
    growth: dict = field(default_factory=dict)
    class_cfg: dict | None = None
    class_id: str = ""
    base_growth: dict = field(default_factory=dict)
    class_growth: dict = field(default_factory=dict)
    # 外部加成（P2-13 难度）：只加在敌方身上，招募为我军时清空
    stat_bonus: dict = field(default_factory=dict)
    move_type: str = "foot"
    skills: list = field(default_factory=list)
    # items: list[{"id": str, "uses": int | None}]
    items: list = field(default_factory=list)
    status: list = field(default_factory=list)
    x: int = 0
    y: int = 0
    alive: bool = True
    acted: bool = False
    moved_this_turn: bool = False
    description: str = ""
    flags: dict = field(default_factory=dict)
    uid: str = ""
    status_turns: dict = field(default_factory=dict)
    ai: str = "aggressive"
    ai_params: dict = field(default_factory=dict)
    retreat_done: bool = False
    deployable: bool = False
    deployed: bool = False
    is_lord: bool = False
    drop_gold: int = 0
    drop_item: str = ""
    drop_items: list = field(default_factory=list)   # [{id, chance}]
    _lv_since_guarantee: int = 0
    _gain_since_guarantee: int = 0
    has_promoted: bool = False
    support_ranks: dict = field(default_factory=dict)
    # ═══ 新增：好感度点数 {对方uid: 累计点数}，双向同步 ═══
    support_points: dict = field(default_factory=dict)
    # 武器系统重做：当前装备的攻击武器 iid（None=自动取第一把可用武器）
    equipped: str | None = None

    # ---------------- 派生属性 ----------------

    def _recompute_stats(self) -> None:
        keys = (set(self.base_stats) | set(self.class_stats)
                | set(self.level_gains) | set(self.stat_bonus))
        keys.add("hp")
        cur_hp = self.stats.get("hp", 0)
        new_max: dict = {}
        for k in keys:
            new_max[k] = (
                self.base_stats.get(k, 0)
                + self.class_stats.get(k, 0)
                + self.level_gains.get(k, 0)
                + self.stat_bonus.get(k, 0)
            )
        self.max_stats = new_max
        new_cur: dict = {}
        for k in keys:
            if k == "hp":
                new_cur["hp"] = min(
                    cur_hp if cur_hp > 0 else new_max["hp"], new_max["hp"]
                )
            else:
                new_cur[k] = new_max[k]
        self.stats = new_cur

    # ---------------- 构造 ----------------

    @classmethod
    def from_cfg(
        cls,
        uid: str,
        cfg: dict,
        classes: dict,
        faction: str,
        x: int,
        y: int,
        ai_profiles: dict | None = None,
        items_cfg: dict | None = None,
    ) -> "Unit":
        class_cfg = classes.get(cfg.get("class"))
        move_type = (class_cfg or {}).get("move_type", "foot")
        base_growth = dict(cfg.get("growth", {}))
        class_growth = dict((class_cfg or {}).get("growth", {}))
        total_growth = {
            k: base_growth.get(k, 0) + class_growth.get(k, 0)
            for k in set(base_growth) | set(class_growth)
        }
        base_stats = dict(cfg["stats"])
        class_stats = dict((class_cfg or {}).get("stats", {}))
        # 人物级转职分支：units.yaml 里写 promote 覆盖职业默认线（如莉娜）
        # 合并语义：人物的 to/level 优先；item 等未写字段沿用职业默认，
        # 避免覆盖时意外丢掉转职道具要求。
        if cfg.get("promote") and isinstance(cfg["promote"], dict):
            class_cfg = dict(class_cfg or {})
            merged = dict(class_cfg.get("promote") or {})
            merged.update(cfg["promote"])
            class_cfg["promote"] = merged
        combined: dict = {}
        for k in set(base_stats) | set(class_stats):
            combined[k] = base_stats.get(k, 0) + class_stats.get(k, 0)

        ai_name = cfg.get("ai", "aggressive")
        profile = dict((ai_profiles or {}).get(ai_name, {}))
        profile.pop("name", None)
        for k in AI_OVERRIDE_KEYS:
            if k in cfg:
                profile[k] = cfg[k]

        # ---- items 初始化：str → {"id", "uses"} ----
        raw_items = cfg.get("items", []) or []
        items: list[dict] = []
        for it in raw_items:
            if isinstance(it, dict):
                iid = it.get("id", "")
                if "uses" in it:
                    uses = it["uses"]
                else:
                    uses = _init_uses((items_cfg or {}).get(iid, {}))
            else:
                iid = str(it)
                uses = _init_uses((items_cfg or {}).get(iid, {}))
            items.append({"id": iid, "uses": uses})

        return cls(
            name=cfg["name"],
            short=cfg.get("short", cfg["name"][:1]),
            faction=faction,
            level=int(cfg.get("level", 1)),
            exp=int(cfg.get("exp", 0)),
            class_id=str(cfg.get("class", "")),
            base_stats=base_stats,
            class_stats=class_stats,
            level_gains={},
            stats=dict(combined),
            max_stats=dict(combined),
            growth=total_growth,
            class_cfg=class_cfg,
            base_growth=base_growth,
            class_growth=class_growth,
            move_type=move_type,
            skills=list(cfg.get("skills", [])),
            items=items,
            x=int(x),
            y=int(y),
            description=cfg.get("description", ""),
            flags=dict(cfg.get("flags", {})),
            uid=uid,
            ai=ai_name,
            ai_params=profile,
            deployable=bool(cfg.get("deployable", False)),
            deployed=bool(cfg.get("start_deployed", cfg.get("deployable", False))),
            is_lord=bool(cfg.get("is_lord", False)),
            drop_gold=int(cfg.get("drop_gold", 0)),
            drop_item=str(cfg.get("drop_item", "")),
            drop_items=list(cfg.get("drop_items") or []),
        )

    # ---------------- 武器（重做版） ----------------
    # 规则：
    #   - 一个单位可带多把武器；攻击用 equipped（不匹配距离时自动换）
    #   - 职业 weapon_types 决定能用哪些 weapon_type（资格校验）
    #   - range 数字 n → (n,n)；"a-b" → 最小a最大b。弓 range: 2 = 只打2格，
    #     贴脸打不了也反不了（FE 经典）
    #   - no_attack: true 的武器（杖）永远不进攻击池，走「杖」菜单

    def _can_wield(self, cfg: dict) -> bool:
        wt = cfg.get("weapon_type")
        if not wt:
            return True
        wts = (self.class_cfg or {}).get("weapon_types")
        if wts is None:
            return True
        return wt in wts

    @staticmethod
    def range_span(rng) -> tuple[int, int]:
        if rng is None:
            return (0, 0)
        if isinstance(rng, (int, float)):
            n = int(rng)
            return (n, n)
        s = str(rng).replace("～", "-").replace("~", "-")
        parts = [p for p in s.split("-") if p.strip() != ""]
        if len(parts) == 1:
            try:
                n = int(parts[0])
            except ValueError:
                return (0, 0)
            return (n, n)
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            return (0, 0)

    def usable_weapons(self, items_cfg: dict) -> list[tuple[str, dict]]:
        """可用来攻击的武器：type=weapon、非 no_attack、职业能用。"""
        out: list[tuple[str, dict]] = []
        for it in self.items:
            iid = it["id"] if isinstance(it, dict) else it
            cfg = (items_cfg or {}).get(iid, {})
            if cfg.get("type") != "weapon" or cfg.get("no_attack"):
                continue
            if not self._can_wield(cfg):
                continue
            out.append((iid, cfg))
        return out

    def usable_staves(self, items_cfg: dict) -> list[tuple[str, dict]]:
        """可用的杖（weapon_type=staff 且职业能用）。"""
        out: list[tuple[str, dict]] = []
        for it in self.items:
            iid = it["id"] if isinstance(it, dict) else it
            cfg = (items_cfg or {}).get(iid, {})
            if cfg.get("type") != "weapon" or cfg.get("weapon_type") != "staff":
                continue
            if not self._can_wield(cfg):
                continue
            out.append((iid, cfg))
        return out

    def weapon(self, items_cfg: dict) -> tuple[str | None, dict]:
        """当前武器：equipped 有效则用它，否则第一把可用武器。"""
        weps = self.usable_weapons(items_cfg)
        if not weps:
            return None, {}
        for iid, cfg in weps:
            if iid == self.equipped:
                return iid, cfg
        return weps[0]

    def weapon_range_span(self, items_cfg: dict) -> tuple[int, int]:
        iid, w = self.weapon(items_cfg)
        if not w:
            return (0, 0)
        return self.range_span(w.get("range"))

    def weapon_range(self, items_cfg: dict) -> int:
        """当前武器最大射程（兼容旧调用点）。"""
        return self.weapon_range_span(items_cfg)[1]

    def max_attack_range(self, items_cfg: dict) -> int:
        """所有可用武器里的最大射程（AI 走位/危险范围用）。"""
        hi = 0
        for _iid, cfg in self.usable_weapons(items_cfg):
            hi = max(hi, self.range_span(cfg.get("range"))[1])
        return hi

    def can_attack_at(self, items_cfg: dict, dist: int) -> bool:
        """是否存在可覆盖该距离的可用武器。"""
        for _iid, cfg in self.usable_weapons(items_cfg):
            lo, hi = self.range_span(cfg.get("range"))
            if lo <= dist <= hi:
                return True
        return False

    def auto_equip_for(self, items_cfg: dict, dist: int) -> str | None:
        """按目标距离换武器：当前装备覆盖则保留，否则换第一把覆盖的。"""
        weps = self.usable_weapons(items_cfg)
        if not weps:
            self.equipped = None
            return None
        valid_ids = [w[0] for w in weps]
        if self.equipped in valid_ids:
            for iid, cfg in weps:
                if iid == self.equipped:
                    lo, hi = self.range_span(cfg.get("range"))
                    if lo <= dist <= hi:
                        return self.equipped
                    break
        for iid, cfg in weps:
            lo, hi = self.range_span(cfg.get("range"))
            if lo <= dist <= hi:
                self.equipped = iid
                return iid
        if self.equipped in valid_ids:
            return self.equipped
        self.equipped = weps[0][0]
        return self.equipped

    # ---------------- 道具操作 ----------------

    def items_ids(self) -> list[str]:
        return [it["id"] if isinstance(it, dict) else it for it in self.items]

    def get_item_uses(self, iid: str) -> int | None:
        for it in self.items:
            if isinstance(it, dict) and it.get("id") == iid:
                return it.get("uses")
            if not isinstance(it, dict) and it == iid:
                return None
        return None

    def consume_uses(self, iid: str, n: int = 1) -> bool:
        """扣减道具 n 点。返回是否已耗尽并移除。
        uses=None（无限）则不扣，返回 False。
        """
        for it in self.items:
            if not isinstance(it, dict):
                continue
            if it.get("id") != iid:
                continue
            if it.get("uses") is None:
                return False
            it["uses"] = it["uses"] - n
            if it["uses"] <= 0:
                self.items.remove(it)
                return True
            return False
        return False

    def consume_weapon_uses(self, items_cfg: dict) -> str | None:
        """扣减当前武器 1 点耐久。返回损坏的 iid（已移除），否则 None。"""
        iid, _w = self.weapon(items_cfg)
        if iid is None:
            return None
        for it in self.items:
            if not isinstance(it, dict):
                continue
            if it.get("id") != iid:
                continue
            if it.get("uses") is None:
                return None
            it["uses"] = it["uses"] - 1
            if it["uses"] <= 0:
                self.items.remove(it)
                return iid
            return None
        return None

    def add_item(
        self,
        iid: str,
        items_cfg: dict | None = None,
        uses: int | None = -1,
    ) -> None:
        """追加道具。
        uses=-1 表示按配置初始化；其他值原样使用（含 None 表示无限）。
        """
        if uses == -1:
            uses = _init_uses((items_cfg or {}).get(iid, {}))
        self.items.append({"id": iid, "uses": uses})

    def remove_item_by_id(self, iid: str) -> bool:
        """按 id 移除第一个匹配项。"""
        for i, it in enumerate(self.items):
            cur = it["id"] if isinstance(it, dict) else it
            if cur == iid:
                self.items.pop(i)
                return True
        return False

    def normalize_items(self, items_cfg: dict | None = None) -> None:
        """把 items 统一成 [{"id", "uses"}] 格式（读档兼容）。"""
        cfg = items_cfg or {}
        normalized: list[dict] = []
        for it in self.items:
            if isinstance(it, str):
                normalized.append({"id": it, "uses": _init_uses(cfg.get(it, {}))})
            elif isinstance(it, dict) and "id" in it:
                if "uses" in it:
                    normalized.append({"id": it["id"], "uses": it["uses"]})
                else:
                    normalized.append({
                        "id": it["id"],
                        "uses": _init_uses(cfg.get(it["id"], {})),
                    })
        self.items = normalized

    def item_display_list(self, items_cfg: dict | None = None) -> list[str]:
        """返回可用于 UI 显示的道具名列表。带 uses 后缀（无限则不显示）。"""
        cfg = items_cfg or {}
        out: list[str] = []
        for it in self.items:
            iid = it["id"] if isinstance(it, dict) else it
            name = cfg.get(iid, {}).get("name", iid)
            if isinstance(it, dict):
                uses = it.get("uses")
                if uses is not None:
                    name += f"（剩{uses}）"
            out.append(name)
        return out

    # ---------------- 升级 ----------------

    def level_up(self, global_cfg: dict) -> dict:
        gains: dict = {}
        for stat, rate in self.growth.items():
            if randint(1, 100) <= int(rate):
                gains[stat] = gains.get(stat, 0) + 1
                self.level_gains[stat] = self.level_gains.get(stat, 0) + 1
        for entry in (self.class_cfg or {}).get("skill_learn", []):
            if int(entry.get("level", -1)) == self.level and entry.get("skill") not in self.skills:
                self.skills.append(entry["skill"])
        self._recompute_stats()
        return gains

    def _apply_growth_guarantee(self, global_cfg: dict) -> tuple[str, int] | None:
        formulas = global_cfg.get("formulas", {})
        every = int(ev(str(formulas.get("growth_guarantee_levels", "0")), {}))
        min_g = int(ev(str(formulas.get("growth_guarantee_min", "0")), {}))
        if every <= 0 or min_g <= 0:
            return None
        if self._lv_since_guarantee < every:
            return None
        if self._gain_since_guarantee >= min_g:
            self._lv_since_guarantee = 0
            self._gain_since_guarantee = 0
            return None
        short = min_g - self._gain_since_guarantee
        if not self.growth:
            self._lv_since_guarantee = 0
            self._gain_since_guarantee = 0
            return None
        stat = max(self.growth.items(), key=lambda kv: kv[1])[0]
        self.level_gains[stat] = self.level_gains.get(stat, 0) + short
        self._recompute_stats()
        self._lv_since_guarantee = 0
        self._gain_since_guarantee = 0
        return stat, short

    def gain_exp(self, amount: int, global_cfg: dict) -> list[dict]:
        """增加经验并处理升级。

        v7.4b：
        - 等级上限优先读 class_cfg.max_level（职业配置）
        - 职业没配 → 走全局 max_level / max_level_promoted
        - 满级后不再累积经验（exp 归零），返回空列表
        """
        formulas = global_cfg.get("formulas", {})
        cc = self.class_cfg or {}

        # ═══ 等级上限：职业优先，全局兜底 ═══
        if "max_level" in cc and cc["max_level"] is not None:
            cap = int(cc["max_level"])
        else:
            cap_key = "max_level_promoted" if self.has_promoted else "max_level"
            cap = int(ev(str(formulas.get(cap_key, "20")), {}))

        if self.level >= cap:
            self.exp = 0
            return []

        threshold = int(ev(str(formulas.get("level_up_exp", "100")), {}))
        self.exp += int(amount)
        results: list[dict] = []
        while self.exp >= threshold and self.level < cap:
            self.exp -= threshold
            self.level += 1
            before = list(self.skills)
            gains = self.level_up(global_cfg)
            self._lv_since_guarantee += 1
            self._gain_since_guarantee += len([v for v in gains.values() if v > 0])
            bonus = self._apply_growth_guarantee(global_cfg)
            results.append({
                "level": self.level,
                "gains": gains,
                "new_skills": [s for s in self.skills if s not in before],
                "guarantee_bonus": bonus,
            })
        if self.level >= cap:
            self.exp = 0
        return results
    # ---------------- 转职 ----------------

    @property
    def promote_item(self) -> str:
        """转职所需道具 id（职业/人物覆盖的 promote.item；空=不需要）。"""
        promote = (self.class_cfg or {}).get("promote") or {}
        return str(promote.get("item", "") or "")

    @property
    def promote_options(self) -> list[str]:
        if not self.class_cfg:
            return []
        promote = self.class_cfg.get("promote") or {}
        if not promote:
            return []
        req_level = int(promote.get("level", 999))
        if self.level < req_level:
            return []
        return list(promote.get("to") or [])

    def promote(self, new_class: str, classes: dict) -> dict:
        cfg = classes.get(new_class)
        if not cfg:
            return {}
        if new_class not in self.promote_options:
            return {}
        old_class_name = (self.class_cfg or {}).get("name", "?")
        old_max = dict(self.max_stats)
        old_cur_hp = self.stats.get("hp", 0)
        self.class_cfg = cfg
        self.class_id = new_class
        self.class_stats = dict(cfg.get("stats", {}))
        self.move_type = cfg.get("move_type", "foot")
        new_class_growth = dict(cfg.get("growth", {}))
        self.growth = {
            k: self.base_growth.get(k, 0) + new_class_growth.get(k, 0)
            for k in set(self.base_growth) | set(new_class_growth)
        }
        self.class_growth = new_class_growth
        self.level = 1
        self.exp = 0
        self.has_promoted = True
        self._lv_since_guarantee = 0
        self._gain_since_guarantee = 0
        new_skills: list[str] = []
        for entry in cfg.get("skill_learn", []):
            sid = entry.get("skill")
            if sid and sid not in self.skills:
                self.skills.append(sid)
                new_skills.append(sid)
        self._recompute_stats()
        new_max_hp = self.max_stats.get("hp", 0)
        hp_delta = new_max_hp - old_max.get("hp", 0)
        self.stats["hp"] = min(old_cur_hp + max(0, hp_delta), new_max_hp)
        diffs: dict = {}
        for k in set(old_max) | set(self.max_stats):
            d = self.max_stats.get(k, 0) - old_max.get(k, 0)
            if d != 0:
                diffs[k] = d
        return {
            "old_class": old_class_name,
            "new_class": cfg.get("name", new_class),
            "diffs": diffs,
            "new_skills": new_skills,
        }