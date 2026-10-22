"""rich 渲染：三区布局、战斗动画、预测、战斗日志。

v6：新增 show_game_mode_menu；状态栏显示「难度/模式」。
"""
from __future__ import annotations

import os
import sys
import time
import unicodedata

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_console = Console()

STAT_NAMES: dict[str, str] = {
    "hp": "HP", "str": "力量", "def": "守备", "spd": "速度",
    "skl": "技巧", "luk": "幸运", "int": "魔力", "res": "抗性", "mov": "移动",
}

FACTION_STYLE: dict[str, str] = {
    "player": "bold cyan",
    "enemy": "bold red",
    "ally": "bold green",
}

_KEY_MAP = {"w": "up", "s": "down", "a": "left", "d": "right", "q": "esc", "x": "esc"}

_STYLE_MOVE = "on dark_olive_green3"
_STYLE_DANGER = "on dark_red"


def _cell_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _pad(ch: str, target: int = 2) -> str:
    w = _cell_width(ch)
    return ch + " " * max(0, target - w)


def _read_single_key() -> str:
    if not sys.stdin.isatty():
        try:
            raw = input()
        except EOFError:
            raise
        if not raw:
            return "enter"
        return _KEY_MAP.get(raw.strip().lower()[0], raw.strip().lower()[0])

    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            return {b"H": "up", b"P": "down", b"K": "left", b"M": "right"}.get(ch2, "")
        if ch == b"\r":
            return "enter"
        if ch == b"\x1b":
            return "esc"
        try:
            c = ch.decode("utf-8").lower()
        except UnicodeDecodeError:
            return ""
        return _KEY_MAP.get(c, c)

    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            import select
            if select.select([sys.stdin], [], [], 0.02)[0]:
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(ch3, "esc")
            return "esc"
        if ch in ("\r", "\n"):
            return "enter"
        return _KEY_MAP.get(ch.lower(), ch.lower())
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key(prompt: str = "") -> str:
    if prompt:
        _console.print(prompt, end=" ")
    return _read_single_key()


def log(msg: str, style: str = "") -> None:
    _console.print(msg, style=style)


def render_map(game, highlight=None, cursor=None, danger=None, clear: bool = True) -> None:
    highlight = set(highlight or ())
    danger = set(danger or ())
    m = game.map
    if clear:
        _console.clear()

    text = Text()
    for y in range(m.height):
        for x in range(m.width):
            ch = m.char_at(x, y)
            u = m.unit_at(x, y)
            if u is not None and u.alive:
                ch = u.short
                fg = FACTION_STYLE.get(u.faction, "white")
            else:
                fg = str(m.terrain_at(x, y).get("color", "white"))
            styles: list[str] = [fg]
            if cursor == (x, y):
                styles.append("reverse")
            else:
                if (x, y) in danger:
                    styles.append(_STYLE_DANGER)
                if (x, y) in highlight:
                    styles.append(_STYLE_MOVE)
            text.append(_pad(ch, 2), style=" ".join(styles))
        if y < m.height - 1:
            text.append("\n")

    title = f"{m.cfg.get('name', '')}　第 {game.turn} 回合"
    _console.print(Panel(text, title=title, border_style="cyan", padding=(0, 1), expand=False))


def _support_display_text(unit, game) -> str:
    ranks = unit.support_ranks or {}
    if not ranks:
        return ""
    name_map: dict[str, str] = {}
    if game is not None:
        for u in game.roster or []:
            name_map[u.uid] = u.name
    parts: list[str] = []
    for uid, rank in ranks.items():
        if rank <= 0:
            continue
        parts.append(f"{name_map.get(uid, uid)} Lv{rank}")
    return "、".join(parts)


def _items_display_list(unit, game) -> list[str]:
    names: list[str] = []
    for it in unit.items:
        iid = it["id"] if isinstance(it, dict) else it
        name = game.items.get(iid, {}).get("name", iid) if game else iid
        if isinstance(it, dict):
            uses = it.get("uses")
            if uses is not None:
                name += f"（剩{uses}）"
        if iid == getattr(unit, "equipped", None):
            name = "★" + name
        names.append(name)
    return names


