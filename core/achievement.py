"""AchievementMixin：成就解锁 + 成就行追加。"""
from __future__ import annotations

from core.formula import ev


class AchievementMixin:
    def _check_achievements(self) -> list[dict]:
        ach_cfg = self.global_cfg.get("achievements") or {}
        if not ach_cfg:
            return []
        unlocked = self.global_vars.setdefault("achievements", [])
        unlocked_set = set(unlocked)
        gs = self.global_vars.setdefault("global_stats", {})
        newly: list[dict] = []
        for aid, cfg in ach_cfg.items():
            if aid in unlocked_set:
                continue
            cond = cfg.get("condition", "")
            if not cond:
                continue
            try:
                ok = bool(ev(str(cond), gs))
            except Exception:
                ok = False
            if ok:
                unlocked.append(aid)
                unlocked_set.add(aid)
                newly.append({"id": aid, **cfg})
        if newly:
            self._save_global()
        return newly

    def _append_achievement_lines(self, lines: list[str]) -> None:
        for ach in self._check_achievements():
            lines.append(f"▶ 达成成就【{ach['name']}】{ach.get('description', '')}")