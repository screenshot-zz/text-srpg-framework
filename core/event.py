"""剧情事件：run_story 播放对话并执行动作，run_action 按 type 分发。

v7 新增：change_ai 动作（剧情运行时改变单位 AI 档案或参数）。
v7.3 新增：change_terrain 动作（剧情临时改变地形，支持单格 / 多格 / 恢复）。
"""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from core.formula import ev, _DotDict
from core.unit import Unit

_console = Console()

_ACTION_TYPES = {
    "dialogue", "give_item", "lose_item", "spawn_unit", "remove_unit",
    "set_stat", "add_skill", "add_status", "next_map", "change_faction",
    "set_var", "custom", "change_ai", "change_terrain", "add_drop",
}

def _find_unit(uid: str, game) -> Unit | None:
    for u in game.units:
        if getattr(u, "uid", "") == uid:
            return u
    return None


def run_story(story_id: str, game) -> None:
    story = game.stories.get(story_id)
    if not story:
        _console.print(f"[red]剧情 {story_id} 不存在[/red]")
        return
    if _run_dialogue_list(story.get("dialogue", []) or [], game):
        return
    for act in story.get("actions", []) or []:
        run_action(act, game)


def _run_dialogue_list(lines: list, game) -> bool:
    for line in lines:
        if not isinstance(line, dict):
            continue
        if "choices" in line:
            if _run_choices(line["choices"], game):
                return True
            continue
        speaker = line.get("speaker", "旁白")
        text = line.get("text", "")
        _console.print(Panel(text, title=f"【{speaker}】", border_style="magenta", padding=(0, 1)))
        try:
            input("（按回车继续）")
        except EOFError:
            return False
    return False


def _run_choices(choices: list, game) -> bool:
    if not isinstance(choices, list) or not choices:
        return False
    from core.ui import read_key
    _console.print(Panel("请选择：", border_style="cyan", padding=(0, 1)))
    for i, ch in enumerate(choices, 1):
        _console.print(f"  [cyan]{i}[/cyan]. {ch.get('text', '')}")
    chosen = None
    while True:
        k = read_key()
        if k.isdigit():
            idx = int(k) - 1
            if 0 <= idx < len(choices):
                chosen = choices[idx]
                break
    if chosen is None:
        return False
    for var, val in (chosen.get("set_var") or {}).items():
        game.vars[var] = val
        _console.print(f"[dim]（变量 {var} = {val}）[/dim]")
    for act in (chosen.get("actions") or []):
        run_action(act, game)
    target = chosen.get("story")
    if target and target in game.stories:
        run_story(target, game)
        return True
    return False


def run_action(act: dict, game) -> None:
    if not isinstance(act, dict):
        return
    t = act.get("type")
    if t not in _ACTION_TYPES:
        _console.print(f"[red]未知 action.type：{t}[/red]")
        return
    if t == "dialogue":
        _run_dialogue(act)
    elif t == "give_item":
        _run_give_item(act, game)
    elif t == "lose_item":
        _run_lose_item(act, game)
    elif t == "spawn_unit":
        _run_spawn_unit(act, game)
    elif t == "remove_unit":
        _run_remove_unit(act, game)
    elif t == "set_stat":
        _run_set_stat(act, game)
    elif t == "add_skill":
        _run_add_skill(act, game)
    elif t == "add_status":
        _run_add_status(act, game)
    elif t == "next_map":
        _run_next_map(act, game)
    elif t == "change_faction":
        _run_change_faction(act, game)
    elif t == "set_var":
        _run_set_var(act, game)
    elif t == "custom":
        _run_custom(act, game)
    elif t == "change_ai":
        _run_change_ai(act, game)
    elif t == "change_terrain":
        _run_change_terrain(act, game)
    elif t == "add_drop":
        _run_add_drop(act, game)

def _run_dialogue(act: dict) -> None:
    _console.print(Panel(
        act.get("text", ""), title=f"【{act.get('speaker', '旁白')}】",
        border_style="magenta", padding=(0, 1),
    ))