def unit_info_text(unit, game=None) -> Text:
    from core.combat import effective_stats, unit_combat_stats
    s, mx = unit.stats, unit.max_stats
    style = FACTION_STYLE.get(unit.faction, "white")
    class_name = (unit.class_cfg or {}).get("name", "?") if unit.class_cfg else "?"
    t = Text()
    t.append(f"{unit.name}", style=style)
    t.append(f"（{class_name}）", style="dim cyan")
    t.append(f"　Lv {unit.level}　EXP {unit.exp}　", style="bold")
    t.append(f"HP {s.get('hp', 0)}/{mx.get('hp', 0)}", style="bold red")

    # ═══ 地形显示：任何单位、任何地形都显示 ═══
    if game is not None and game.map is not None:
        _terrain = game.map.terrain_at(unit.x, unit.y)
        _tname = _terrain.get("name", "")
        _tchar = game.map.char_at(unit.x, unit.y) if game.map.in_bounds(unit.x, unit.y) else ""
        if not _tname:
            _tname = _tchar or "未知"
        _def = _terrain.get("def", 0) or 0
        _res = _terrain.get("res", 0) or 0
        _av = _terrain.get("avoid", 0) or 0
        bonus_parts = []
        if _def:
            bonus_parts.append(f"防+{_def}")
        if _res:
            bonus_parts.append(f"抗+{_res}")
        if _av:
            bonus_parts.append(f"回+{_av}")
        t.append(f"　@ {_tname}", style="cyan bold")
        if bonus_parts:
            t.append(f"（{' '.join(bonus_parts)}）", style="cyan")
    t.append("\n")

    status_cfg = game.status if game else None
    eff = effective_stats(unit, status_cfg)
    attr_parts: list[str] = []
    for k in ("str", "def", "spd", "skl", "luk", "int", "res", "mov"):
        base_v = s.get(k, 0)
        eff_v = eff.get(k, base_v)
        if eff_v != base_v:
            attr_parts.append(f"{STAT_NAMES[k]} {base_v}({eff_v - base_v:+d})")
        else:
            attr_parts.append(f"{STAT_NAMES[k]} {base_v}")
    t.append("　".join(attr_parts), style="white")

    if game is not None:
        cs = unit_combat_stats(unit, game)
        sup = cs.get("support") or {}

        def _stat_fmt(label: str, val: float, bonus: int = 0) -> str:
            if bonus:
                return f"{label} {int(val)}({bonus:+d})"
            return f"{label} {int(val)}"

        t.append(
            "\n" + "　".join([
                _stat_fmt("攻击", cs["attack"]),
                _stat_fmt("防御", cs["defense"]),
                _stat_fmt("命中", cs["hit"], sup.get("hit", 0)),
                _stat_fmt("回避", cs["avoid"], sup.get("avoid", 0)),
                _stat_fmt("必杀", cs["crit"], sup.get("crit", 0)),
            ]),
            style="bold yellow",
        )
    t.append("\n技能：", style="dim")
    _skill_names = []
    for sid in list(unit.skills) + list((unit.class_cfg or {}).get("class_skills") or []):
        _skill_names.append(game.skills.get(sid, {}).get("name", sid) if game else sid)
    t.append("、".join(_skill_names) if _skill_names else "无")
    t.append("\n物品：", style="dim")
    item_names = _items_display_list(unit, game)
    t.append("、".join(item_names) if item_names else "无")
    support_text = _support_display_text(unit, game)
    if support_text:
        t.append("\n支援：", style="dim")
        t.append(support_text, style="cyan")
        sup = (cs.get("support") if game is not None else None) or {}
        if any(sup.values()):
            parts = []
            if sup.get("hit"):
                parts.append(f"命中+{sup['hit']}")
            if sup.get("avoid"):
                parts.append(f"回避+{sup['avoid']}")
            if sup.get("crit"):
                parts.append(f"必杀+{sup['crit']}")
            t.append(f"　● 相邻生效（{' '.join(parts)}）", style="green bold")
        else:
            t.append("（相邻时生效）", style="dim")
    if unit.status:
        t.append("\n状态：", style="dim")
        names = [sid for sid in unit.status]
        if game is not None:
            names = [game.status.get(sid, {}).get("name", sid) for sid in unit.status]
        t.append("、".join(names), style="magenta")
    if unit.description:
        t.append(f"\n{unit.description}", style="italic")
    return t


def show_unit_panel(unit, game=None) -> None:
    _console.print(Panel(
        unit_info_text(unit, game), title="单位信息",
        border_style=FACTION_STYLE.get(unit.faction, "white"),
        padding=(0, 1), expand=False,
    ))


