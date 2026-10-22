"""全局常量与工厂函数。所有 Mixin 与 Game 主类都从这里 import。"""
from __future__ import annotations

import os

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
MAP_DIR = os.path.join(CONFIG_DIR, "maps")
SAVE_DIR = os.path.join(BASE_DIR, "save")
GLOBAL_SAVE_PATH = os.path.join(SAVE_DIR, "global_save.json")
LEGACY_SAVE_PATH = os.path.join(SAVE_DIR, "save.json")

DIRS: dict[str, tuple[int, int]] = {
    "up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
}

LOSE_TRIGGERS = {"lord_dead", "all_player_dead", "turn_limit"}
NON_RESULT_TRIGGERS = {"start", "interact", "enter"}


def default_stats() -> dict:
    return {
        "kills": 0, "crits": 0, "misses": 0, "max_damage": 0,
        "turns": 0, "min_clear_turns": 0, "maps_cleared": 0,
        "gold_earned": 0, "items_used": 0, "skills_used": 0,
        "supports_unlocked": 0, "promotions": 0,
    }


def default_global_stats() -> dict:
    return {
        "total_kills": 0, "total_crits": 0, "total_misses": 0,
        "total_max_damage": 0, "total_turns": 0, "total_maps_cleared": 0,
        "total_gold_earned": 0, "total_items_used": 0, "total_skills_used": 0,
        "total_supports_unlocked": 0, "total_promotions": 0,
        "total_games_played": 0, "min_clear_turns": 0,
    }


def default_global_vars() -> dict:
    return {"achievements": [], "global_stats": default_global_stats()}


def load_yaml(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}