def _run_give_item(act: dict, game) -> None:
    item = act.get("item")
    if not item or item not in game.items:
        _console.print(f"[red]道具 {item} 未在 items.yaml 中定义[/red]")
        return
    u = _find_unit(act.get("unit"), game)
    if not u:
        _console.print(f"[red]单位 {act.get('unit')} 不存在[/red]")
        return
    u.add_item(item, game.items)
    _console.print(f"[green]{u.name} 获得道具：{game.items[item].get('name', item)}[/green]")


def _run_lose_item(act: dict, game) -> None:
    item = act.get("item")
    u = _find_unit(act.get("unit"), game)
    if not u:
        return
    if u.remove_item_by_id(item):
        _console.print(f"[yellow]{u.name} 失去了 {game.items.get(item, {}).get('name', item)}[/yellow]")


def _run_spawn_unit(act: dict, game) -> None:
    uid = act.get("unit_id")
    x, y = int(act.get("x", 0)), int(act.get("y", 0))
    faction = act.get("faction", "enemy")
    if uid not in game.units_cfg:
        _console.print(f"[red]units.yaml 中缺少单位：{uid}[/red]")
        return
    if game.map is None:
        _console.print("[red]当前无地图，spawn_unit 无法执行（开局脚本不适用）[/red]")
        return
    if game.map.unit_at(x, y) is not None:
        _console.print(f"[red]({x},{y}) 已有单位，无法生成 {uid}[/red]")
        return
    unit = Unit.from_cfg(
        uid, game.units_cfg[uid], game.classes, faction, x, y,
        game.ai_profiles, items_cfg=game.items,
    )
    game._apply_difficulty_to_unit(unit)
    game.units.append(unit)
    game.map.units = game.units
    game._had_enemies = game._had_enemies or (faction == "enemy")
    _console.print(f"[red]{unit.name} 在 ({x},{y}) 出现了！[/red]")


def _run_remove_unit(act: dict, game) -> None:
    u = _find_unit(act.get("unit"), game)
    if not u:
        return
    u.alive = False
    _console.print(f"[yellow]{u.name} 离场了。[/yellow]")


def _run_set_stat(act: dict, game) -> None:
    uid, stat = act.get("unit"), act.get("stat")
    expr = act.get("formula", "0")
    u = _find_unit(uid, game)
    if not u:
        _console.print(f"[red]单位 {uid} 不存在[/red]")
        return
    ctx = {
        "hp": u.stats.get("hp", 0), "max_hp": u.max_stats.get("hp", 0),
        "str": u.stats.get("str", 0), "def": u.stats.get("def", 0),
        "spd": u.stats.get("spd", 0), "skl": u.stats.get("skl", 0),
        "luk": u.stats.get("luk", 0), "int": u.stats.get("int", 0),
        "res": u.stats.get("res", 0), "mov": u.stats.get("mov", 0),
        "level": u.level, "exp": u.exp,
        "vars": _DotDict(game.vars),
        **{f"var_{k}": v for k, v in game.vars.items()},
    }
    val = int(ev(str(expr), ctx))
    if stat == "exp":
        u.exp = val
    elif stat == "level":
        u.level = val
    else:
        u.stats[stat] = val
    _console.print(f"[green]{u.name} 的 {stat} 变为 {val}[/green]")


def _run_add_skill(act: dict, game) -> None:
    skill = act.get("skill")
    u = _find_unit(act.get("unit"), game)
    if not u:
        return
    if skill and skill not in u.skills:
        u.skills.append(skill)
        _console.print(
            f"[magenta]{u.name} 习得技能：{game.skills.get(skill, {}).get('name', skill)}[/magenta]"
        )


def _run_add_status(act: dict, game) -> None:
    sid = act.get("status")
    u = _find_unit(act.get("unit"), game)
    if not u:
        return
    cfg = game.status.get(sid, {})
    if not cfg:
        _console.print(f"[red]status.yaml 缺少状态：{sid}[/red]")
        return
    if sid not in u.status:
        u.status.append(sid)
    u.status_turns[sid] = int(cfg.get("duration", 1))
    _console.print(f"[yellow]{u.name} 陷入{cfg.get('name', sid)}状态！[/yellow]")