def render_screen(
    game, highlight=None, cursor=None, selected=None, message: str = "", danger=None,
) -> None:
    _console.clear()
    render_map(game, highlight=highlight, cursor=cursor, danger=danger, clear=False)
    u = game.map.unit_at(*cursor) if cursor else None
    if u is None:
        u = selected
    if u is not None:
        _console.print(Panel(
            unit_info_text(u, game), title="单位信息",
            border_style=FACTION_STYLE.get(u.faction, "white"),
            padding=(0, 1), expand=False,
        ))
    else:
        _console.print(Panel(
            "（无单位）", title="单位信息",
            border_style="dim", padding=(0, 1), expand=False,
        ))
    st = Text()
    tag_parts = []
    if hasattr(game, "difficulty_display_name"):
        tag_parts.append(f"难度：{game.difficulty_display_name()}")
    if hasattr(game, "mode_display_name"):
        tag_parts.append(f"模式：{game.mode_display_name()}")
    tag = "　".join(tag_parts) + "　" if tag_parts else ""
    st.append(
        f"金钱：{game.gold}G　{tag}地图：{game.map.cfg.get('name', '')}　第 {game.turn} 回合\n",
        style="bold",
    )
    win_texts, lose_texts = [], []
    if hasattr(game, "_condition_texts"):
        try:
            win_texts, lose_texts = game._condition_texts()
        except Exception:
            pass
    if win_texts:
        st.append("胜利：" + "、".join(win_texts), style="green")
        st.append("　" if lose_texts else "\n")
    if lose_texts:
        st.append("失败：" + "、".join(lose_texts), style="red")
        st.append("\n")
    if message:
        st.append(message, style="yellow")
    _console.print(Panel(
        st, title="状态 / 提示",
        border_style="cyan", padding=(0, 1), expand=False,
    ))


def show_main_menu(title: str = "") -> str:
    title = title or "火焰之纹章·文字战记"
    while True:
        _console.print(Panel(
            f"[bold]{title}[/bold]\n\n"
            "  [cyan]1[/cyan]. 开始游戏\n"
            "  [cyan]2[/cyan]. 读取存档\n"
            "  [cyan]3[/cyan]. 退出",
            title="主菜单", border_style="yellow", padding=(1, 4),
        ))
        c = input("请输入选项：").strip().lower()
        if c in ("1", "start", "开始"):
            return "start"
        if c in ("2", "load", "读档", "继续"):
            return "load"
        if c in ("3", "quit", "q", "退出"):
            return "quit"
        _console.print("[red]无效选项，请输入 1 / 2 / 3[/red]")


def show_difficulty_menu(options: list[dict]) -> str | None:
    """新游戏开局选择难度。返回难度 id；Q 取消返回 None。"""
    while True:
        body = Text()
        for i, o in enumerate(options, 1):
            body.append(f"  {i}. {o.get('name', '?')}\n", style="cyan")
            desc = o.get("description", "")
            if desc:
                body.append(f"     {desc}\n", style="dim")
        _console.print(Panel(
            body, title="选择难度", border_style="yellow",
            padding=(1, 4), expand=False,
        ))
        _console.print("[dim]数字键选择　Q 取消返回主菜单[/dim]")
        c = input("请输入选项：").strip().lower()
        if c in ("q", "esc", "quit", "取消"):
            return None
        if c.isdigit():
            idx = int(c) - 1
            if 0 <= idx < len(options):
                return options[idx]["id"]
        _console.print("[red]无效选项，请输入数字或 Q[/red]")


def show_game_mode_menu(options: list[dict]) -> str | None:
    """新游戏开局选择模式（难度之后）。返回模式 id；Q 取消返回 None。"""
    while True:
        body = Text()
        for i, o in enumerate(options, 1):
            body.append(f"  {i}. {o.get('name', '?')}\n", style="cyan")
            desc = o.get("description", "")
            if desc:
                body.append(f"     {desc}\n", style="dim")
        _console.print(Panel(
            body, title="选择模式", border_style="magenta",
            padding=(1, 4), expand=False,
        ))
        _console.print("[dim]数字键选择　Q 取消返回主菜单[/dim]")
        c = input("请输入选项：").strip().lower()
        if c in ("q", "esc", "quit", "取消"):
            return None
        if c.isdigit():
            idx = int(c) - 1
            if 0 <= idx < len(options):
                return options[idx]["id"]
        _console.print("[red]无效选项，请输入数字或 Q[/red]")


