"""ModeMixin：模式 / 难度 / 教堂配置。

模式：经典/休闲（game_modes 配置），控制 permadeath / 复活 HP。
难度：普通/困难/地狱（difficulties 配置），控制敌方属性加成 / 开局脚本。
教堂：economy.church 段，控制治疗/祝福/复活价格。
"""
from __future__ import annotations

from core.ui import _console, show_difficulty_menu, show_game_mode_menu


class ModeMixin:
    # ---------------- 模式 ----------------

    def _mode_cfg(self) -> dict:
        modes = self.global_cfg.get("game_modes") or {}
        if self.mode and self.mode in modes:
            return dict(modes[self.mode] or {})
        return dict(self.global_cfg.get("game_mode") or {})

    def mode_display_name(self) -> str:
        return str(self._mode_cfg().get("name") or self.mode or "休闲模式")

    def _permadeath(self) -> bool:
        return bool(self._mode_cfg().get("permadeath", False))

    def _legacy_mode_id(self) -> str:
        old_pd = bool((self.global_cfg.get("game_mode") or {}).get("permadeath", False))
        modes = self.global_cfg.get("game_modes") or {}
        for mid, cfg in modes.items():
            if bool((cfg or {}).get("permadeath", False)) == old_pd:
                return mid
        return "classic" if old_pd else "casual"

    def _select_mode(self) -> str | None:
        modes = self.global_cfg.get("game_modes") or {}
        if not modes:
            return self._legacy_mode_id()
        options = [{"id": k, **(v or {})} for k, v in modes.items()]
        if len(options) == 1:
            return options[0]["id"]
        return show_game_mode_menu(options)

    # ---------------- 难度 ----------------

    def _difficulty_cfg(self) -> dict:
        diffs = self.global_cfg.get("difficulties") or {}
        return dict(diffs.get(self.difficulty) or {})

    def difficulty_display_name(self) -> str:
        return str(self._difficulty_cfg().get("name") or self.difficulty or "普通")

    def _select_difficulty(self) -> str | None:
        diffs = self.global_cfg.get("difficulties") or {}
        if not diffs:
            return "normal"
        options = [{"id": k, **(v or {})} for k, v in diffs.items()]
        if len(options) == 1:
            return options[0]["id"]
        return show_difficulty_menu(options)

    def _apply_difficulty_to_unit(self, u) -> None:
        if u.faction != "enemy":
            return
        cfg = self._difficulty_cfg()
        bonus = {}
        for k, v in (cfg.get("enemy_stat_bonus") or {}).items():
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
            if v:
                bonus[k] = bonus.get(k, 0) + v
        if bonus:
            for k, v in bonus.items():
                u.stat_bonus[k] = u.stat_bonus.get(k, 0) + v
            u._recompute_stats()
        try:
            gb = int(cfg.get("enemy_growth_bonus", 0) or 0)
        except (TypeError, ValueError):
            gb = 0
        if gb:
            for k in u.growth:
                u.growth[k] = min(100, int(u.growth[k]) + gb)

    def _run_difficulty_start_actions(self) -> None:
        acts = self._difficulty_cfg().get("start_actions") or []
        if not acts:
            return
        from core.event import run_action
        for act in acts:
            run_action(act, self)
        _console.print(f"[yellow]【难度脚本】已生效：{self.difficulty_display_name()}[/yellow]")

    # ---------------- 教堂配置 ----------------

    def _church_cfg(self) -> dict:
        eco = self.global_cfg.get("economy") or {}
        church = dict(eco.get("church") or {})
        if "revive_cost" not in church and "revive_cost" in eco:
            church["revive_cost"] = eco["revive_cost"]
        return church