def _run_next_map(act: dict, game) -> None:
    map_id = act.get("map")
    if not map_id or map_id not in game.maps:
        _console.print(f"[red]地图 {map_id} 不存在[/red]")
        return
    game.load_map(map_id, defer_start=True)
    if not game._show_prep():
        game.state = "title"
        return
    game._fire_start_events()


def _run_change_faction(act: dict, game) -> None:
    """改变单位阵营。

    enemy → player：加入 roster（可跨章节出战）；若本图出战名额还有，
                     自动 deployed=True；否则留待整备手动勾选。
    enemy → ally：仅场上阵营改变，不进 roster。
    """
    uid = act.get("unit")
    faction = act.get("faction", "ally")
    if faction not in ("player", "ally", "enemy"):
        _console.print(f"[red]无效阵营：{faction}[/red]")
        return
    u = _find_unit(uid, game)
    if not u:
        _console.print(f"[red]单位 {uid} 不存在[/red]")
        return
    old = u.faction
    if old == faction:
        return
    u.faction = faction
    auto_deployed = False
    if faction == "player" and old != "player":
        u.deployable = True
        u.is_lord = False
        u.ai = "aggressive"
        if u.stat_bonus:
            u.stat_bonus = {}
        u.growth = {
            k: u.base_growth.get(k, 0) + u.class_growth.get(k, 0)
            for k in set(u.base_growth) | set(u.class_growth)
        }
        u._recompute_stats()
        deployed_count = sum(
            1 for x in game.roster if x.deployed and x.alive and x is not u
        )
        if deployed_count < game._map_deploy_capacity():
            u.deployed = True
            auto_deployed = True
        else:
            u.deployed = False
        if u not in game.roster:
            game.roster.append(u)
    tail = ""
    if faction == "player":
        tail = "（加入我军"
        if auto_deployed:
            tail += "，已加入出战）"
        else:
            tail += "，请到整备界面选择出战）"
    _console.print(f"[green]{u.name} 从 {old} 变为 {faction}{tail}[/green]")


def _run_set_var(act: dict, game) -> None:
    var = act.get("var")
    if not var:
        return
    if "value_expr" in act:
        ctx = {
            "vars": _DotDict(game.vars),
            **{f"var_{k}": v for k, v in game.vars.items()},
        }
        val = ev(str(act["value_expr"]), ctx)
        try:
            val = int(val) if float(val).is_integer() else float(val)
        except (TypeError, ValueError):
            pass
    else:
        val = act.get("value", 0)
    game.vars[var] = val
    _console.print(f"[green]变量 {var} = {val}[/green]")


def _run_custom(act: dict, game) -> None:
    """自定义动作：执行 act['code'] 中的 Python 代码。

    ⚠️ 安全警告：使用 exec() 执行 stories.yaml 中的任意代码。
    仅应加载本地可信的配置文件。
    """
    code = act.get("code", "")
    if not code:
        return
    ns: dict = {"game": game}
    try:
        exec(code, {"__builtins__": __builtins__}, ns)  # noqa: S102
    except Exception as e:  # noqa: BLE001
        _console.print(f"[red]custom 动作执行失败：{e}[/red]")


def _run_change_ai(act: dict, game) -> None:
    """改变单位的 AI 档案或参数。

    两种写法（可组合）：
        1. ai: profile_id          切换整个档案（覆盖当前 ai_params）
        2. ai_params: {k: v}       覆盖单个参数（保留其他）

    示例：
        - {type: change_ai, unit: thief_1, ai: aggressive}
        - {type: change_ai, unit: ally_1,
           ai_params: {move_mode: follow, follow_target: hero}}
    """
    uid = act.get("unit")
    u = _find_unit(uid, game)
    if not u:
        _console.print(f"[red]单位 {uid} 不存在[/red]")
        return

    changed = False
    profile_id = act.get("ai")
    if profile_id:
        profile = dict(game.ai_profiles.get(profile_id, {}))
        if not profile:
            _console.print(f"[red]ai_profiles 缺少 {profile_id}[/red]")
            return
        profile.pop("name", None)  # name 是展示用，不放进 ai_params
        u.ai = profile_id
        u.ai_params = profile
        changed = True

    overrides = act.get("ai_params") or {}
    if overrides:
        for k, v in overrides.items():
            u.ai_params[k] = v
        changed = True

    if changed:
        mode = u.ai_params.get("move_mode", "?")
        _console.print(f"[yellow]{u.name} 的行动模式变为「{mode}」。[/yellow]")