def show_combat_predict(p: dict, title: str = "战斗预测") -> None:
    t = Text()
    t.append(
        f"攻击力 {int(p.get('attack', 0))}　防御 {int(p.get('defense', 0))}　"
        f"预期伤害 {int(p.get('damage', 0))}\n"
    )
    t.append(
        f"命中 {int(p.get('hit_rate', 0))}%　回避 {int(p.get('avoid', 0))}%　"
        f"必杀 {int(p.get('crit_rate', 0))}%",
        style="bold",
    )
    _console.print(Panel(t, title=title, border_style="yellow", padding=(0, 1), expand=False))


def _format_support_line(sup_list: list[dict]) -> str:
    parts: list[str] = []
    for d in sup_list:
        pieces = []
        if d.get("hit"):
            pieces.append(f"命中+{d['hit']}")
        if d.get("avoid"):
            pieces.append(f"回避+{d['avoid']}")
        if d.get("crit"):
            pieces.append(f"必杀+{d['crit']}")
        if pieces:
            parts.append(f"{d['name']} Lv{d['rank']}（{' '.join(pieces)}）")
    return "、".join(parts)


def show_combat_predict_pair(atk, dfn, pair: dict) -> None:
    a = pair.get("atk_side") or {}
    d = pair.get("dfn_side")
    table = Table(
        title=f"{atk.name}（{atk.short}） VS {dfn.name}（{dfn.short}）",
        border_style="yellow", show_header=True, header_style="bold",
        title_style="bold yellow", expand=False, padding=(0, 1),
    )
    table.add_column("", style="dim", justify="left")
    table.add_column(f"【攻】{atk.name}", justify="right", style=FACTION_STYLE.get(atk.faction, "white"))
    table.add_column("—", justify="center", style="dim")
    table.add_column(f"【守】{dfn.name}", justify="left", style=FACTION_STYLE.get(dfn.faction, "white"))

    def fnum(v, suffix: str = "") -> str:
        return "—" if v is None else f"{int(v)}{suffix}"

    table.add_row("HP",
                  f"{atk.stats.get('hp', 0)}/{atk.max_stats.get('hp', 0)}", "",
                  f"{dfn.stats.get('hp', 0)}/{dfn.max_stats.get('hp', 0)}")
    table.add_row("命中", fnum(a.get("hit_rate"), "%"), "",
                  fnum(d.get("hit_rate") if d else None, "%"))
    table.add_row("伤害", fnum(a.get("damage")), "",
                  fnum(d.get("damage") if d else None))
    table.add_row("必杀", fnum(a.get("crit_rate"), "%"), "",
                  fnum(d.get("crit_rate") if d else None, "%"))
    table.add_row("追击",
                  "✓" if pair.get("atk_doubles") else "—", "",
                  "✓" if pair.get("dfn_doubles") else "—")
    if getattr(dfn, "drop_gold", 0) > 0:
        table.add_row("击败可得", "", "", f"{dfn.drop_gold}G")
    _console.print(table)

    note = pair.get("triangle_note", "")
    if note:
        _console.print(f"[bold yellow]武器：{note}[/bold yellow]")
    if pair.get("can_counter") and d is not None:
        _console.print("[dim]守方射程内 → 会反击[/dim]")
    elif not pair.get("can_counter"):
        _console.print("[dim]守方射程外 → 不会反击[/dim]")

    atk_sup = pair.get("atk_support_details") or []
    dfn_sup = pair.get("dfn_support_details") or []
    if atk_sup:
        line = _format_support_line(atk_sup)
        if line:
            _console.print(f"[cyan]支援（攻）：{atk.name} 获 {line}[/cyan]")
    if dfn_sup:
        line = _format_support_line(dfn_sup)
        if line:
            _console.print(f"[cyan]支援（守）：{dfn.name} 获 {line}[/cyan]")


