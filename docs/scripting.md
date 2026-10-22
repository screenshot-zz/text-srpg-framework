# 脚本编写指南

本文档说明如何编写剧情脚本：**变量**、**动作**、**触发条件**、**条件表达式**。

所有脚本写在 `config/stories.yaml` 和 `config/maps/*.yaml` 里，**不需要改 Python**。

> **版本说明**：本文基于 v7.4 标准版。如果你的项目还没实现某个字段或动作，参考对应章节的"代码位置"补进引擎即可。

---

## 目录

1. [变量系统](#1-变量系统)
2. [动作全表](#2-动作全表)
3. [触发条件](#3-触发条件)
4. [条件表达式可用字段](#4-条件表达式可用字段)
5. [完整示例](#5-完整示例)
6. [常见错误](#6-常见错误)

---

## 1. 变量系统

变量存在 `game.vars`（一个 dict），随存档保存，新游戏清空。

### 1.1 写变量：`set_var`

```yaml
actions:
  # 静态值
  - {type: set_var, var: scout_met, value: 1}
  - {type: set_var, var: hero_name, value: "艾伦"}

  # 表达式（走公式引擎 ev）
  - {type: set_var, var: scout_lean, value_expr: "vars.scout_lean + 1"}
  - {type: set_var, var: flag, value_expr: "vars.step >= 3 and vars.boss_dead == 1"}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `var` | ✅ | 变量名（字符串，建议小写下划线） |
| `value` | 二选一 | 静态值（数字 / 字符串 / 布尔） |
| `value_expr` | 二选一 | 表达式，走 `ev()`，可用 `vars.xxx` 访问其他变量 |

**优先级**：同时写 `value` 和 `value_expr` 时，`value_expr` 生效。

### 1.2 读变量：在 condition 里

两种写法等价：

```yaml
condition: "vars.scout_met == 1"      # 点访问，缺失键返回 0
condition: "var_scout_met == 1"       # 下划线写法
```

推荐 `vars.xxx`，语义更清晰，缺失键自动按 0 处理不会报错。

### 1.3 变量的典型用途

| 用途 | 示例 |
| --- | --- |
| 分支标记 | `var_choice == 1` / `var_choice == 2` |
| 进度计数 | `var_scout_lean >= 2` |
| 一次性标记 | `var_village_visited == 1` |
| 剧情链 | 剧情 A 设 `var_step = 1` → 剧情 B 检查 `var_step == 1` |

---

## 2. 动作全表

动作写在 `actions:` 列表里，按顺序执行。共 15 种（以 `core/event.py::_ACTION_TYPES` 为准）。

### 2.1 dialogue — 单条对话

```yaml
- {type: dialogue, speaker: "旁白", text: "风起了。"}
```

| 字段 | 说明 |
| --- | --- |
| `speaker` | 说话者（默认"旁白"） |
| `text` | 台词 |

不暂停，直接打印。适合在 `actions` 中间插旁白。

### 2.2 give_item — 给道具

```yaml
- {type: give_item, unit: hero, item: vulnerary}
```

| 字段 | 说明 |
| --- | --- |
| `unit` | 单位 uid（必须在场上或 roster 里） |
| `item` | 道具 id（必须在 `items.yaml` 里） |

### 2.3 lose_item — 没收道具

```yaml
- {type: lose_item, unit: hero, item: family_letter}
```

按 id 移除第一个匹配项。没有则静默跳过。

### 2.4 spawn_unit — 生成单位

```yaml
- {type: spawn_unit, unit_id: enemy2, x: 13, y: 3, faction: enemy}
```

| 字段 | 说明 |
| --- | --- |
| `unit_id` | `units.yaml` 里的 uid |
| `x` / `y` | 坐标（必须是空地，有单位会拒绝） |
| `faction` | enemy / player / ally |

- 自动应用难度加成
- 会更新 `_had_enemies`，让 `all_enemy_dead` 判定有效

### 2.5 remove_unit — 移除单位

```yaml
- {type: remove_unit, unit: ally_soldier}
```

只设 `alive = False`，不从 `self.units` 删。渲染时跳过，存档保存。

### 2.6 set_stat — 改属性

```yaml
- {type: set_stat, unit: hero, stat: exp, formula: "exp + 50"}
- {type: set_stat, unit: hero, stat: str, formula: "str + 2"}
- {type: set_stat, unit: hero, stat: level, formula: "10"}
```

| 字段 | 说明 |
| --- | --- |
| `unit` | 单位 uid |
| `stat` | 属性名（hp / str / def / spd / skl / luk / int / res / mov / exp / level） |
| `formula` | 表达式（不能写 `=`，只能写表达式） |

**注意**：改 `hp` 是改当前 HP，不改 max。想永久加 HP 上限需改 `base_stats`，当前无直接动作。

### 2.7 add_skill — 学技能

```yaml
- {type: add_skill, unit: hero, skill: swordmaster_mastery}
```

已学会的不会重复加。被动技能立即生效。

### 2.8 add_status — 加状态

```yaml
- {type: add_status, unit: hero, status: poison}
```

持续时间读 `status.yaml::duration`。已有该状态会重置持续回合。

### 2.9 next_map — 切地图

```yaml
- {type: next_map, map: map2}
```

切图后会强制进整备界面，整备取消（Q）回标题。

流程：`load_map(defer_start=True)` → `_show_prep()` → `_fire_start_events()`

### 2.10 change_faction — 改阵营

```yaml
- {type: change_faction, unit: enemy_brigand, faction: player}
```

`enemy → player`：

- 加入 roster（可跨章节出战）
- 清空 `stat_bonus`（难度加成不跟着走）
- 重算 `growth`
- 出战名额够则自动 `deployed = True`

`enemy → ally`：只改场上阵营，不进 roster。

### 2.11 set_var — 设变量

见 [1.1 写变量](#11-写变量set_var)。

### 2.12 custom — 任意代码

```yaml
- type: custom
  code: |
    game.gold = game.gold // 2
    for u in game.units:
        if u.faction == 'enemy':
            u.stats['hp'] = min(u.stats['hp'], 10)
```

直接 `exec` Python 代码，`game` 是唯一命名空间变量。

> ⚠️ **安全风险**：`stories.yaml` 是本地文件，可信；别从网络加载。

常用示例：

```yaml
# 给所有敌人减半 HP
- {type: custom, code: "for u in game.units:\n    if u.faction == 'enemy':\n        u.stats['hp'] = u.stats['hp'] // 2"}

# 金钱翻倍
- {type: custom, code: "game.gold *= 2"}

# 直接改地图某格（比 change_terrain 更暴力）
- {type: custom, code: "game.map.grid[5][5] = '桥'"}

# 解除所有玩家单位的中毒（替代 remove_status）
- type: custom
  code: |
    for u in game.units:
        if u.alive and u.faction == 'player' and 'poison' in u.status:
            u.status.remove('poison')
            u.status_turns.pop('poison', None)
```

### 2.13 change_ai — 改 AI

切换整个档案：

```yaml
- {type: change_ai, unit: thief_1, ai: aggressive}
```

只覆盖单个参数：

```yaml
- type: change_ai
  unit: ally_1
  ai_params: {move_mode: follow, follow_target: hero}
```

组合（下令跑向某点）：

```yaml
- type: change_ai
  unit: enemy_thief
  ai_params:
    move_mode: "move_to"
    move_to: {x: 20, y: 10}
    reached_action: "story"
    reached_story: "thief_arrive"
    can_attack: false
```

> ⚠️ **关键**：改 `move_mode` 必须显式写 `move_mode: "move_to"`，只写 `move_to: {x,y}` 不生效。

### 2.14 change_terrain — 改地形

单格：

```yaml
- {type: change_terrain, x: 5, y: 5, char: "桥"}
```

多格：

```yaml
- type: change_terrain
  tiles:
    - {x: 8,  y: 15, char: "桥"}
    - {x: 9,  y: 15, char: "桥"}
    - {x: 10, y: 15, char: "桥"}
```

恢复：

```yaml
- {type: change_terrain, x: 5, y: 5, restore: true}
```

| 字段 | 说明 |
| --- | --- |
| `x` / `y` | 单格坐标（和 `tiles` 二选一） |
| `char` | 目标地形字符（`global.yaml::terrain` 里配的） |
| `tiles` | 多格列表 |
| `restore` | `true` = 恢复原始字符（要求之前改过） |

> ⚠️ 只改 runtime 的 `map.grid`，读档/切图会恢复成 YAML 原始地形。原始字符记录在 `game.vars["_terrain_original"]`。

### 2.15 add_drop — 加掉落物

```yaml
- {type: add_drop, unit: enemy_boss, item: master_seal, chance: 100}
- {type: add_drop, unit: enemy_boss, item: killer_sword, chance: 50}
- {type: add_drop, unit: enemy_boss, item: vulnerary}   # chance 默认 100
```

| 字段 | 说明 |
| --- | --- |
| `unit` | 单位 uid |
| `item` | 道具 id |
| `chance` | 0-100，100 = 必掉（默认 100） |

效果：追加到 `unit.drop_items`，击杀后按几率入仓库。

### 动作速查表

| # | type | 一句话 |
| --- | --- | --- |
| 1 | dialogue | 打印对话 |
| 2 | give_item | 给道具 |
| 3 | lose_item | 没收道具 |
| 4 | spawn_unit | 刷单位 |
| 5 | remove_unit | 移除单位 |
| 6 | set_stat | 改属性 |
| 7 | add_skill | 学技能 |
| 8 | add_status | 加状态 |
| 9 | next_map | 切地图 |
| 10 | change_faction | 改阵营 |
| 11 | set_var | 设变量 |
| 12 | custom | 任意代码 |
| 13 | change_ai | 改 AI |
| 14 | change_terrain | 改地形 |
| 15 | add_drop | 加掉落 |

---

## 3. 触发条件

### 3.1 地图事件（`map.yaml::events`）

```yaml
events:
  - id: intro
    trigger: start
    story: map1_intro
```

| trigger | 触发时机 | 支持 condition | 支持 result |
| --- | --- | --- | --- |
| `start` | 开局（load_map 后） | ❌ | ❌ |
| `enter` | 单位移动进入某格 | ✅ | ❌ |
| `interact` | 单位站在某格，按「访问」 | ✅ | ❌ |
| `reach_point` | 单位回合结束站在某格 | ❌ | ✅ |
| `all_enemy_dead` | 敌人全灭 | ❌ | ✅ |
| `all_player_dead` | 我方全灭 | ❌ | ✅ |
| `lord_dead` | 主角阵亡 | ❌ | ✅ |
| `boss_killed` | 指定 boss 被击杀 | ❌ | ✅ |
| `turn_limit` | 回合数超过 N | ❌ | ✅ |

字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 事件 id（once 去重用） |
| `trigger` | 触发类型 |
| `x` / `y` | 坐标（enter / interact / reach_point 用） |
| `story` | 触发后播的剧情 id |
| `condition` | 条件表达式（enter / interact 支持） |
| `result` | win / lose（胜负判定用） |
| `text` | 胜负条件显示文本 |
| `once` | 是否只触发一次（默认 true） |
| `boss` | boss_killed 用，指定 boss uid |
| `turn` | turn_limit 用，回合数 |
| `unit` / `faction` | reach_point 用，过滤单位 |

> **once 的粒度**：`map.yaml::events` 的 once 是**全局一次**（整个存档只触发一次），不是每个单位一次。

### 3.2 地形触发器（`global.yaml::terrain::triggers`）

```yaml
"泉":
  triggers:
    - {on: turn_start, heal: 5}
    - {on: turn_end, damage: 2}
    - {on: turn_start, story: altar_blessing, once: true,
       condition: "unit_uid == 'hero'"}
```

| on | 触发时机 |
| --- | --- |
| `turn_start` | 每回合开始（玩家回合前） |
| `turn_end` | 每回合结束（状态结算后、胜负判定前） |

每个 trigger 支持：

| 字段 | 说明 |
| --- | --- |
| `on` | turn_start / turn_end（必填） |
| `heal` | 回 HP（int） |
| `damage` | 扣 HP（int，扣死判死） |
| `story` | 播剧情 |
| `actions` | 执行事件动作（复用 `event.py::run_action`） |
| `once` | 每个单位只触发一次（per-unit 粒度） |
| `condition` | 条件表达式 |

> **once 的粒度**：地形 triggers 的 once 是**每个单位独立**（hero 触发过，mage_girl 还能触发）。判定 key 是 `(unit_uid, 地形字符, trigger_index)`。

### 3.3 战斗对话（`stories.yaml::talks`）

```yaml
talks:
  scout_reunion:
    name: "重逢的吊坠"
    units: [ally_soldier, enemy_brigand]
    timing: pre
    condition: "atk_uid == 'ally_soldier'"
    once: true
    dialogue: [...]
    actions: [...]
```

| 字段 | 说明 |
| --- | --- |
| `units` | 两个交战单位 uid，无序匹配 |
| `timing` | pre（战前）/ post（战后） |
| `condition` | 条件表达式 |
| `once` | 是否只播一次（默认 true） |
| `dialogue` | 对话列表 |
| `actions` | 播完后执行的动作 |

---

## 4. 条件表达式可用字段

### 4.1 地图事件 / 地形触发器（`_event_condition_ctx`）

| 类别 | 字段 | 类型 | 说明 |
| --- | --- | --- | --- |
| 全局 | `turn` | int | 当前回合 |
| | `gold` | int | 金钱 |
| | `enemy_count` | int | 存活敌人数 |
| | `ally_count` | int | 存活友军数 |
| | `kills` | int | 本局击杀数 |
| 单位身份 | `unit_uid` | str | 单位 uid（如 hero） |
| | `unit_name` | str | 显示名 |
| | `unit_faction` | str | player / enemy / ally |
| | `unit_class` | str | 职业 id |
| | `unit_alive` | 0/1 | 是否存活 |
| | `unit_moved` | 0/1 | 本回合是否移动过 |
| 单位数值 | `unit_hp` | int | 当前 HP |
| | `unit_max_hp` | int | 最大 HP |
| | `unit_level` | int | 等级 |
| | `unit_exp` | int | 经验 |
| 单位状态 | `unit_has_poison` | 0/1 | 是否中毒 |
| | `unit_has_stun` | 0/1 | 是否眩晕 |
| | `unit_status_count` | int | 状态数量 |
| 地形 | `unit_terrain` | str | 脚下地形字符（如 村） |
| | `unit_terrain_name` | str | 脚下地形名（如 村庄） |
| 剧情变量 | `vars.xxx` | any | 点访问，缺失为 0 |
| | `var_xxx` | any | 下划线写法 |

### 4.2 战斗对话（`_battle_talk_ctx`）

| 类别 | 字段 |
| --- | --- |
| 全局 | `turn` / `gold` / `vars.xxx` / `var_xxx` |
| 攻方 | `atk_uid` / `atk_hp` / `atk_max_hp` / `atk_level` / `atk_str` / `atk_spd` / `atk_skl` / `atk_luk` / `atk_def` / `atk_res` / `atk_int` |
| 守方 | `dfn_uid` / `dfn_hp` / `dfn_max_hp` / `dfn_level` / `dfn_str` / `dfn_spd` / `dfn_skl` / `dfn_luk` / `dfn_def` / `dfn_res` / `dfn_int` |

### 4.3 道具 / 技能条件（`_item_condition_ctx`）

| 字段 | 说明 |
| --- | --- |
| `hp` / `max_hp` | 目标当前 HP / 最大 HP |
| `user_hp` / `user_max_hp` | 使用者 HP |
| `target_hp` / `target_max_hp` | 目标 HP |
| `target_uid` | 目标 uid |
| `target_can_recruit` | 目标是否可招募（0/1） |
| `target_is_enemy` | 目标是敌人（0/1） |
| `target_is_ally` | 目标是友军（0/1） |
| `has_poison` | 目标中毒（0/1） |
| `in_range` | 目标在射程内（0/1） |
| `vars.xxx` / `var_xxx` | 剧情变量 |

### 4.4 公式引擎支持的语法

`ev()` 走 `simpleeval`，支持：

- **算术**：`+ - * / // % **`
- **比较**：`== != > < >= <=`
- **逻辑**：`and` / `or` / `not`
- **成员**：`in` / `not in`
- **三元**：`a if cond else b`
- **函数**：`max()` / `min()` / `abs()` / `round()`
- **列表/字典字面量**：`[1, 2]` / `{'a': 1}`

**不支持**：赋值、函数定义、import、属性赋值。

---

## 5. 完整示例

### 5.1 村庄：访问一次给道具，再访问只播对话

```yaml
# map1.yaml
events:
  - {id: village, trigger: interact, x: 14, y: 4,
     story: village_gift, condition: "unit_terrain == '村'"}
```

```yaml
# stories.yaml
village_gift:
  dialogue:
    - {speaker: "村民", text: "谢谢你，冒险者。"}
  actions:
    - {type: set_var, var: village_visited, value: 1}
    - {type: give_item, unit: hero, item: vulnerary}
```

第二次访问：`once` 默认 true，事件不再触发。想"第二次播不同对话"，需要两条事件 + condition 互斥（见 5.2）。

### 5.2 分支：访问过一次后播不同对话

```yaml
events:
  - {id: village_first, trigger: interact, x: 14, y: 4,
     story: village_gift, condition: "var_village_visited == 0 and unit_terrain == '村'"}
  - {id: village_again, trigger: interact, x: 14, y: 4,
     story: village_again_story, condition: "var_village_visited == 1 and unit_terrain == '村'",
     once: false}
```

`village_gift` 的 `actions` 里设 `var_village_visited = 1`。第二次访问走 `village_again`，`once: false` 让它每次都能触发。

### 5.3 盗贼逃跑：下令 → 到点剧情 → 消失

```yaml
# map1.yaml
units:
  - {id: enemy_thief, x: 5, y: 5, faction: enemy, ai: move_to,
     move_to: {x: 15, y: 5}, reached_action: "story",
     reached_story: "thief_reach_chest", can_attack: false}

events:
  - {id: thief_alert, trigger: enter, x: 5, y: 5, story: thief_alert_story}
```

```yaml
# stories.yaml
thief_alert_story:
  dialogue:
    - {speaker: "盗贼斥候", text: "被发现了！撤！"}
  actions:
    - {type: change_ai, unit: enemy_thief,
       ai_params: {move_mode: "move_to", move_to: {x: 30, y: 0},
                   reached_action: "story", reached_story: "thief_escape"}}

thief_reach_chest:
  dialogue:
    - {speaker: "盗贼斥候", text: "宝箱到手！"}
  actions:
    - {type: change_ai, unit: enemy_thief,
       ai_params: {move_to: {x: 30, y: 0}, reached_story: "thief_escape"}}

thief_escape:
  dialogue:
    - {speaker: "盗贼斥候", text: "追不上我吧！"}
  actions:
    - {type: remove_unit, unit: enemy_thief}
```

流程：

1. 玩家进入 (5,5) → 触发 `thief_alert` → 下令改目标到 (30,0)
2. 盗贼走到 (15,5) → 触发 `thief_reach_chest` → 继续往 (30,0) 走
3. 盗贼走到 (30,0) → 触发 `thief_escape` → 消失

> **关键**：`remove_unit` 必须放在**到达后**的剧情里，不能放在"下令"剧情里（否则命令作废）。

### 5.4 Boss 守城：boss 占格，打死才能占

```yaml
# map1.yaml
grid:
  - "....................城................"

units:
  - {id: enemy_boss, x: 20, y: 0, faction: enemy, ai: guard}

events:
  - {id: seize_story, trigger: enter, x: 20, y: 0, story: castle_seized}
  - {id: seize_win, trigger: reach_point, x: 20, y: 0, result: win, text: "占领城堡"}
```

流程：

1. boss 站在 (20,0)，玩家站不上去
2. 玩家打死 boss → 格子空出来
3. 玩家走到 (20,0) → `enter` 触发剧情 → 回合结束 `reach_point` 判胜

### 5.5 地形触发器：中毒单位站灵泉解毒

```yaml
# global.yaml::terrain
"灵":
  name: "灵泉"
  triggers:
    - on: turn_start
      once: true
      condition: "unit_has_poison == 1"
      story: spring_cure
      actions:
        - type: custom
          code: |
            for u in game.units:
                if u.alive and u.faction == 'player' and 'poison' in u.status:
                    u.status.remove('poison')
                    u.status_turns.pop('poison', None)
```

### 5.6 剧情链：三阶段选择

```yaml
# stories.yaml
intro_choice:
  dialogue:
    - choices:
        - text: "帮助村民"
          set_var: {choice: 1}
          story: help_villager
        - text: "追击山贼"
          set_var: {choice: 2}
          story: chase_bandit

help_villager:
  dialogue:
    - {speaker: "村民", text: "谢谢！这是谢礼。"}
  actions:
    - {type: give_item, unit: hero, item: vulnerary}
    - {type: set_var, var: village_saved, value: 1}

chase_bandit:
  dialogue:
    - {speaker: "艾伦", text: "不能让他们跑了！"}
  actions:
    - {type: set_var, var: bandit_chased, value: 1}
```

后续事件用 `condition` 读 `var_choice` / `var_village_saved` 分支。

---

## 6. 常见错误

| 错误写法 | 问题 | 正确写法 |
| --- | --- | --- |
| `type: giveitem` | 拼写错 | `type: give_item` |
| `type: spawn` | 不存在 | `type: spawn_unit` |
| `set_var` 写 `value_expr: "scout_lean + 1"` | 找不到变量 | `value_expr: "vars.scout_lean + 1"` |
| `change_terrain` 只写 `char: "桥"` 没 x/y | 报"缺少坐标" | 补 `x: 5, y: 5` |
| `next_map` 写不存在的 map | 报"地图不存在" | 检查 map id |
| `condition: "unit_uid == 'hero'"` 但 ctx 没 unit_uid | 静默失败（不报错，但不触发） | 确认 `_event_condition_ctx` 提供了该字段 |
| `change_ai` 只写 `move_to: {x,y}` 没 `move_mode` | 不生效 | 必须写 `move_mode: "move_to"` |
| `remove_unit` 和 `change_ai` 写在同一个 actions 里 | 命令作废（先删后跑） | `remove_unit` 放到到达剧情里 |
| `once: true` + condition 锁定 unit_uid | 只有该单位触发一次 | 想全局一次就锁 uid；想每个单位一次用 `terrain::triggers` |
| `spawn_unit` 到有单位的格 | 报错，不生成 | 提前留空 |

---

## 附：代码位置速查

| 想改… | 文件 + 函数 |
| --- | --- |
| 动作分发 | `core/event.py::run_action` |
| 动作类型表 | `core/event.py::_ACTION_TYPES` |
| 事件条件上下文 | `core/game.py::_event_condition_ctx` |
| 战斗对话上下文 | `core/battle.py::_battle_talk_ctx` |
| 道具条件上下文 | `core/action.py::_item_condition_ctx` |
| 地形触发器执行 | `core/game.py::_process_terrain_triggers` |
| 地图事件触发 | `core/game.py::_check_events` |
| 胜负判定 | `core/game.py::check_victory` |
| 公式引擎 | `core/formula.py::ev` |

---

**有疑问？** 把本文档 + 相关 YAML 段 + 涉及的 `.py` 文件发给 AI，就能定位问题或扩展功能。
