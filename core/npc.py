"""NpcMixin：敌方/友军回合 AI。

支持 6 种 move_mode：
- approach  默认：全局索敌，移动 + 攻击
- stay      驻守：原地攻击射程内
- sentinel  哨兵：警戒范围内出现敌人才行动，否则原地
- follow    跟随：跟随指定 uid，跟到 follow_distance 后原地
- move_to   前往：移动到指定点，到达触发 reached_action
- flee_to   撤退（旧名，兼容）：等同 move_to，参数名不同

回合调度在 Game.player_phase / npc_phase 控制。
"""
from __future__ import annotations

from core.unit import Unit


class NpcMixin:
    # ---------------- 基础工具 ----------------

    def _is_stunned(self, u) -> bool:
        for sid in u.status:
            s = self.status.get(sid, {})
            if (s.get("formula") or {}).get("skip_action"):
                return True
        return False

    def _dist(self, a, b) -> int:
        return abs(a.x - b.x) + abs(a.y - b.y)

    def _enemy_threat_range(self, enemy) -> set[tuple[int, int]]:
        """玩家看到的红色危险格。按 move_mode 智能收缩：
        - stay / 未触发的 sentinel：只显示攻击范围（原地打）
        - 其他：显示移动 + 攻击范围
        """
        mode = enemy.ai_params.get("move_mode", "approach")
        cells = self.map.move_range(enemy)
        if mode == "stay":
            cells = {(enemy.x, enemy.y)}
        elif mode == "sentinel":
            aggro = int(enemy.ai_params.get(
                "aggro_range", enemy.max_attack_range(self.items) or 1))
            in_aggro = any(
                u.alive and u.faction in ("player", "ally")
                and abs(enemy.x - u.x) + abs(enemy.y - u.y) <= aggro
                for u in self.units
            )
            if not in_aggro:
                cells = {(enemy.x, enemy.y)}
        rng = enemy.max_attack_range(self.items)
        danger: set[tuple[int, int]] = set()
        for (x, y) in cells:
            danger.add((x, y))
            for dx in range(-rng, rng + 1):
                for dy in range(-rng, rng + 1):
                    if abs(dx) + abs(dy) <= rng:
                        nx, ny = x + dx, y + dy
                        if self.map.in_bounds(nx, ny):
                            danger.add((nx, ny))
        return danger

    # ---------------- 主入口 ----------------

    def _npc_act(self, npc, targets: list) -> None:
        params = npc.ai_params
        mode = params.get("move_mode", "approach")

        if mode == "flee_to":
            self._npc_move_to(npc, targets, legacy=True)
            return
        if mode == "move_to":
            self._npc_move_to(npc, targets, legacy=False)
            return
        if mode == "follow":
            self._npc_follow(npc, targets)
            return
        if mode == "sentinel":
            self._npc_sentinel(npc, targets)
            return
        if mode == "stay" or not params.get("can_move", True):
            self._npc_stay(npc, targets)
            return
        self._npc_approach(npc, targets)

    # ---------------- 通用：射程内可攻击目标 ----------------

    def _npc_attack_range_targets(self, npc, targets) -> list:
        """当前能直接攻击到的目标，按 (残血优先, 近优先)。"""
        return sorted(
            [p for p in targets if npc.can_attack_at(self.items, self._dist(npc, p))],
            key=lambda p: (p.stats.get("hp", 0), self._dist(npc, p)),
        )

    # ---------------- 各模式实现 ----------------

    def _npc_stay(self, npc, targets) -> None:
        """原地不动；能打就打。"""
        if not npc.ai_params.get("can_attack", True):
            return
        now = self._npc_attack_range_targets(npc, targets)
        if now:
            self._npc_attack(npc, now[0])

    def _npc_approach(self, npc, targets) -> None:
        """全局索敌：射程内就打，否则走到能打的位置，否则靠近最近敌人。"""
        if not targets:
            return
        can_attack = bool(npc.ai_params.get("can_attack", True))

        now = self._npc_attack_range_targets(npc, targets)
        if now:
            if can_attack:
                self._npc_attack(npc, now[0])
            return

        cells = self.map.move_range(npc)
        if not cells:
            return

        # 优先：找一个能攻击敌人的位置
        attack_positions: list[tuple[tuple[int, int], int, object]] = []
        for (x, y), cost in cells.items():
            for p in targets:
                d = abs(x - p.x) + abs(y - p.y)
                if any(lo2 <= d <= hi2
                       for _i, c in npc.usable_weapons(self.items)
                       for lo2, hi2 in [Unit.range_span(c.get("range"))]):
                    attack_positions.append(((x, y), cost, p))
                    break
        if attack_positions:
            (bx, by), _cost, victim = min(
                attack_positions, key=lambda t: (t[1], t[2].stats.get("hp", 0))
            )
            npc.x, npc.y = bx, by
            npc.moved_this_turn = True
            if can_attack:
                self._npc_attack(npc, victim)
            return

        # 没有能攻击的位置：靠近最近的敌人
        target = min(targets, key=lambda p: (self._dist(npc, p), p.stats.get("hp", 0)))
        (bx, by), _cost = min(
            cells.items(),
            key=lambda kv: (abs(kv[0][0] - target.x) + abs(kv[0][1] - target.y), kv[1]),
        )
        if (bx, by) != (npc.x, npc.y):
            npc.x, npc.y = bx, by
            npc.moved_this_turn = True

    def _npc_sentinel(self, npc, targets) -> None:
        """哨兵：警戒半径内出现敌人 → 转为主动进攻；否则原地（最多打射程内）。"""
        aggro = int(npc.ai_params.get(
            "aggro_range", npc.max_attack_range(self.items) or 1))
        triggered = any(self._dist(npc, p) <= aggro for p in targets)
        if triggered:
            self._npc_approach(npc, targets)
        else:
            self._npc_stay(npc, targets)

    def _npc_follow(self, npc, targets) -> None:
        """跟随指定 uid；到了 follow_distance 内停下（可攻击射程内敌人）。"""
        target_uid = npc.ai_params.get("follow_target")
        follow_dist = int(npc.ai_params.get("follow_distance", 1))
        can_attack = bool(npc.ai_params.get("can_attack", True))

        leader = None
        for u in self.units:
            if u.alive and u.uid == target_uid:
                leader = u
                break
        if leader is None:
            # 跟随目标死了：原地守
            self._npc_stay(npc, targets)
            return

        # 能打就打
        if can_attack:
            now = self._npc_attack_range_targets(npc, targets)
            if now:
                self._npc_attack(npc, now[0])
                return

        # 距离超过 follow_distance → 靠近
        d_leader = self._dist(npc, leader)
        if d_leader > follow_dist:
            cells = self.map.move_range(npc)
            if cells:
                (bx, by), _ = min(
                    cells.items(),
                    key=lambda kv: (
                        abs(kv[0][0] - leader.x) + abs(kv[0][1] - leader.y),
                        kv[1],
                    ),
                )
                if (bx, by) != (npc.x, npc.y):
                    npc.x, npc.y = bx, by
                    npc.moved_this_turn = True

    def _npc_move_to(self, npc, targets, legacy: bool) -> None:
        """前往指定点。到达后按 reached_action 处理。

        legacy=True  → 旧的 flee_to（参数名 retreat_to / retreat_story / retreat_reached）
        legacy=False → 新的 move_to（参数名 move_to / reached_story / reached_action）
        """
        p = npc.ai_params
        if legacy:
            dest = p.get("retreat_to")
            reached_action = p.get("retreat_reached", "remove")
            reached_story = p.get("retreat_story")
        else:
            dest = p.get("move_to")
            reached_action = p.get("reached_action", "nothing")
            reached_story = p.get("reached_story")

        if not dest:
            return
        tx, ty = int(dest.get("x", 0)), int(dest.get("y", 0))

        # 已经到达（可能上回合就到了）
        if (npc.x, npc.y) == (tx, ty):
            self._handle_reached(npc, reached_action, reached_story)
            return

        # 走位：选离目标点最近的可达格
        cells = self.map.move_range(npc)
        if not cells:
            return
        (bx, by), _ = min(
            cells.items(),
            key=lambda kv: (abs(kv[0][0] - tx) + abs(kv[0][1] - ty), kv[1]),
        )
        if (bx, by) != (npc.x, npc.y):
            npc.x, npc.y = bx, by
            npc.moved_this_turn = True

        # 移动后恰好到达
        if (npc.x, npc.y) == (tx, ty):
            self._handle_reached(npc, reached_action, reached_story)
            return

        # 未到达：边移动边攻击（可选）
        if npc.ai_params.get("can_attack", False) and targets:
            now = self._npc_attack_range_targets(npc, targets)
            if now:
                self._npc_attack(npc, now[0])

    def _handle_reached(self, npc, action: str, story_id: str | None) -> None:
        """到达目标点后的处理。

        去重粒度：每个目标点独立（用坐标做 key）。
        换目标点后可以再次触发，同一个点只触发一次。
        记录在 npc.flags["_reached_points"] 里，随存档保存。

        action 取值：
            story   —— 只播剧情（不消失）
            remove  —— 消失（不播剧情）
            both    —— 播剧情 + 消失
            nothing —— 什么都不做（停住，下回合继续站原地）
        """
        # ═══ 坐标去重：每个目标点独立触发一次 ═══
        dest = npc.ai_params.get("move_to") or npc.ai_params.get("retreat_to")
        if not dest:
            return
        tx = int(dest.get("x", 0))
        ty = int(dest.get("y", 0))
        reached = npc.flags.setdefault("_reached_points", [])
        key = [tx, ty]
        if key in reached:
            return
        reached.append(key)

        lines = [f"{npc.name} 到达了目的地。"]
        if action in ("story", "both") and story_id and story_id in self.stories:
            self._pause("\n".join(lines), cursor=(npc.x, npc.y))
            from core.event import run_story
            run_story(story_id, self)
            if action == "both" and npc.alive:
                npc.alive = False
            return
        if action in ("remove", "both"):
            npc.alive = False
            lines.append(f"{npc.name} 撤离了战场。")
        if action != "nothing":
            self._pause("\n".join(lines), cursor=(npc.x, npc.y))

    def _npc_attack(self, npc, victim) -> None:
        npc.auto_equip_for(self.items, abs(npc.x - victim.x) + abs(npc.y - victim.y))
        lines = self._resolve_battle(npc, victim)
        self._append_achievement_lines(lines)
        for line in lines:
            self._log_battle(line)
        self._pause("\n".join(lines), cursor=(victim.x, victim.y))