def play_battle_animation(atk, dfn, predict: dict | None = None) -> None:
    atk_char, dfn_char = atk.short, dfn.short
    atk_style = FACTION_STYLE.get(atk.faction, "white")
    dfn_style = FACTION_STYLE.get(dfn.faction, "white")
    width = 20
    total = 6
    title = f"{atk.name} VS {dfn.name}"

    def draw(atk_pos: int, mid: bool = False) -> None:
        _console.clear()
        line = Text()
        if mid:
            line.append(" " * (width // 2 - 1))
            line.append(atk_char, style=atk_style)
            line.append("⚔", style="bold red")
            line.append(dfn_char, style=dfn_style)
        else:
            pos_d = width - atk_pos
            line.append(" " * atk_pos)
            line.append(atk_char, style=atk_style)
            gap = pos_d - atk_pos - 1
            if gap > 0:
                line.append(" " * gap)
            line.append(dfn_char, style=dfn_style)
        _console.print(Panel(line, title=title, border_style="red", padding=(0, 1), expand=False))
        if predict:
            show_combat_predict(predict)

    for i in range(total):
        draw(i * 2)
        time.sleep(0.1)
    draw(0, mid=True)
    time.sleep(0.35)


# ═════════════════════════════════════════════════════════════════
# 统计面板（拆分 tab 独立函数）
# ═════════════════════════════════════════════════════════════════

def render_this_game_stats(game) -> None:
    stats = game.stats
    body = Text()
    body.append("本局统计\n", style="bold cyan")
    body.append(f"  击杀总数    {stats.get('kills', 0)}\n")
    body.append(f"  暴击次数    {stats.get('crits', 0)}\n")
    body.append(f"  落空次数    {stats.get('misses', 0)}\n")
    body.append(f"  单次最大伤害 {stats.get('max_damage', 0)}\n")
    body.append(f"  累计回合    {stats.get('turns', 0)}\n")
    body.append(f"  通关地图    {stats.get('maps_cleared', 0)}\n")
    body.append(f"  本局获得金币 {stats.get('gold_earned', 0)}G\n")
    body.append(f"  使用道具     {stats.get('items_used', 0)}\n")
    body.append(f"  使用技能     {stats.get('skills_used', 0)}\n")
    body.append(f"  支援升级     {stats.get('supports_unlocked', 0)}\n")
    body.append(f"  转职次数     {stats.get('promotions', 0)}\n")
    _console.print(Panel(body, title="统计", border_style="cyan",
                         padding=(0, 2), expand=False))


def render_global_stats(game) -> None:
    gs = (game.global_vars or {}).get("global_stats") or {}
    body2 = Text()
    body2.append("跨存档累计\n", style="bold magenta")
    body2.append(f"  累计击杀    {gs.get('total_kills', 0)}\n")
    body2.append(f"  累计暴击    {gs.get('total_crits', 0)}\n")
    body2.append(f"  累计通关    {gs.get('total_maps_cleared', 0)} 张地图\n")
    body2.append(f"  累计金币    {gs.get('total_gold_earned', 0)}G\n")
    body2.append(f"  累计游戏次数 {gs.get('total_games_played', 0)}\n")
    _console.print(Panel(body2, title="跨存档", border_style="magenta",
                         padding=(0, 2), expand=False))


def render_achievements(game) -> None:
    ach_cfg = game.global_cfg.get("achievements") or {}
    unlocked_ids = set((game.global_vars or {}).get("achievements", []))
    ach_body = Text()
    total = len(ach_cfg)
    done = len(unlocked_ids & set(ach_cfg.keys()))
    ach_body.append(f"已达成 {done}/{total}\n\n", style="bold")
    for aid, cfg in ach_cfg.items():
        name = cfg.get("name", aid)
        desc = cfg.get("description", "")
        if aid in unlocked_ids:
            ach_body.append(f"✓ {name}\n", style="bold green")
            ach_body.append(f"    {desc}\n", style="dim")
        else:
            ach_body.append(f"· {name}\n", style="dim")
            ach_body.append(f"    {desc}\n", style="dim")
    _console.print(Panel(ach_body, title="成就", border_style="yellow",
                         padding=(0, 2), expand=False))


def render_support_panel(game) -> None:
    """好感度进度面板（白名单：只显示 stories.yaml 里配置了的配对）。"""
    alive = [u for u in game.roster if u.alive]
    thresholds = game._support_thresholds()
    pairs: list[dict] = []
    for i, a in enumerate(alive):
        for b in alive[i + 1:]:
            if not game._is_support_pair(a.uid, b.uid):
                continue
            rank = min(a.support_ranks.get(b.uid, 0),
                       b.support_ranks.get(a.uid, 0))
            pts = min(a.support_points.get(b.uid, 0),
                      b.support_points.get(a.uid, 0))
            max_lv = game._support_max_level_for(a.uid, b.uid)
            next_rank = rank + 1
            need = (thresholds[min(next_rank, len(thresholds)) - 1]
                    if thresholds and next_rank <= max_lv else 0)
            can_up = rank < max_lv and pts >= need
            pairs.append({
                "a": a, "b": b, "rank": rank, "pts": pts,
                "max_level": max_lv, "need": need, "can_up": can_up,
            })

    pairs.sort(key=lambda p: (not p["can_up"], -p["rank"], -p["pts"]))

    if not pairs:
        tip = ("在战场上让支援角色相邻作战、互相使用物品/杖可积累好感度。\n"
               "好感度达到门槛后，可在整备「2. 支援对话」升级。")
        if thresholds:
            tip += "\n门槛：" + "、".join(
                f"Lv{i+1}={th}" for i, th in enumerate(thresholds)
            )
        _console.print(Panel(tip, title="好感度", border_style="yellow", expand=False))
        return

    table = Table(title="好感度（白名单配对）", border_style="cyan",
                  expand=False, show_header=True, header_style="bold")
    table.add_column("配对", style="bold")
    table.add_column("等级", justify="center")
    table.add_column("好感度", justify="right")
    table.add_column("状态", justify="left")
    for p in pairs:
        a, b = p["a"], p["b"]
        rank, pts, max_lv, need = p["rank"], p["pts"], p["max_level"], p["need"]
        rank_disp = f"{rank}/{max_lv}" if max_lv else str(rank)
        if rank >= max_lv:
            pts_disp = str(pts)
            status = "[green]已满级[/green]"
        else:
            pts_disp = f"{pts}/{need}"
            status = "[green]可升级✓[/green]" if p["can_up"] else "[dim]未达标[/dim]"
        table.add_row(f"{a.name} ↔ {b.name}", rank_disp, pts_disp, status)
    _console.print(table)


def render_stats_panel(game) -> None:
    """旧接口：一次性打印 3 块（prep.py 的「6. 统计 / 成就」仍用）。"""
    render_this_game_stats(game)
    render_global_stats(game)
    render_achievements(game)


def render_battle_log(game, start: int = 0) -> int:
    logs = game.battle_log
    page_size = 20

    def _draw(s: int) -> None:
        _console.clear()
        if not logs:
            _console.print(Panel("暂无战斗日志。", border_style="yellow"))
            return
        total = len(logs)
        max_start = max(0, total - page_size)
        s = max(0, min(s, max_start))
        end = min(s + page_size, total)
        body = Text()
        for i in range(s, end):
            body.append(f"{logs[i]}\n")
        _console.print(Panel(
            body, title=f"战斗日志（{s + 1}-{end}/{total}）",
            border_style="cyan", padding=(0, 1), expand=False,
        ))
        _console.print("[dim]↑↓ 翻页　任意键返回[/dim]")

    _draw(start)
    if not logs:
        read_key()
        return start
    while True:
        k = read_key()
        if k == "up":
            start = max(0, start - 1)
            _draw(start)
        elif k == "down":
            start += 1
            _draw(start)
        else:
            return start


def show_save_list(saves: list[dict], max_saves: int) -> str:
    while True:
        _console.clear()
        if not saves:
            _console.print(Panel("暂无存档。", border_style="yellow"))
            read_key()
            return "back"
        body = Text()
        for i, s in enumerate(saves, 1):
            mark = "📌 " if s.get("kind") == "section" else "   "
            body.append(f"  {i}. {mark}{s.get('label', '?')}\n")
            body.append(f"     {s.get('timestamp', '')}\n", style="dim")
        body.append(f"\n(共 {len(saves)}/{max_saves} 个存档)\n", style="dim")
        _console.print(Panel(body, title="读取存档", border_style="cyan", padding=(0, 2), expand=False))
        _console.print("[dim]数字键读档　D 删除　Q 返回[/dim]")
        k = read_key()
        if k in ("q", "esc"):
            return "back"
        if k == "d":
            _console.print("[dim]输入要删除的存档编号[/dim]")
            k2 = read_key()
            if k2.isdigit():
                idx = int(k2) - 1
                if 0 <= idx < len(saves):
                    return f"delete:{idx}"
            continue
        if k.isdigit():
            idx = int(k) - 1
            if 0 <= idx < len(saves):
                return f"load:{idx}"