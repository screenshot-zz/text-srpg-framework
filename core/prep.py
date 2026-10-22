"""整备界面。

出战上限：用 game._map_deploy_capacity()（= min(地图 max_deploy, deploy_points 数量)），
不是全局 max_deploy，避免"选了 N 人但只上 M 人"。

v6：模式选择从开局进入（game._select_mode），教堂替代墓地。
"""
from __future__ import annotations

from typing import Optional

from rich.panel import Panel
from rich.text import Text

from core.ui import STAT_NAMES, _console, read_key, render_stats_panel, unit_info_text


class PrepScreen:
    def __init__(self, game) -> None:
        self.game = game

    # ---------------- 主循环 ----------------

    def run(self) -> bool:
        while True:
            self._render_main()
            k = read_key()
            if k == "1":
                self._show_info()
            elif k == "2":
                self._show_talk()
            elif k == "3":
                self._choose_deploy()
            elif k == "4":
                self._promote()
            elif k == "5":
                self._manage_items()
            elif k == "6":
                self._show_stats()
            elif k == "7":
                self._save_section()
            elif k == "8":
                self._show_church()
            elif k in ("9", "enter"):
                if not any(u.deployed and u.alive for u in self.game.roster):
                    _console.print("[red]至少需要一位出战单位！[/red]", end="")
                    self._pause()
                    continue
                return True
            elif k in ("0", "esc", "quit"):
                return False

    def _pause(self, msg: str = "（按任意键返回）") -> None:
        _console.print(f"[dim]{msg}[/dim]", end=" ")
        read_key()

    def _render_main(self) -> None:
        _console.clear()
        deployed = [u for u in self.game.roster if u.deployed and u.alive]
        max_deploy = self.game._map_deploy_capacity()
        promote_count = sum(1 for u in self.game.roster if u.promote_options)
        body = Text()
        body.append(
            f"金钱：{self.game.gold}G　"
            f"难度：{self.game.difficulty_display_name()}　"      # ═══ v6 ═══
            f"模式：{self.game.mode_display_name()}　　"           # ═══ v6 ═══
            f"仓库物品：{len(self.game.warehouse)} 件\n\n", style="bold",
        )
        body.append("  1. 人物情报\n")
        body.append("  2. 支援对话")
        ready = self._count_support_ready()
        if ready:
            body.append(f"（{ready} 对可升级）", style="green")
        body.append("\n")
        body.append(f"  3. 选择出战（{len(deployed)}/{max_deploy}）\n")
        if promote_count > 0:
            body.append(f"  4. 转职（{promote_count} 人可转）\n", style="yellow")
        else:
            body.append("  4. 转职\n")
        body.append("  5. 整理物品\n")
        body.append("  6. 统计 / 成就\n")
        body.append("  7. 存档（章节开始）\n")

        injured = [u for u in self.game.roster if u.alive
                   and u.stats.get("hp", 0) < u.max_stats.get("hp", 0)]
        dead = [u for u in self.game.roster if not u.alive]
        hints = []
        if injured:
            hints.append(f"{len(injured)}人有伤")
        if dead and self.game._permadeath():
            hints.append(f"{len(dead)}人阵亡")
        hint_str = f"（{'，'.join(hints)}）" if hints else ""
        body.append(f"  8. 教堂{hint_str}\n")

        body.append("  9. 出发\n")
        body.append("  0. 退出到标题\n")
        _console.print(Panel(body, title="整备", border_style="yellow", padding=(0, 2)))

    def _count_support_ready(self) -> int:
        th = self.game._support_thresholds()
        if not th:
            return 0
        alive = [u for u in self.game.roster if u.alive]
        n = 0
        for i, a in enumerate(alive):
            for b in alive[i + 1:]:
                if not self.game._is_support_pair(a.uid, b.uid):
                    continue
                rank = min(a.support_ranks.get(b.uid, 0),
                           b.support_ranks.get(a.uid, 0))
                max_lv = self.game._support_max_level_for(a.uid, b.uid)
                if rank >= max_lv:
                    continue
                need = th[min(rank + 1, len(th)) - 1]
                pts = min(a.support_points.get(b.uid, 0),
                          b.support_points.get(a.uid, 0))
                if pts >= need:
                    n += 1
        return n

    def _show_stats(self) -> None:
        _console.clear()
        render_stats_panel(self.game)
        self._pause()

    def _save_section(self) -> None:
        path = self.game.save_game("section")
        _console.clear()
        if path:
            _console.print(Panel(
                f"已保存章节存档。\n{self.game._save_label('section')}\n{path}",
                title="存档", border_style="green",
            ))
        else:
            _console.print(Panel("存档失败（当前无地图）。", border_style="red"))
        self._pause()

    # ---------------- 教堂 ----------------

    def _show_church(self) -> None:
        cfg = self.game._church_cfg()
        heal_per_hp = int(cfg.get("heal_cost_per_hp", 2))
        heal_min = int(cfg.get("heal_cost_min", 50))
        revive_cost = int(cfg.get("revive_cost", 500))
        blessings = list(cfg.get("blessings") or [])
        permadeath = self.game._permadeath()

        while True:
            _console.clear()
            injured = [u for u in self.game.roster if u.alive
                       and u.stats.get("hp", 0) < u.max_stats.get("hp", 0)]
            total_missing = sum(
                u.max_stats.get("hp", 0) - u.stats.get("hp", 0) for u in injured
            )
            heal_total = total_missing * heal_per_hp
            if injured and heal_total < heal_min:
                heal_total = heal_min
            dead = [u for u in self.game.roster if not u.alive]

            body = Text()
            body.append(f"金钱：{self.game.gold}G　"
                        f"待应用祝福：{len(self.game.pending_blessings)} 种\n\n",
                        style="bold")
            body.append("  1. 治疗全员", style="cyan")
            if injured:
                body.append(f"（{len(injured)}人 · 共 {total_missing}HP · {heal_total}G）\n")
            else:
                body.append("（全员满血）\n", style="dim")
            body.append(f"  2. 接受祝福（{len(blessings)} 种可选）\n", style="cyan")
            body.append("  3. 复活阵亡伙伴", style="cyan")
            if not permadeath:
                body.append("（当前模式自动复活，无需付费）\n", style="dim")
            elif dead:
                body.append(f"（{len(dead)}人 · {revive_cost}G/人）\n")
            else:
                body.append("（无阵亡）\n", style="dim")
            body.append("  0. 返回\n")
            _console.print(Panel(body, title="⛪ 教堂",
                                 border_style="bright_blue", padding=(0, 2)))
            k = read_key()
            if k in ("0", "esc", "quit"):
                return
            if k == "1":
                self._church_heal(injured, heal_total)
            elif k == "2":
                self._church_blessing(blessings)
            elif k == "3" and permadeath:
                self._church_revive(dead, revive_cost)

    def _church_heal(self, injured: list, cost: int) -> None:
        if not injured:
            self._pause("全员满血，无需治疗。")
            return
        if self.game.gold < cost:
            self._pause(f"金钱不足！需要 {cost}G，当前 {self.game.gold}G")
            return
        self.game.gold -= cost
        for u in injured:
            u.stats["hp"] = u.max_stats.get("hp", 0)
        _console.clear()
        body = Text()
        body.append(f"神官为 {len(injured)} 位战友吟诵圣歌，伤口尽数愈合。\n\n",
                    style="bold")
        body.append(f"花费 {cost}G，剩余 {self.game.gold}G\n", style="green")
        _console.print(Panel(body, title="⛪ 治疗", border_style="bright_blue"))
        self._pause()

    def _church_blessing(self, blessings: list) -> None:
        if not blessings:
            self._pause("教堂暂时没有可用的祝福。")
            return
        while True:
            _console.clear()
            body = Text()
            body.append(f"金钱：{self.game.gold}G\n\n", style="bold")
            for i, b in enumerate(blessings, 1):
                selected = any(
                    p.get("status") == b.get("status")
                    for p in self.game.pending_blessings
                )
                mark = "★ " if selected else "  "
                body.append(f"{mark}{i}. {b.get('name', '?')}", style="cyan")
                body.append(f"　{b.get('price', 0)}G\n", style="yellow")
                body.append(f"     {b.get('description', '')}\n", style="dim")
            body.append("  0. 返回\n")
            _console.print(Panel(body, title="⛪ 祝福", border_style="bright_blue"))
            k = read_key()
            if k in ("0", "esc", "quit"):
                return
            if k.isdigit() and 1 <= int(k) <= len(blessings):
                b = blessings[int(k) - 1]
                price = int(b.get("price", 0))
                sid = b.get("status")
                if any(p.get("status") == sid for p in self.game.pending_blessings):
                    self._pause(f"已接受过「{b.get('name')}」祝福，无需重复购买。")
                    return
                if self.game.gold < price:
                    self._pause(f"金钱不足！需要 {price}G，当前 {self.game.gold}G")
                    continue
                self.game.gold -= price
                self.game.pending_blessings.append({
                    "status": sid,
                    "duration": int(b.get("duration", 3)),
                    "name": b.get("name", sid),
                })
                self._pause(f"接受了「{b.get('name')}」祝福，全队将在下一关获得加成。\n"
                            f"花费 {price}G，剩余 {self.game.gold}G")
                return

    def _church_revive(self, dead: list, revive_cost: int) -> None:
        if not dead:
            self._pause("没有阵亡的伙伴。")
            return
        while True:
            _console.clear()
            body = Text()
            body.append(f"金钱：{self.game.gold}G　"
                        f"复活费用：{revive_cost}G/人\n\n", style="bold")
            for i, u in enumerate(dead, 1):
                cls = (u.class_cfg or {}).get("name", "?")
                body.append(f"  {i}. {u.name}（{cls} Lv{u.level}）\n")
            body.append("  0. 返回\n")
            _console.print(Panel(body, title="⛪ 复活", border_style="bright_blue"))
            k = read_key()
            if k in ("0", "esc", "quit"):
                return
            if k.isdigit():
                idx = int(k) - 1
                if 0 <= idx < len(dead):
                    target = dead[idx]
                    if self.game.gold < revive_cost:
                        self._pause(f"金钱不足！需要 {revive_cost}G，"
                                    f"当前 {self.game.gold}G")
                        continue
                    self.game.gold -= revive_cost
                    target.alive = True
                    target.stats["hp"] = 1
                    target.status = []
                    target.status_turns = {}
                    target.deployed = False
                    self._pause(
                        f"{target.name} 苏醒了。\n"
                        f"HP 仅恢复到 1/{target.max_stats.get('hp', 0)}，"
                        f"请再选择「治疗全员」以回满。\n"
                        f"花费 {revive_cost}G，剩余 {self.game.gold}G\n"
                        f"（可在「选择出战」中勾选参战）"
                    )
                    return

    # ---------------- 人物情报 ----------------

    def _show_info(self) -> None:
        while True:
            _console.clear()
            roster = self.game.roster
            if not roster:
                _console.print(Panel("没有可查看的人物。", border_style="yellow"))
                self._pause()
                return
            body = Text()
            for i, u in enumerate(roster, 1):
                status = "✓出战" if u.deployed and u.alive else ("✗阵亡" if not u.alive else "—待命")
                mx = u.max_stats.get("hp", 0)
                cls_name = (u.class_cfg or {}).get("name", "?")
                body.append(f"  {i}. {u.name}（{u.short}）{cls_name} Lv{u.level} ")
                body.append(f"HP {u.stats.get('hp', 0)}/{mx} ", style="bold red")
                body.append(f"{status}\n", style="dim")
            _console.print(Panel(body, title="人物情报", border_style="cyan", padding=(0, 2)))
            _console.print("[dim]数字键查看详情，Q 返回[/dim]")
            k = read_key()
            if k in ("q", "esc"):
                return
            if k.isdigit():
                i = int(k)
                if 1 <= i <= len(roster):
                    _console.clear()
                    _console.print(Panel(
                        unit_info_text(roster[i - 1], self.game),
                        title="人物详情", border_style="cyan", padding=(0, 2),
                    ))
                    self._pause()

    # ---------------- 支援对话 ----------------

    def _show_talk(self) -> None:
        roster = [u for u in self.game.roster if u.alive]
        if len(roster) < 2:
            _console.clear()
            _console.print(Panel("至少需要两位可聊天的伙伴。", border_style="yellow"))
            self._pause()
            return
        a = self._pick_unit(roster, "选择第一位伙伴")
        if a is None:
            return
        b = self._pick_unit([u for u in roster if u is not a], "选择第二位伙伴")
        if b is None:
            return
        support_cfg = (
            self.game.supports.get(f"{a.uid}_{b.uid}")
            or self.game.supports.get(f"{b.uid}_{a.uid}")
        )
        if not support_cfg:
            _console.clear()
            _console.print(Panel(f"{a.name} 和 {b.name} 暂时没什么好聊的。", border_style="yellow"))
            self._pause()
            return
        cur_rank = a.support_ranks.get(b.uid, 0)
        max_level = self._support_max_level(support_cfg)
        if cur_rank >= max_level:
            dialogue = self._support_dialogue(support_cfg, max_level)
            self._play_dialogue(dialogue)
            _console.clear()
            _console.print(Panel(f"{a.name} 与 {b.name} 的支援已达最高等级 {max_level}。",
                                 border_style="dim"))
            self._pause()
            return

        thresholds = self.game._support_thresholds()
        next_rank = cur_rank + 1
        need = thresholds[min(next_rank, len(thresholds)) - 1] if thresholds else 0
        pts = min(a.support_points.get(b.uid, 0),
                  b.support_points.get(a.uid, 0))
        if pts < need:
            _console.clear()
            _console.print(Panel(
                f"{a.name} 与 {b.name} 的羁绊还不够深。\n\n"
                f"好感度：{pts} / {need}\n\n"
                f"（在战场上让两人相邻作战、或对彼此使用物品/杖可积累好感度）",
                title="支援未解锁", border_style="yellow",
            ))
            self._pause()
            return

        new_rank = cur_rank + 1
        a.support_ranks[b.uid] = new_rank
        b.support_ranks[a.uid] = new_rank
        self.game.stats["supports_unlocked"] += 1
        self.game.global_vars["global_stats"]["total_supports_unlocked"] += 1
        dialogue = self._support_dialogue(support_cfg, new_rank)
        self._play_dialogue(dialogue)
        _console.clear()
        body = Text()
        body.append(f"{a.name} 与 {b.name} 的支援等级提升到 {new_rank}！\n\n", style="bold green")
        bonus_table = self.game.global_cfg.get("support_bonus") or {}
        cur_bonus = bonus_table.get(new_rank) or {}
        if cur_bonus:
            parts = [f"{STAT_NAMES.get(k, k)}+{v}" for k, v in cur_bonus.items() if v]
            if parts:
                body.append(f"战斗中相邻时获得：{'、'.join(parts)}\n", style="yellow")
        body.append("（相邻才生效，双向加成）", style="dim")
        new_ach = self.game._check_achievements()
        if new_ach:
            body.append("\n")
            for ach in new_ach:
                body.append(f"▶ 达成成就【{ach['name']}】{ach.get('description', '')}\n",
                            style="bold yellow")
        _console.print(Panel(body, title="支援提升", border_style="green", padding=(0, 2)))
        self._pause()

    def _support_max_level(self, cfg: dict) -> int:
        if "max_level" in cfg:
            return int(cfg["max_level"])
        dialogues = cfg.get("dialogues")
        if isinstance(dialogues, list) and dialogues:
            levels = [int(d.get("level", 0)) for d in dialogues if isinstance(d, dict)]
            if levels:
                return max(levels)
        return 1

    def _support_dialogue(self, cfg: dict, level: int) -> list[dict]:
        dialogues = cfg.get("dialogues")
        if isinstance(dialogues, list):
            for d in dialogues:
                if isinstance(d, dict) and int(d.get("level", 0)) == level:
                    return d.get("dialogue", []) or []
            if dialogues:
                last = dialogues[-1]
                if isinstance(last, dict):
                    return last.get("dialogue", []) or []
        return cfg.get("dialogue", []) or []

    def _play_dialogue(self, dialogue: list[dict]) -> None:
        for line in dialogue:
            _console.clear()
            speaker = line.get("speaker", "旁白")
            text = line.get("text", "")
            _console.print(Panel(text, title=f"【{speaker}】", border_style="magenta", padding=(0, 2)))
            self._pause()

    def _pick_unit(self, units: list, title: str) -> Optional[object]:
        while True:
            _console.clear()
            body = Text()
            for i, u in enumerate(units, 1):
                body.append(f"  {i}. {u.name}（Lv{u.level}）\n")
            _console.print(Panel(body, title=title, border_style="cyan", padding=(0, 2)))
            _console.print("[dim]数字键选择，Q 取消[/dim]")
            k = read_key()
            if k in ("q", "esc"):
                return None
            if k.isdigit():
                i = int(k)
                if 1 <= i <= len(units):
                    return units[i - 1]

    # ---------------- 选择出战 ----------------

    def _choose_deploy(self) -> None:
        max_deploy = self.game._map_deploy_capacity()
        while True:
            _console.clear()
            deployed = [u for u in self.game.roster if u.deployed and u.alive]
            body = Text()
            body.append(f"出战名单（{len(deployed)}/{max_deploy}）\n\n", style="bold")
            for i, u in enumerate(self.game.roster, 1):
                if not u.alive:
                    body.append(f"  {i}. ✗ {u.name}（阵亡）\n", style="dim")
                else:
                    mark = "✓" if u.deployed else " "
                    body.append(f"  {i}. [{mark}] {u.name} Lv{u.level}\n",
                                style="green" if u.deployed else "white")
            _console.print(Panel(body, title="选择出战", border_style="green", padding=(0, 2)))
            _console.print("[dim]数字键切换，Q 返回[/dim]")
            k = read_key()
            if k in ("q", "esc"):
                return
            if k.isdigit():
                i = int(k)
                if 1 <= i <= len(self.game.roster):
                    u = self.game.roster[i - 1]
                    if not u.alive:
                        continue
                    if u.deployed:
                        u.deployed = False
                    else:
                        if len(deployed) >= max_deploy:
                            _console.print(f"[red]本关最多 {max_deploy} 人出战[/red]", end="")
                            self._pause()
                            continue
                        u.deployed = True

    # ---------------- 转职 ----------------

    def _promote(self) -> None:
        candidates = [u for u in self.game.roster if u.promote_options and u.alive]
        if not candidates:
            _console.clear()
            _console.print(Panel(
                "当前没有可转职的单位。\n（等级达标且职业配置了 promote 段才可转）",
                border_style="yellow",
            ))
            self._pause()
            return
        while True:
            _console.clear()
            body = Text()
            body.append("可转职单位：\n\n", style="bold")
            for i, u in enumerate(candidates, 1):
                cur_cls = (u.class_cfg or {}).get("name", "?")
                opts = "、".join(
                    self.game.classes[c].get("name", c) for c in u.promote_options
                    if c in self.game.classes
                )
                seal_note = ""
                if u.promote_item:
                    seal_nm = self.game.items.get(u.promote_item, {}).get("name", u.promote_item)
                    have = (seal_nm in u.items_ids()) or \
                           any((it.get("id") if isinstance(it, dict) else it) == u.promote_item
                               for it in self.game.warehouse)
                    seal_note = f"　[{seal_nm}{'✓' if have else '✗缺'}]"
                body.append(f"  {i}. {u.name}（{cur_cls} Lv{u.level}）→ {opts}{seal_note}\n")
            _console.print(Panel(body, title="转职", border_style="cyan", padding=(0, 2)))
            _console.print("[dim]数字键选择单位，Q 返回[/dim]")
            k = read_key()
            if k in ("q", "esc"):
                return
            if k.isdigit():
                i = int(k)
                if 1 <= i <= len(candidates):
                    if self._promote_unit(candidates[i - 1]):
                        return

    def _promote_unit(self, unit) -> bool:
        opts = [c for c in unit.promote_options if c in self.game.classes]
        if not opts:
            return False
        if len(opts) == 1:
            target = opts[0]
        else:
            target = ""
            while True:
                _console.clear()
                body = Text()
                body.append(f"{unit.name} 的转职路线：\n\n", style="bold")
                for i, cid in enumerate(opts, 1):
                    cfg = self.game.classes[cid]
                    stat_items = [f"{STAT_NAMES.get(k, k)}{v:+d}"
                                  for k, v in (cfg.get("stats") or {}).items() if v]
                    stat_str = "、".join(stat_items) or "无属性变化"
                    body.append(f"  {i}. {cfg.get('name', cid)}（{stat_str}）\n")
                    body.append(f"     {cfg.get('description', '')}\n", style="dim")
                _console.print(Panel(body, title="选择转职职业", border_style="cyan", padding=(0, 2)))
                _console.print("[dim]数字键选择，Q 取消[/dim]")
                k = read_key()
                if k in ("q", "esc"):
                    return False
                if k.isdigit():
                    i = int(k)
                    if 1 <= i <= len(opts):
                        target = opts[i - 1]
                        break
        ok_item, src = self.game._consume_promote_item(unit)
        if not ok_item:
            _console.clear()
            need = self.game.items.get(unit.promote_item, {}).get("name", unit.promote_item)
            _console.print(Panel(
                f"转职需要【{need}】×1。\n身上和仓库里都没有——可以去商店购买，或先完成相关剧情。",
                title="缺少转职道具", border_style="red",
            ))
            self._pause()
            return False
        result = unit.promote(target, self.game.classes)
        if not result:
            _console.clear()
            _console.print(Panel("转职失败（可能等级不足）。", border_style="red"))
            self._pause()
            return False
        self.game.stats["promotions"] += 1
        self.game.global_vars["global_stats"]["total_promotions"] += 1
        _console.clear()
        body = Text()
        body.append(f"{unit.name} 从 {result['old_class']} 转职为 {result['new_class']}！\n\n",
                    style="bold yellow")
        body.append("属性变化：\n")
        if result["diffs"]:
            for stat, d in result["diffs"].items():
                body.append(f"  {STAT_NAMES.get(stat, stat)} {d:+d}\n",
                            style="green" if d > 0 else "red")
        else:
            body.append("  （无变化）\n", style="dim")
        body.append(f"\n等级重置为 Lv{unit.level}。\n", style="dim")
        if result.get("new_skills"):
            names = [self.game.skills.get(s, {}).get("name", s) for s in result["new_skills"]]
            body.append(f"\n习得技能：{'、'.join(names)}\n", style="magenta")
        new_ach = self.game._check_achievements()
        if new_ach:
            body.append("\n")
            for ach in new_ach:
                body.append(f"▶ 达成成就【{ach['name']}】{ach.get('description', '')}\n",
                            style="bold yellow")
        _console.print(Panel(body, title="转职完成", border_style="yellow", padding=(0, 2)))
        self._pause()
        return True

    # ---------------- 整理物品 ----------------

    def _manage_items(self) -> None:
        while True:
            _console.clear()
            body = Text()
            body.append(f"仓库物品：{len(self.game.warehouse)} 件\n\n", style="bold")
            body.append("  1. 单位 → 仓库\n")
            body.append("  2. 仓库 → 单位\n")
            body.append("  3. 单位间交换\n")
            body.append("  0. 返回\n")
            _console.print(Panel(body, title="整理物品", border_style="cyan", padding=(0, 2)))
            k = read_key()
            if k in ("0", "esc", "quit"):
                return
            if k == "1":
                self._item_to_warehouse()
            elif k == "2":
                self._item_from_warehouse()
            elif k == "3":
                self._item_between_units()

    def _pick_item_index(self, unit) -> Optional[int]:
        if not unit.items:
            _console.clear()
            _console.print(Panel("该单位没有物品。", border_style="yellow"))
            self._pause()
            return None
        while True:
            _console.clear()
            body = Text()
            for i, it in enumerate(unit.items, 1):
                iid = it["id"] if isinstance(it, dict) else it
                name = self.game.items.get(iid, {}).get("name", iid)
                if isinstance(it, dict):
                    uses = it.get("uses")
                    if uses is not None:
                        name += f"（剩{uses}）"
                body.append(f"  {i}. {name}\n")
            _console.print(Panel(body, title=f"{unit.name} 的物品", border_style="cyan", padding=(0, 2)))
            _console.print("[dim]数字键选择，Q 取消[/dim]")
            k = read_key()
            if k in ("q", "esc"):
                return None
            if k.isdigit():
                i = int(k)
                if 1 <= i <= len(unit.items):
                    return i - 1

    def _item_to_warehouse(self) -> None:
        unit = self._pick_unit(self.game.roster, "选择单位")
        if unit is None:
            return
        idx = self._pick_item_index(unit)
        if idx is None:
            return
        it = unit.items.pop(idx)
        self.game.warehouse.append(it)
        iid = it["id"] if isinstance(it, dict) else it
        _console.print(f"[green]{unit.name} 的 {self.game.items.get(iid, {}).get('name', iid)} 已存入仓库。[/green]", end="")
        self._pause()

    def _item_from_warehouse(self) -> None:
        if not self.game.warehouse:
            _console.clear()
            _console.print(Panel("仓库是空的。", border_style="yellow"))
            self._pause()
            return
        idx = -1
        while True:
            _console.clear()
            body = Text()
            for i, it in enumerate(self.game.warehouse, 1):
                iid = it["id"] if isinstance(it, dict) else it
                name = self.game.items.get(iid, {}).get("name", iid)
                if isinstance(it, dict):
                    uses = it.get("uses")
                    if uses is not None:
                        name += f"（剩{uses}）"
                body.append(f"  {i}. {name}\n")
            _console.print(Panel(body, title="仓库物品", border_style="cyan", padding=(0, 2)))
            _console.print("[dim]数字键选择，Q 取消[/dim]")
            k = read_key()
            if k in ("q", "esc"):
                return
            if k.isdigit():
                i = int(k)
                if 1 <= i <= len(self.game.warehouse):
                    idx = i - 1
                    break
        unit = self._pick_unit(self.game.roster, "选择接收单位")
        if unit is None:
            return
        it = self.game.warehouse.pop(idx)
        unit.items.append(it)
        iid = it["id"] if isinstance(it, dict) else it
        _console.print(f"[green]{unit.name} 获得了 {self.game.items.get(iid, {}).get('name', iid)}。[/green]", end="")
        self._pause()

    def _item_between_units(self) -> None:
        a = self._pick_unit(self.game.roster, "选择来源单位")
        if a is None:
            return
        idx = self._pick_item_index(a)
        if idx is None:
            return
        b = self._pick_unit([u for u in self.game.roster if u is not a], "选择接收单位")
        if b is None:
            return
        it = a.items.pop(idx)
        b.items.append(it)
        iid = it["id"] if isinstance(it, dict) else it
        _console.print(f"[green]{a.name} 把 {self.game.items.get(iid, {}).get('name', iid)} 交给了 {b.name}。[/green]", end="")
        self._pause()