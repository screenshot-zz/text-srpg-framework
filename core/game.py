"""Game 主类：装配所有 Mixin + 保留主流程 / 地图 / 回合调度 / 胜负判定。

v7：新增 NPC 到达点纯剧情触发（_check_npc_reach_events）。
v7.1：新增 campaign 段（固定章节顺序 + 出战预设）。
v7.2：新增地形系统：
    - 顶层 heal 字段（回合结束回血，向后兼容）
    - triggers 列表（任意时机触发剧情/回血/扣血/动作，支持 once + condition）
"""
from __future__ import annotations

import os
from typing import Optional

from rich.panel import Panel
from rich.text import Text

from core.audio import AudioPlayer
from core.constants import (
    BASE_DIR, CONFIG_DIR, DIRS, LOSE_TRIGGERS, MAP_DIR,
    NON_RESULT_TRIGGERS, default_global_vars, default_stats, load_yaml,
)
from core.save import SaveMixin
from core.mode import ModeMixin
from core.support import SupportMixin
from core.achievement import AchievementMixin
from core.battle import BattleMixin
from core.action import ActionMixin
from core.npc import NpcMixin
from core.formula import ev, _DotDict
from core.map import GameMap
from core.unit import AI_OVERRIDE_KEYS, Unit
from core.ui import (
    _console, log, read_key,
    render_achievements, render_battle_log, render_global_stats,
    render_screen, render_support_panel, render_this_game_stats,
    show_main_menu,
)