def _run_change_terrain(act: dict, game) -> None:
    """剧情临时改变地形。

    三种写法：
        单格：{type: change_terrain, x: 5, y: 5, char: "桥"}
        多格：{type: change_terrain, tiles: [{x: 5, y: 5, char: "桥"}, {x: 6, y: 5, char: "桥"}]}
        恢复：{type: change_terrain, x: 5, y: 5, restore: true}

    ⚠ 变更只改 runtime 的 map.grid，不写回 yaml。
       读档 / 切图会恢复成配置里的原始地形（"临时"语义）。
       原始地形记录在 game.vars["_terrain_original"] 里，供 restore 用。
    """
    if game.map is None:
        _console.print("[red]当前无地图，change_terrain 无法执行[/red]")
        return

    # 收集要改的格子：(x, y, char|None, restore)
    tiles: list[tuple[int, int, str | None, bool]] = []
    if "tiles" in act:
        for t in (act.get("tiles") or []):
            if not isinstance(t, dict):
                continue
            tiles.append((
                int(t.get("x", -1)), int(t.get("y", -1)),
                t.get("char"), bool(t.get("restore", False)),
            ))
    elif "x" in act and "y" in act:
        tiles.append((
            int(act.get("x", -1)), int(act.get("y", -1)),
            act.get("char"), bool(act.get("restore", False)),
        ))

    if not tiles:
        _console.print("[red]change_terrain 缺少坐标（x/y 或 tiles）[/red]")
        return

    original = game.vars.setdefault("_terrain_original", {})
    lines: list[str] = []

    for x, y, char, restore in tiles:
        if not game.map.in_bounds(x, y):
            lines.append(f"[red]({x},{y}) 越界，跳过[/red]")
            continue
        key = f"{x},{y}"
        old_char = game.map.char_at(x, y)

        if restore:
            if key not in original:
                lines.append(f"[dim]({x},{y}) 无原始记录，无法恢复[/dim]")
                continue
            new_char = original.pop(key)
        else:
            if char is None:
                lines.append(f"[red]({x},{y}) 缺少 char 参数[/red]")
                continue
            # 首次改这格时，记录原始字符
            if key not in original:
                original[key] = old_char
            new_char = str(char)

        game.map.grid[y][x] = new_char
        new_name = game.map.terrain_at(x, y).get("name", new_char)
        lines.append(f"[cyan]地形变化：({x},{y}) {old_char} → {new_char}（{new_name}）[/cyan]")

    if lines:
        _console.print("\n".join(lines))



def _run_add_drop(act: dict, game) -> None:
    """给单位增加掉落物（v7.4c）。

    写法：
        - {type: add_drop, unit: enemy_boss, item: master_seal, chance: 100}
        - {type: add_drop, unit: enemy_boss, item: killer_sword, chance: 50}
        - {type: add_drop, unit: enemy_boss, item: vulnerary}   # chance 默认 100

    chance: 0-100，100 = 必掉。
    掉落物在击杀后进仓库（warehouse），和 drop_item 一样。
    """
    uid = act.get("unit")
    u = _find_unit(uid, game)
    if not u:
        _console.print(f"[red]单位 {uid} 不存在[/red]")
        return
    iid = act.get("item")
    if not iid or iid not in game.items:
        _console.print(f"[red]道具 {iid} 未在 items.yaml 中定义[/red]")
        return
    chance = int(act.get("chance", 100))
    chance = max(0, min(100, chance))
    u.drop_items.append({"id": iid, "chance": chance})
    name = game.items[iid].get("name", iid)
    _console.print(f"[green]{u.name} 的掉落列表增加了 {name}（{chance}%）[/green]")