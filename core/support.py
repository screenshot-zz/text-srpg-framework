"""SupportMixin：支援好感度。

白名单：只有 stories.yaml 的 supports 段里配置的配对才累计。
好感度阈值 / 每场战斗加成 / 使用物品/杖加成 全在 global.yaml 的 support 段。
"""
from __future__ import annotations


class SupportMixin:
    def _support_cfg(self) -> dict:
        return self.global_cfg.get("support") or {}

    def _support_thresholds(self) -> list[int]:
        return [int(x) for x in (self._support_cfg().get("thresholds") or [])]

    def _is_support_pair(self, uid_a: str, uid_b: str) -> bool:
        if not self.supports:
            return False
        return (f"{uid_a}_{uid_b}" in self.supports
                or f"{uid_b}_{uid_a}" in self.supports)

    def _support_max_level_for(self, uid_a: str, uid_b: str) -> int:
        cfg = (self.supports.get(f"{uid_a}_{uid_b}")
               or self.supports.get(f"{uid_b}_{uid_a}") or {})
        if not cfg:
            return 0
        if "max_level" in cfg:
            return int(cfg["max_level"])
        dialogues = cfg.get("dialogues")
        if isinstance(dialogues, list) and dialogues:
            lv = [int(d.get("level", 0)) for d in dialogues if isinstance(d, dict)]
            if lv:
                return max(lv)
        return 1

    def _support_point_cap(self, uid_a: str, uid_b: str) -> int:
        lv = self._support_max_level_for(uid_a, uid_b)
        th = self._support_thresholds()
        if not th or lv <= 0:
            return 0
        return th[min(lv, len(th)) - 1]

    def _add_support_points(self, a, b, gain: int) -> None:
        if gain <= 0 or a is b or a.uid == b.uid:
            return
        if not self._is_support_pair(a.uid, b.uid):
            return
        cap = self._support_point_cap(a.uid, b.uid)
        for u, v in ((a, b), (b, a)):
            cur = u.support_points.get(v.uid, 0)
            u.support_points[v.uid] = min(cur + gain, cap)

    def _gain_support_points_from_battle(self, atk, dfn) -> None:
        gain = int((self._support_cfg().get("gain") or {}).get("battle_adjacent", 0))
        if gain <= 0:
            return
        for fighter in (atk, dfn):
            if not fighter.alive:
                continue
            for other in self.units:
                if not other.alive or other is fighter:
                    continue
                if other.faction != fighter.faction:
                    continue
                if abs(other.x - fighter.x) + abs(other.y - fighter.y) != 1:
                    continue
                self._add_support_points(fighter, other, gain)