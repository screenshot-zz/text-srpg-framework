"""地图工具：宽高校验修复 + 随机地形生成。

纯函数、无 UI 依赖，游戏逻辑零影响。
算法来自参考工具：
  - 宽高校验：fix_map.py
  - 噪声生成：map_generator.py
"""
from __future__ import annotations

import random


# ---------- 宽高校验 ----------

def validate_and_fix_grid(
    grid: list | None,
    width: int,
    height: int,
) -> tuple[list[str], list[str]]:
    """校验 grid 是否满足 width x height，不满足则自动截断/补齐。

    返回 (new_grid, messages)：
        new_grid：规整后的 list[str]，长度 = height，每行长度 = width
        messages：修复信息列表（空列表 = 无需修复）

    规则（对齐 fix_map.py）：
        - 行数过多 → 截断底部；行数过少 → 底部补 "."
        - 单行过长 → 截断到 width；过短 → 末尾补 "."
    """
    grid = list(grid or [])
    messages: list[str] = []

    if len(grid) > height:
        messages.append(f"行数过多，已截断底部 {len(grid) - height} 行")
    elif len(grid) < height:
        messages.append(f"行数过少，已补齐底部 {height - len(grid)} 行")

    new_grid: list[str] = []
    for i in range(height):
        row = str(grid[i]) if i < len(grid) else ""
        if len(row) > width:
            messages.append(
                f"第 {i + 1} 行过长 ({len(row)}/{width})，已截断")
            new_grid.append(row[:width])
        elif len(row) < width:
            messages.append(
                f"第 {i + 1} 行过短 ({len(row)}/{width})，已补齐")
            new_grid.append(row + "." * (width - len(row)))
        else:
            new_grid.append(row)

    return new_grid, messages


# ---------- 噪声生成 ----------

def _noise(w: int, h: int, seed: int, scale: int = 6) -> list[list[float]]:
    """双线性插值噪声图。逻辑完全复制自 map_generator.py。"""
    rng = random.Random(seed)
    gw, gh = w // scale + 2, h // scale + 2
    g = [[rng.random() for _ in range(gw)] for _ in range(gh)]
    out = [[0.0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            fx, fy = x / scale, y / scale
            x0, y0 = int(fx), int(fy)
            tx, ty = fx - x0, fy - y0

            def lerp(a, b, t):
                return a + (b - a) * t

            top = lerp(g[y0][x0], g[y0][x0 + 1], tx)
            bot = lerp(g[y0 + 1][x0], g[y0 + 1][x0 + 1], tx)
            out[y][x] = lerp(top, bot, ty)
    return out


def _remove_small_blobs(
    grid: list[list[str]],
    min_blob: int,
    keep: tuple[str, ...] = (),
) -> list[list[str]]:
    """去掉 < min_blob 的孤立块（保留 keep 里的字符不删）。"""
    h, w = len(grid), len(grid[0])
    seen = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if seen[y][x] or grid[y][x] == "." or grid[y][x] in keep:
                continue
            ch = grid[y][x]
            stack, block = [(y, x)], []
            while stack:
                cy, cx = stack.pop()
                if seen[cy][cx]:
                    continue
                seen[cy][cx] = True
                block.append((cy, cx))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if (0 <= ny < h and 0 <= nx < w
                            and not seen[ny][nx]
                            and grid[ny][nx] == ch):
                        stack.append((ny, nx))
            if len(block) < min_blob:
                for by, bx in block:
                    grid[by][bx] = "."
    return grid


def generate_random_grid(
    width: int,
    height: int,
    seed: int | None = None,
    ratios: dict[str, float] | None = None,
    river_ratio: float = 6,
    empty_ratio: float = 50,
    min_blob: int = 8,
) -> list[str]:
    """生成随机地形。

    参数：
        width, height      地图尺寸
        seed               整数 = 可复现，None = 自动随机
        ratios             各类地形占比（键必须与 global.yaml 里一致）
                           默认 {"山": 12, "林": 10, "村": 5, "城": 2, "丘": 7}
        river_ratio        河占比（%），走线生成
        empty_ratio        空地保底占比（%）
        min_blob           小于此数的孤立块会被清掉

    返回 list[str]（每行一个字符串，可直接填到 yaml 的 grid 字段）。
    """
    ratios = dict(ratios or {"山": 12, "林": 10, "村": 5, "城": 2, "丘": 7})
    rng_seed = seed if seed is not None else int(random.random() * 2**31)
    rng = random.Random(rng_seed)
    n = width * height

    # 归一化：确保不超 100
    total = sum(ratios.values()) + river_ratio + empty_ratio
    if total > 100:
        scale = 100.0 / total
        ratios = {k: v * scale for k, v in ratios.items()}
        river_ratio *= scale
        empty_ratio *= scale

    target = {k: int(v * n / 100) for k, v in ratios.items()}
    river_target = int(river_ratio * n / 100)

    nz = _noise(width, height, rng_seed)
    nz2 = _noise(width, height, rng_seed + 999, scale=9)
    grid: list[list[str | None]] = [[None] * width for _ in range(height)]

    order_high = sorted(
        ((nz[y][x], nz2[y][x], y, x)
         for y in range(height) for x in range(width)),
        key=lambda c: -c[0],
    )
    order_mix = sorted(order_high, key=lambda c: -c[1])

    def fill(order, ch, count):
        placed = 0
        for _, _, y, x in order:
            if placed >= count:
                break
            if grid[y][x] is not None:
                continue
            grid[y][x] = ch
            placed += 1

    fill(order_high, "山", target.get("山", 0))
    fill(order_high, "丘", target.get("丘", 0))
    fill(order_mix, "林", target.get("林", 0))

    # 河：随机游走
    if river_target > 0:
        y = rng.randint(0, height - 1)
        placed = 0
        for x in range(width):
            if placed >= river_target:
                break
            if 0 <= y < height and grid[y][x] is None:
                grid[y][x] = "河"
                placed += 1
            y += rng.choice([-1, 0, 1])
            y = max(0, min(height - 1, y))

    # 村、城：优先空地
    for ch, cnt in [
        ("村", target.get("村", 0)),
        ("城", target.get("城", 0)),
    ]:
        cand = [
            (y, x) for y in range(height) for x in range(width)
            if grid[y][x] is None
        ]
        rng.shuffle(cand)
        for y, x in cand[:cnt]:
            grid[y][x] = ch

    # None → 空地
    grid = [
        [(grid[y][x] if grid[y][x] is not None else ".")
         for x in range(width)]
        for y in range(height)
    ]

    # 连通块过滤
    grid = _remove_small_blobs(grid, min_blob, keep=("河",))

    return ["".join(row) for row in grid]