class Game(
    SaveMixin,
    ModeMixin,
    SupportMixin,
    AchievementMixin,
    BattleMixin,
    ActionMixin,
    NpcMixin,
):
    def __init__(self) -> None:
        self.global_cfg: dict = {}
        self.classes: dict = {}
        self.skills: dict = {}
        self.status: dict = {}
        self.items: dict = {}
        self.stories: dict = {}
        self.supports: dict = {}
        self.units_cfg: dict = {}
        self.maps: dict = {}
        self.ai_profiles: dict = {}
        self.map: Optional[GameMap] = None
        self.units: list[Unit] = []
        self.roster: list[Unit] = []
        self.warehouse: list[dict] = []
        self.turn: int = 1
        self.state: str = "title"
        self.map_id: str = ""
        self.gold: int = 0
        self._had_enemies: bool = False
        self._victory_handled: bool = False
        self._fired_events: set = set()
        self._fired_talks: set = set()
        self._fired_terrain: set = set()   # {(unit_uid, char, trigger_index), ...}
        self.stats: dict = default_stats()
        self.vars: dict = {}
        self.difficulty: str = "normal"
        self.mode: str = "casual"
        self.battle_log: list[str] = []
        self.global_vars: dict = default_global_vars()
        self._log_start: int = 0
        self.pending_blessings: list[dict] = []
        self.audio = AudioPlayer()

    def _pause(self, message: str, cursor: Optional[tuple[int, int]] = None) -> None:
        if cursor is None:
            cursor = (0, 0)
            for u in self.units:
                if u.faction == "player" and u.alive:
                    cursor = (u.x, u.y)
                    break
        render_screen(self, cursor=cursor, message=message + "\n【按回车继续】")
        read_key()

    # ---------------- 配置加载 ----------------

    def load_all_configs(self) -> None:
        self.global_cfg = load_yaml(os.path.join(CONFIG_DIR, "global.yaml"))
        self.classes = load_yaml(os.path.join(CONFIG_DIR, "classes.yaml"))
        self.skills = load_yaml(os.path.join(CONFIG_DIR, "skills.yaml"))
        self.status = load_yaml(os.path.join(CONFIG_DIR, "status.yaml"))
        self.items = load_yaml(os.path.join(CONFIG_DIR, "items.yaml"))
        self.stories = load_yaml(os.path.join(CONFIG_DIR, "stories.yaml"))
        self.supports = self.stories.get("supports", {}) if isinstance(self.stories, dict) else {}
        self.units_cfg = load_yaml(os.path.join(CONFIG_DIR, "units.yaml"))
        self.ai_profiles = self.global_cfg.get("ai_profiles") or {}
        self.maps = {}
        if os.path.isdir(MAP_DIR):
            for fn in sorted(os.listdir(MAP_DIR)):
                if fn.endswith((".yaml", ".yml")):
                    cfg = load_yaml(os.path.join(MAP_DIR, fn))
                    if cfg.get("id"):
                        self.maps[cfg["id"]] = cfg
        self._load_global()
        self._migrate_legacy_save()
        self._order_maps()

    def _order_maps(self) -> None:
        order = (self.global_cfg.get("campaign") or {}).get("maps") or []
        if not order:
            return
        ordered: dict = {}
        for mid in order:
            if mid in self.maps:
                ordered[mid] = self.maps[mid]
            else:
                print(f"[章节配置] campaign.maps 里的 {mid} 不存在，已跳过")
        for mid, cfg in self.maps.items():
            if mid not in ordered:
                print(f"[章节配置] {mid} 未在 campaign.maps 中列出，追加到末尾")
                ordered[mid] = cfg
        self.maps = ordered

    # ---------------- 出战容量 ----------------

    def _initial_gold(self) -> int:
        return int((self.global_cfg.get("economy") or {}).get("initial_gold", 0))

    def _max_deploy(self) -> int:
        return int((self.global_cfg.get("economy") or {}).get("max_deploy", 4))

    def _map_max_deploy(self, map_id: str | None = None) -> int:
        mid = map_id or self.map_id
        if mid and mid in self.maps:
            cfg = self.maps[mid]
            if "max_deploy" in cfg:
                return int(cfg["max_deploy"])
        return self._max_deploy()

    def _map_deploy_capacity(self, map_id: str | None = None) -> int:
        mid = map_id or self.map_id
        if not mid or mid not in self.maps:
            return self._max_deploy()
        cfg = self.maps[mid]
        cap = self._map_max_deploy(mid)
        points = list(cfg.get("deploy_points") or [])
        if not points:
            for u in cfg.get("units", []):
                if u.get("faction", "player") == "player":
                    points.append({"x": u["x"], "y": u["y"]})
        if not points:
            return cap
        return min(cap, len(points))

    def _deploy_preset_for(self, map_id: str) -> list[str] | None:
        campaign = self.global_cfg.get("campaign") or {}
        presets = campaign.get("deploy_presets") or {}
        if map_id in presets:
            return list(presets[map_id] or [])
        maps = campaign.get("maps") or []
        if maps and map_id == maps[0] and campaign.get("first_deploy"):
            return list(campaign["first_deploy"])
        return None

    # ---------------- 地图加载 ----------------

    def _build_map_only(self, map_id: str) -> None:
        if map_id not in self.maps:
            raise KeyError(f"地图 {map_id} 不存在，可用：{list(self.maps)}")
        self.map_id = map_id
        self.map = GameMap(self.maps[map_id], self.global_cfg.get("terrain", {}))
        self._victory_handled = False
        self._fired_events = set()
        self._fired_talks = set()
        # _fired_terrain 不重置：跨回合、跨地图的 once 记录保留

    def _instantiate_unit(self, uid: str, u_cfg: dict) -> Unit:
        if uid not in self.units_cfg:
            raise KeyError(f"units.yaml 中缺少单位定义：{uid}")
        base = dict(self.units_cfg[uid])
        for k in ("ai", *AI_OVERRIDE_KEYS):
            if k in u_cfg:
                base[k] = u_cfg[k]
        u = Unit.from_cfg(
            uid, base, self.classes,
            u_cfg.get("faction", "player"), u_cfg["x"], u_cfg["y"],
            self.ai_profiles, items_cfg=self.items,
        )
        self._apply_difficulty_to_unit(u)
        return u

    def _init_roster(self, capacity: int | None = None,
                     preset: list[str] | None = None) -> None:
        if capacity is None:
            capacity = self._max_deploy()
        self.roster = []
        if preset is not None:
            valid: list[str] = []
            for uid in preset:
                if uid not in self.units_cfg:
                    print(f"[章节配置] deploy_presets 里的 {uid} 不存在，已忽略")
                    continue
                if not self.units_cfg[uid].get("deployable"):
                    print(f"[章节配置] {uid} 不是 deployable 单位，已忽略")
                    continue
                valid.append(uid)
            if len(valid) > capacity:
                print(f"[章节配置] 预设 {len(valid)} 人，本关只能上 {capacity} 人，"
                      f"多余 {len(valid) - capacity} 人转为待命")
                valid = valid[:capacity]
            valid_set = set(valid)
            for uid, cfg in self.units_cfg.items():
                if not cfg.get("deployable"):
                    continue
                u = Unit.from_cfg(uid, cfg, self.classes, "player", 0, 0,
                                  self.ai_profiles, items_cfg=self.items)
                u.deployed = uid in valid_set
                self.roster.append(u)
            return
        count = 0
        for uid, cfg in self.units_cfg.items():
            if not cfg.get("deployable"):
                continue
            u = Unit.from_cfg(uid, cfg, self.classes, "player", 0, 0,
                              self.ai_profiles, items_cfg=self.items)
            if u.deployed:
                if count >= capacity:
                    u.deployed = False
                else:
                    count += 1
            self.roster.append(u)

    def _deploy_roster_on_map(self) -> None:
        cfg = self.maps[self.map_id]
        deploy_points = list(cfg.get("deploy_points") or [])
        if not deploy_points:
            for u in cfg.get("units", []):
                if u.get("faction", "player") == "player":
                    deploy_points.append({"x": u["x"], "y": u["y"]})
        deployed_units = [u for u in self.roster if u.deployed and u.alive]
        if len(deployed_units) > len(deploy_points):
            overflow = deployed_units[len(deploy_points):]
            for u in overflow:
                u.deployed = False
                print(f"[部署] {u.name} 超出本关可用位置数，暂不上场")
            deployed_units = deployed_units[:len(deploy_points)]
        for i, unit in enumerate(deployed_units):
            unit.x = int(deploy_points[i]["x"])
            unit.y = int(deploy_points[i]["y"])
            unit.acted = False
            unit.moved_this_turn = False
            unit.status = []
            unit.status_turns = {}
            self.units.append(unit)

    def load_map(self, map_id: str, defer_start: bool = False) -> None:
        self._build_map_only(map_id)
        cfg = self.maps[map_id]
        self.units = []
        roster_uids = {u.uid for u in self.roster}
        for u in cfg.get("units", []):
            uid = u["id"]
            if uid in roster_uids:
                continue
            self.units.append(self._instantiate_unit(uid, u))
        self._deploy_roster_on_map()
        self.map.units = self.units
        self.turn = 1
        self._had_enemies = any(x.faction == "enemy" for x in self.units)
        bgm = cfg.get("bgm")
        if bgm:
            played = self.audio.play(os.path.join(BASE_DIR, bgm))
            if not played:
                print(f"[BGM] 音乐文件缺失或无法播放：{bgm}")
        if not defer_start:
            self._fire_start_events()

    def _fire_start_events(self) -> None:
        self._redeploy_roster()
        self._apply_pending_blessings()
        for ev_cfg in self.map.cfg.get("events", []):
            if ev_cfg.get("trigger") == "start":
                story_id = ev_cfg.get("story")
                if story_id and story_id in self.stories:
                    from core.event import run_story
                    run_story(story_id, self)

    def _redeploy_roster(self) -> None:
        self.units = [u for u in self.units if u.faction != "player"]
        self._deploy_roster_on_map()
        self.map.units = self.units

    def _apply_pending_blessings(self) -> None:
        if not self.pending_blessings:
            return
        for u in self.units:
            if not u.alive or u.faction != "player":
                continue
            for b in self.pending_blessings:
                sid = b.get("status")
                if not sid:
                    continue
                cfg = self.status.get(sid, {})
                if not cfg:
                    continue
                dur = int(b.get("duration", cfg.get("duration", 1)))
                if sid not in u.status:
                    u.status.append(sid)
                u.status_turns[sid] = dur
        self.pending_blessings = []

    def _show_prep(self) -> bool:
        if not self._permadeath():
            mcfg = self._mode_cfg()
            revive_hp = int(mcfg.get(
                "revive_hp",
                (self.global_cfg.get("game_mode") or {}).get("casual_revive_hp", 1),
            ))
            for u in self.roster:
                if not u.alive:
                    u.alive = True
                    if revive_hp > 0:
                        u.stats["hp"] = min(revive_hp, u.max_stats.get("hp", 1))
                    else:
                        u.stats["hp"] = u.max_stats.get("hp", 1)
                    u.status = []
                    u.status_turns = {}
        from core.prep import PrepScreen
        return PrepScreen(self).run()

    # ---------------- 日志 ----------------

    def _log_battle(self, line: str) -> None:
        self.battle_log.append(f"T{self.turn} {line}")
        if len(self.battle_log) > 300:
            self.battle_log = self.battle_log[-300:]

    # ---------------- 统计菜单 ----------------

    def _show_stats_view(self) -> None:
        while True:
            _console.clear()
            body = Text()
            body.append("  1. 本局统计\n")
            body.append("  2. 跨存档累计\n")
            body.append("  3. 成就\n")
            body.append("  4. 好感度\n")
            body.append("  0. 返回\n")
            _console.print(Panel(body, title="统计", border_style="cyan",
                                 padding=(0, 2), expand=False))
            k = read_key()
            if k in ("0", "esc", "quit"):
                return
            if k == "1":
                _console.clear(); render_this_game_stats(self)
                _console.print("[dim]按任意键返回[/dim]"); read_key()
            elif k == "2":
                _console.clear(); render_global_stats(self)
                _console.print("[dim]按任意键返回[/dim]"); read_key()
            elif k == "3":
                _console.clear(); render_achievements(self)
                _console.print("[dim]按任意键返回[/dim]"); read_key()
            elif k == "4":
                _console.clear(); render_support_panel(self)
                _console.print("[dim]按任意键返回[/dim]"); read_key()

    def _show_battle_log_view(self) -> None:
        self._log_start = render_battle_log(self, self._log_start)

    # ---------------- 主流程 ----------------

    def run(self) -> None:
        self.load_all_configs()
        try:
            while True:
                # 标题 BGM（每次回主菜单都尝试，同曲不重播）
                title_bgm = (self.global_cfg.get("bgm") or {}).get("title")
                if title_bgm:
                    self.audio.play(os.path.join(BASE_DIR, title_bgm))
                choice = show_main_menu(self.global_cfg.get("game_title", ""))
                if choice == "quit":
                    self._save_global()
                    print("再见！")
                    return
                if choice == "start":
                    self._new_game()
                elif choice == "load":
                    kind = self._show_save_select()
                    if kind is None:
                        continue
                    if kind == "section":
                        _console.print("[green]【读档成功】回到整备界面[/green]")
                        if not self._show_prep():
                            self.state = "title"
                            continue
                        self._fire_start_events()
                    else:
                        _console.print("[green]【读档成功】[/green]")
                    self.state = "play"
                    self._game_loop()
        except (EOFError, KeyboardInterrupt):
            self._save_global()
            print("\n输入结束，游戏退出，再见！")

    def _new_game(self) -> None:
        ids = list(self.maps.keys())
        if not ids:
            print("config/maps/ 下没有可用地图。")
            return
        diff = self._select_difficulty()
        if diff is None:
            return
        mode = self._select_mode()
        if mode is None:
            return
        self.difficulty = diff
        self.mode = mode
        _console.print(
            f"[yellow]【难度】{self.difficulty_display_name()}[/yellow]　"
            f"[magenta]【模式】{self.mode_display_name()}[/magenta]"
        )
        self.gold = self._initial_gold()
        init_wh = (self.global_cfg.get("economy") or {}).get("initial_warehouse") or []
        self.warehouse = [{"id": iid, "uses": None} for iid in init_wh
                          if iid in self.items]
        self.stats = default_stats()
        self.vars = {}
        self.battle_log = []
        self.pending_blessings = []
        self._fired_terrain = set()
        self.global_vars["global_stats"]["total_games_played"] += 1
        self._save_global()
        first_map = ids[0]
        preset = self._deploy_preset_for(first_map)
        self._init_roster(
            capacity=self._map_deploy_capacity(first_map),
            preset=preset,
        )
        self._run_difficulty_start_actions()
        self.load_map(first_map)
        self.state = "play"
        self._game_loop()

    def _game_loop(self) -> None:
        while True:
            self._process_terrain_triggers("turn_start")
            self.player_phase()
            self._pause("玩家回合结束，即将进入敌方/友军回合。")
            self.npc_phase()
            self._pause("敌方/友军回合结束，即将结算状态效果。")
            self._process_status()
            self._process_terrain_heal()
            self._process_terrain_triggers("turn_end")
            result = self.check_victory()
            if result == "exit":
                self.state = "title"
                return
            if result in ("defeat", "clear"):
                self.state = "title"
                self._pause("战斗结束，返回标题。")
                return
            if result == "victory":
                self._pause(f"胜利！进入新地图：{self.map.cfg.get('name', '')}")
                continue
            self.turn += 1
            self.stats["turns"] += 1
            self.global_vars["global_stats"]["total_turns"] += 1

    # ---------------- 胜负判定 ----------------

    def _condition_texts(self) -> tuple[list[str], list[str]]:
        if not self.map:
            return [], []
        win, lose = [], []
        for e in self.map.cfg.get("events", []):
            trigger = e.get("trigger")
            if trigger in NON_RESULT_TRIGGERS:
                continue
            result = e.get("result")
            if result is None:
                if trigger in LOSE_TRIGGERS:
                    result = "lose"
                elif trigger in ("all_enemy_dead", "boss_killed"):
                    result = "win"
                else:
                    continue
            text = e.get("text") or self._auto_text(trigger, e)
            if not text:
                continue
            (lose if result == "lose" else win).append(text)
        return win, lose

    def _auto_text(self, trigger: str, e: dict) -> str:
        if trigger == "all_enemy_dead":
            return "击败所有敌人"
        if trigger == "all_player_dead":
            return "我方全灭"
        if trigger == "lord_dead":
            for u in self.units:
                if u.is_lord and u.faction == "player":
                    return f"{u.name} 阵亡"
            return "主角阵亡"
        if trigger == "boss_killed":
            boss_uid = e.get("boss", "")
            for u in self.units:
                if u.uid == boss_uid:
                    return f"击败 {u.name}"
            return f"击败首领 {boss_uid}"
        if trigger == "reach_point":
            return f"到达 ({e.get('x')},{e.get('y')})"
        if trigger == "turn_limit":
            return f"超过 {e.get('turn')} 回合"
        return ""

    def _check_trigger(self, trigger_cfg: dict) -> bool:
        trigger = trigger_cfg.get("trigger")
        if trigger == "all_enemy_dead":
            if not self._had_enemies:
                return False
            return not any(u.faction == "enemy" and u.alive for u in self.units)
        if trigger == "all_player_dead":
            return bool(self.units) and not any(
                u.faction == "player" and u.alive for u in self.units
            )
        if trigger == "lord_dead":
            lords = [u for u in self.units if u.is_lord and u.faction == "player"]
            if not lords:
                return False
            return all(not u.alive for u in lords)
        if trigger == "boss_killed":
            boss_uid = trigger_cfg.get("boss")
            if not boss_uid:
                return False
            found = False
            for u in self.units:
                if u.uid == boss_uid:
                    found = True
                    if u.alive:
                        return False
            return found
        if trigger == "reach_point":
            x = int(trigger_cfg.get("x", -1))
            y = int(trigger_cfg.get("y", -1))
            uid = trigger_cfg.get("unit")
            faction = trigger_cfg.get("faction")
            for u in self.units:
                if not u.alive:
                    continue
                if uid:
                    if u.uid != uid:
                        continue
                elif faction:
                    if u.faction != faction:
                        continue
                else:
                    if u.faction != "player":
                        continue
                if u.x == x and u.y == y:
                    return True
            return False
        if trigger == "turn_limit":
            return self.turn > int(trigger_cfg.get("turn", 999))
        return False

    def _run_result_story(self, e: dict) -> None:
        story_id = e.get("story")
        if story_id and story_id in self.stories:
            from core.event import run_story
            run_story(story_id, self)

    def _record_clear(self, clear_turn: int | None = None) -> None:
        turn = clear_turn if clear_turn is not None else self.turn
        self.stats["maps_cleared"] += 1
        prev = self.stats.get("min_clear_turns", 0)
        if prev == 0 or turn < prev:
            self.stats["min_clear_turns"] = turn
        gs = self.global_vars["global_stats"]
        gs["total_maps_cleared"] += 1
        gprev = gs.get("min_clear_turns", 0)
        if gprev == 0 or turn < gprev:
            gs["min_clear_turns"] = turn

    def check_victory(self) -> str:
        if self._victory_handled:
            return "continue"
        events = self.map.cfg.get("events", [])

        for e in events:
            trigger = e.get("trigger")
            if trigger in NON_RESULT_TRIGGERS:
                continue
            result = e.get("result")
            if result is None:
                if trigger in LOSE_TRIGGERS:
                    result = "lose"
                elif trigger in ("all_enemy_dead", "boss_killed"):
                    result = "win"
                else:
                    continue
            if result != "lose" or not self._check_trigger(e):
                continue
            self._victory_handled = True
            self._run_result_story(e)
            return "defeat"

        for e in events:
            trigger = e.get("trigger")
            if trigger in NON_RESULT_TRIGGERS:
                continue
            result = e.get("result")
            if result is None:
                if trigger in LOSE_TRIGGERS:
                    result = "lose"
                elif trigger in ("all_enemy_dead", "boss_killed"):
                    result = "win"
                else:
                    continue
            if result != "win" or not self._check_trigger(e):
                continue
            self._victory_handled = True
            original_map_id = self.map_id
            original_turn = self.turn
            self._run_result_story(e)

            if self.state == "title":
                return "exit"

            if self.map_id != original_map_id:
                self._record_clear(original_turn)
                self._check_achievements()
                return "victory"

            next_id = self._next_map_id()
            if next_id is None:
                self._record_clear()
                self._check_achievements()
                print("【通关】所有地图已完成！感谢游玩。")
                return "clear"

            self._record_clear()
            self._check_achievements()
            self.load_map(next_id, defer_start=True)
            if not self._show_prep():
                self.state = "title"
                return "exit"
            self._fire_start_events()
            return "victory"

        if self.units and not any(u.faction == "player" and u.alive for u in self.units):
            print("【败北】所有我方单位已阵亡……")
            return "defeat"
        return "continue"

    def _next_map_id(self) -> Optional[str]:
        ids = list(self.maps.keys())
        try:
            i = ids.index(self.map_id)
        except ValueError:
            return None
        return ids[i + 1] if i + 1 < len(ids) else None

    # ---------------- 回合调度 ----------------

    def player_phase(self) -> None:
        for u in self.units:
            if u.faction == "player":
                u.acted = False
                u.moved_this_turn = False
        cursor: Optional[list[int]] = None
        for u in self.units:
            if u.faction == "player" and u.alive and not u.acted:
                cursor = [u.x, u.y]
                break
        if cursor is None:
            return
        while True:
            todo = [u for u in self.units if u.faction == "player" and u.alive and not u.acted]
            if not todo:
                break
            selected = self._select_unit_by_cursor(cursor, todo)
            if selected is None:
                for u in todo:
                    u.acted = True
                break
            cursor = [selected.x, selected.y]
            self.select_and_act(selected)

    def _select_unit_by_cursor(self, cursor: list[int], todo: list[Unit]) -> Optional[Unit]:
        cx, cy = cursor
        while True:
            danger = None
            u = self.map.unit_at(cx, cy)
            if u is not None and u.alive and u.faction == "enemy":
                danger = self._enemy_threat_range(u)
            render_screen(
                self, cursor=(cx, cy), danger=danger,
                message="方向键移动　回车选择　F 结束回合　K 存档　L 日志　T 统计",
            )
            k = read_key()
            if k == "enter":
                u = self.map.unit_at(cx, cy)
                if u is not None and u.faction == "player" and u.alive and not u.acted:
                    return u
                log("请将光标移到己方未行动单位上。", "red")
            elif k == "f":
                return None
            elif k == "k":
                path = self.save_game("manual")
                if path:
                    self._pause(f"游戏已保存到 {os.path.basename(path)}", cursor=(cx, cy))
                else:
                    self._pause("存档失败！请检查磁盘空间或文件权限。", cursor=(cx, cy))
            elif k == "l":
                self._show_battle_log_view()
            elif k == "t":
                self._show_stats_view()
            elif k in ("esc", "quit"):
                return None
            else:
                d = DIRS.get(k)
                if d:
                    nx, ny = cx + d[0], cy + d[1]
                    if 0 <= nx < self.map.width and 0 <= ny < self.map.height:
                        cx, cy = nx, ny

    def npc_phase(self) -> None:
        for u in self.units:
            if u.faction != "player":
                u.acted = False
                u.moved_this_turn = False
        for npc in [u for u in self.units if u.faction != "player" and u.alive]:
            if not npc.alive:
                continue
            if self._is_stunned(npc):
                self._pause(f"{npc.name} 处于异常状态，无法行动！", cursor=(npc.x, npc.y))
                continue
            if npc.faction == "enemy":
                targets = [u for u in self.units
                           if u.faction in ("player", "ally") and u.alive]
            else:
                targets = [u for u in self.units if u.faction == "enemy" and u.alive]
            self._npc_act(npc, targets)
            self._check_npc_reach_events(npc)

    def _check_npc_reach_events(self, unit: Unit) -> None:
        from core.event import run_story
        for ev_cfg in self.map.cfg.get("events", []):
            if ev_cfg.get("trigger") != "reach_point":
                continue
            if ev_cfg.get("result"):
                continue
            uid = ev_cfg.get("unit")
            if uid and uid != unit.uid:
                continue
            x = int(ev_cfg.get("x", -1))
            y = int(ev_cfg.get("y", -1))
            if unit.x != x or unit.y != y:
                continue
            ev_id = ev_cfg.get("id") or ev_cfg.get("story")
            once = ev_cfg.get("once", True)
            if once and ev_id in self._fired_events:
                continue
            cond = ev_cfg.get("condition", "")
            if cond:
                try:
                    if not ev(str(cond), self._event_condition_ctx(unit)):
                        continue
                except Exception:
                    continue
            story_id = ev_cfg.get("story")
            if not story_id or story_id not in self.stories:
                continue
            if once:
                self._fired_events.add(ev_id)
            run_story(story_id, self)

    def _process_status(self) -> None:
        for u in self.units:
            if not u.alive:
                continue
            for sid in list(u.status):
                if not u.alive:
                    break
                s = self.status.get(sid, {})
                f = s.get("formula") or {}
                if "turn_damage" in f:
                    dmg = int(ev(str(f["turn_damage"]), {
                        "max_hp": u.max_stats.get("hp", 0),
                        "hp": u.stats.get("hp", 0),
                    }))
                    if dmg > 0:
                        u.stats["hp"] = max(0, u.stats.get("hp", 0) - dmg)
                        print(f"{u.name} 因{s.get('name', sid)}损失 {dmg} 点生命")
                        if u.stats["hp"] <= 0:
                            u.alive = False
                            if u.faction == "enemy":
                                self.stats["kills"] += 1
                                self.global_vars["global_stats"]["total_kills"] += 1
                            print(f"{u.name} 倒下了！")
                            break
                rem = u.status_turns.get(sid, 1) - 1
                u.status_turns[sid] = rem
                if rem <= 0:
                    u.status.remove(sid)
                    u.status_turns.pop(sid, None)
                    print(f"{u.name} 的{s.get('name', sid)}状态解除了。")

    def _process_terrain_heal(self) -> None:
        """顶层 heal 字段：回合结束时回血（向后兼容）。

        triggers 里的 heal 走 _run_terrain_trigger，不在此处。
        """
        lines: list[str] = []
        for u in self.units:
            if not u.alive:
                continue
            terrain = self.map.terrain_at(u.x, u.y)
            heal = int(terrain.get("heal", 0) or 0)
            if heal <= 0:
                continue
            max_hp = u.max_stats.get("hp", 0)
            cur = u.stats.get("hp", 0)
            if cur >= max_hp:
                continue
            u.stats["hp"] = min(cur + heal, max_hp)
            gained = u.stats["hp"] - cur
            tname = terrain.get("name", self.map.char_at(u.x, u.y))
            lines.append(f"{u.name} 在{tname}上恢复了 {gained} 点生命。"
                         f"（HP {u.stats['hp']}/{max_hp}）")
        if lines:
            self._pause("\n".join(lines))

    # ---------------- 地形触发器（v7.2 新增） ----------------

    def _process_terrain_triggers(self, timing: str) -> None:
        """扫描所有单位脚下地形的 triggers 列表，按 timing 执行。

        timing：turn_start / turn_end
        每个 trigger 支持：story / heal / damage / actions / once / condition
        once 的 key 是 (unit_uid, terrain_char, trigger_index)，每个单位独立。
        """
        for u in list(self.units):
            if not u.alive:
                continue
            # 每轮重新读 terrain（防止前面的 trigger 移动了单位）
            terrain = self.map.terrain_at(u.x, u.y)
            triggers = terrain.get("triggers") or []
            if not triggers:
                continue
            char = self.map.char_at(u.x, u.y)
            for idx, trg in enumerate(triggers):
                if not isinstance(trg, dict):
                    continue
                if trg.get("on") != timing:
                    continue
                if not u.alive:
                    break
                # once 检查
                once = bool(trg.get("once", False))
                key = (u.uid, char, idx)
                if once and key in self._fired_terrain:
                    continue
                # condition 检查
                cond = trg.get("condition", "")
                if cond:
                    try:
                        if not ev(str(cond), self._event_condition_ctx(u)):
                            continue
                    except Exception:
                        continue
                # 先标记 fired，避免剧情里 recursive 调用触发自己
                if once:
                    self._fired_terrain.add(key)
                self._run_terrain_trigger(u, terrain, trg, idx)

    def _run_terrain_trigger(self, unit: Unit, terrain: dict, trg: dict,
                             idx: int) -> None:
        """执行单个地形触发器。"""
        from core.event import run_story, run_action
        tname = terrain.get("name", "地形")
        lines: list[str] = []

        if "heal" in trg:
            heal = int(trg.get("heal") or 0)
            if heal > 0:
                max_hp = unit.max_stats.get("hp", 0)
                cur = unit.stats.get("hp", 0)
                if cur < max_hp:
                    unit.stats["hp"] = min(cur + heal, max_hp)
                    gained = unit.stats["hp"] - cur
                    lines.append(f"{unit.name} 在{tname}上恢复了 {gained} 点生命。"
                                 f"（HP {unit.stats['hp']}/{max_hp}）")

        if "damage" in trg:
            dmg = int(trg.get("damage") or 0)
            if dmg > 0:
                unit.stats["hp"] = max(0, unit.stats.get("hp", 0) - dmg)
                lines.append(f"{unit.name} 在{tname}上损失了 {dmg} 点生命。"
                             f"（HP {unit.stats['hp']}/{unit.max_stats.get('hp', 0)}）")
                if unit.stats["hp"] <= 0:
                    unit.alive = False
                    lines.append(f"{unit.name} 倒下了！")
                    if unit.faction == "enemy":
                        self.stats["kills"] += 1
                        self.global_vars["global_stats"]["total_kills"] += 1

        if lines:
            self._pause("\n".join(lines), cursor=(unit.x, unit.y))

        # 死亡就不再播剧情 / 执行动作
        if not unit.alive:
            return

        story_id = trg.get("story")
        if story_id and story_id in self.stories:
            run_story(story_id, self)

        for act in (trg.get("actions") or []):
            run_action(act, self)

    # ---------------- 事件 ----------------

    def _event_condition_ctx(self, unit: Unit) -> dict:
        """事件 / 地形触发器的条件上下文。

        被以下 4 处共用：
            - Game._check_events（地图 events 的 enter/interact 触发）
            - Game._check_npc_reach_events（NPC 纯剧情 reach_point）
            - Game._process_terrain_triggers（地形 triggers 的 condition）
            - ActionMixin._interact_available（行动菜单"访问"的 condition）
        """
        ctx = {
            # ─── 全局状态 ───
            "turn": self.turn,
            "gold": self.gold,
            "enemy_count": sum(1 for u in self.units if u.faction == "enemy" and u.alive),
            "ally_count": sum(1 for u in self.units if u.faction in ("player", "ally") and u.alive),
            "kills": int(self.stats.get("kills", 0)),
            # ─── 单位身份 ───
            "unit_uid": unit.uid,
            "unit_name": unit.name,
            "unit_faction": unit.faction,
            "unit_class": unit.class_id,
            "unit_alive": 1 if unit.alive else 0,
            "unit_moved": 1 if unit.moved_this_turn else 0,
            # ─── 单位数值 ───
            "unit_hp": unit.stats.get("hp", 0),
            "unit_max_hp": unit.max_stats.get("hp", 0),
            "unit_level": unit.level,
            "unit_exp": unit.exp,
            # ─── 单位状态 ───
            "unit_has_poison": 1 if "poison" in unit.status else 0,
            "unit_has_stun": 1 if "stun" in unit.status else 0,
            "unit_status_count": len(unit.status),
            # ─── 剧情变量 ───
            "vars": _DotDict(self.vars),
        }
        for k, v in self.vars.items():
            ctx[f"var_{k}"] = v
        # ─── 地形（v7.4c）───
        terrain_char = ""
        terrain_name = ""
        if self.map is not None and self.map.in_bounds(unit.x, unit.y):
            terrain_char = self.map.char_at(unit.x, unit.y)
            terrain_name = self.map.terrain_at(unit.x, unit.y).get("name", "")
        ctx["unit_terrain"] = terrain_char
        ctx["unit_terrain_name"] = terrain_name
        return ctx
    def _check_events(self, unit: Unit, trigger: str) -> None:
        from core.event import run_story
        for ev_cfg in self.map.cfg.get("events", []):
            if ev_cfg.get("trigger") != trigger:
                continue
            if trigger in ("enter", "interact"):
                if ev_cfg.get("x") != unit.x or ev_cfg.get("y") != unit.y:
                    continue
            ev_id = ev_cfg.get("id") or ev_cfg.get("story")
            once = ev_cfg.get("once", True)
            if once and ev_id in self._fired_events:
                continue
            cond = ev_cfg.get("condition", "")
            if cond:
                try:
                    if not ev(str(cond), self._event_condition_ctx(unit)):
                        continue
                except Exception:
                    continue
            story_id = ev_cfg.get("story")
            if not story_id or story_id not in self.stories:
                continue
            if once:
                self._fired_events.add(ev_id)
            run_story(story_id, self)