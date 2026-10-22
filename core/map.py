"""地图模型：地形、寻路（Dijkstra）、攻击目标检索、阵营判定。

地形数值（移动消耗/防御/回避）全部来自 config/global.yaml 的 terrain 段，
本模块不硬编码任何游戏数值。

阵营规则：
    player 与 ally 视为同盟（彼此可穿过、不可互相攻击）；
    enemy 与二者均为敌对（阻挡、可互相攻击）。

v7.1：
    move_range 新增 allow_ally_stay 参数。默认 False（可穿不可停，
    供 NPC / 威胁范围使用）；True 时同盟格也可停留，供玩家换位使用。
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Optional

DIRS: list[tuple[int, int]] = [(0, -1), (0, 1), (-1, 0), (1, 0)]
IMPASSABLE = 99

# 视为同盟的阵营对
_FRIENDLY_PAIRS: set[frozenset[str]] = {
    frozenset({"player", "player"}),
    frozenset({"ally", "ally"}),
    frozenset({"enemy", "enemy"}),
    frozenset({"player", "ally"}),
}


def is_hostile(a, b) -> bool:
    """a 与 b 是否敌对。player 与 ally 视为同盟。"""
    return frozenset({a.faction, b.faction}) not in _FRIENDLY_PAIRS


@dataclass
class GameMap:
    """一张地图。cfg 为 maps/*.yaml 的内容，terrain_cfg 为 global.yaml 的 terrain 段。"""

    cfg: dict
    terrain_cfg: dict
    units: list = field(default_factory=list)
    grid: list[list[str]] = field(init=False)
    width: int = field(init=False)
    height: int = field(init=False)

    def __post_init__(self) -> None:
        self.width = int(self.cfg["width"])
        self.height = int(self.cfg["height"])
        rows = self.cfg["grid"]
        if len(rows) != self.height:
            raise ValueError(
                f"grid 行数 {len(rows)} 与 height {self.height} 不一致（地图 {self.cfg.get('id')}）"
            )
        self.grid = []
        for i, row in enumerate(rows):
            if len(row) != self.width:
                raise ValueError(
                    f"grid 第 {i + 1} 行长度 {len(row)} 与 width {self.width} 不一致（地图 {self.cfg.get('id')}）"
                )
            self.grid.append(list(row))

    # ---------- 基础查询 ----------

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def char_at(self, x: int, y: int) -> str:
        return self.grid[y][x]

    def terrain_at(self, x: int, y: int) -> dict:
        # 越界保护：切图后 roster 单位可能还带着上一张图的坐标，
        # 此时整备面板/预测会查询地形 —— 按无地形效果返回，避免 IndexError。
        if not self.in_bounds(x, y):
            return {"color": "white", "move_cost": {"foot": 0, "mounted": 0},
                    "def": 0, "avoid": 0}
        ch = self.char_at(x, y)
        t = self.terrain_cfg.get(ch)
        if t is None:
            t = self.terrain_cfg.get(".", {"color": "white", "move_cost": {"foot": 1, "mounted": 1}})
        return t

    def unit_at(self, x: int, y: int) -> Optional[object]:
        for u in self.units:
            if u.alive and u.x == x and u.y == y:
                return u
        return None

    def move_cost(self, x: int, y: int, move_type: str) -> int:
        if move_type == "flying":
            return 1  # 飞行系无视一切地形（FE 规则）
        mc = self.terrain_at(x, y).get("move_cost", {})
        cost = mc.get(move_type, mc.get("foot", IMPASSABLE))
        return int(cost)

    # ---------- 寻路 / 索敌 ----------

    def move_range(self, unit, allow_ally_stay: bool = False) -> dict[tuple[int, int], int]:
        """Dijkstra 计算单位可达格：{(x,y): 累计消耗}。

        - 四方向移动；
        - 地形消耗取 terrain.move_cost[unit.move_type]，>=99 不可通行；
        - 敌对单位占格完全阻挡；同盟单位可穿过，但默认不可停留；
        - allow_ally_stay=True 时同盟格也可停留（玩家换位用），
          默认 False 保持 NPC / 威胁范围旧行为（可穿不可停）；
        - 只返回累计消耗 <= stats["mov"] 的格子。
        """
        start = (unit.x, unit.y)
        mov = int(unit.stats.get("mov", 0))
        dist: dict[tuple[int, int], int] = {start: 0}
        pq: list[tuple[int, tuple[int, int]]] = [(0, start)]
        while pq:
            d, (x, y) = heapq.heappop(pq)
            if d > dist.get((x, y), d):
                continue
            for dx, dy in DIRS:
                nx, ny = x + dx, y + dy
                if not self.in_bounds(nx, ny):
                    continue
                occ = self.unit_at(nx, ny)
                if occ is not None and is_hostile(unit, occ):
                    continue
                c = self.move_cost(nx, ny, unit.move_type)
                if c >= IMPASSABLE:
                    continue
                nd = d + c
                if nd <= mov and nd < dist.get((nx, ny), nd + 1):
                    dist[(nx, ny)] = nd
                    heapq.heappush(pq, (nd, (nx, ny)))
        if allow_ally_stay:
            return dist
        return {
            p: c
            for p, c in dist.items()
            if p == start or self.unit_at(*p) is None
        }

    def attack_targets(self, unit, items_cfg: dict) -> list:
        """当前武器射程区间（min-max）内的所有敌对单位。"""
        lo, hi = unit.weapon_range_span(items_cfg)
        if hi <= 0:
            return []
        return [
            u
            for u in self.units
            if u.alive
            and is_hostile(unit, u)
            and lo <= abs(u.x - unit.x) + abs(u.y - unit.y) <= hi
        ]