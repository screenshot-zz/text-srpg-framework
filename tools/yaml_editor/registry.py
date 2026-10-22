"""ID 引用注册表：启动时加载所有相关 yaml，供下拉框收集 id。"""
from __future__ import annotations

from pathlib import Path

from .yaml_io import YamlFile


STAFF_SPECIAL_IDS: list[str] = [
    "repair", "revive", "summon", "teleport", "script",
]
ACTIVE_SKILL_SPECIAL_IDS: list[str] = ["steal", "dance"]


class Registry:
    def __init__(self, config_dir: str | Path):
        self.config_dir = Path(config_dir)
        self._cache: dict[str, list[tuple[str, str]]] = {}
        self.reload()

    # ---------- 加载 ----------

    def reload(self) -> None:
        self._cache = {}
        loaders = (
            ("status", "status.yaml"),
            ("items", "items.yaml"),
            ("skills", "skills.yaml"),
            ("classes", "classes.yaml"),
            ("units", "units.yaml"),
        )
        for key, filename in loaders:
            try:
                self._cache[key] = self._loader_flat(
                    self.config_dir / filename)
            except Exception:
                self._cache[key] = []

    @staticmethod
    def _loader_flat(path: Path) -> list[tuple[str, str]]:
        if not path.exists():
            return []
        yf = YamlFile(path)
        out: list[tuple[str, str]] = []
        for k, v in yf.items():
            name = str(v.get("name", k)) if isinstance(v, dict) else str(k)
            out.append((str(k), name))
        return out

    # ---------- 对外 API ----------

    def status_ids(self) -> list[tuple[str, str]]:
        return list(self._cache.get("status", []))

    def item_ids(self) -> list[tuple[str, str]]:
        return list(self._cache.get("items", []))

    def skill_ids(self) -> list[tuple[str, str]]:
        return list(self._cache.get("skills", []))

    def class_ids(self) -> list[tuple[str, str]]:
        return list(self._cache.get("classes", []))

    def unit_ids(self) -> list[tuple[str, str]]:
        return list(self._cache.get("units", []))

    def group_ids(self) -> list[str]:
        path = self.config_dir / "classes.yaml"
        if not path.exists():
            return []
        try:
            yf = YamlFile(path)
        except Exception:
            return []
        groups: set[str] = set()
        for _cid, cfg in yf.items():
            if isinstance(cfg, dict):
                for g in (cfg.get("groups") or []):
                    groups.add(str(g))
        return sorted(groups)

    def staff_special_ids(self) -> list[str]:
        return list(STAFF_SPECIAL_IDS)

    def active_skill_special_ids(self) -> list[str]:
        return list(ACTIVE_SKILL_SPECIAL_IDS)

    def key_item_ids(self) -> list[tuple[str, str]]:
        path = self.config_dir / "items.yaml"
        if not path.exists():
            return []
        try:
            yf = YamlFile(path)
        except Exception:
            return []
        out: list[tuple[str, str]] = []
        for k, v in yf.items():
            if isinstance(v, dict) and v.get("type") == "key":
                out.append((str(k), str(v.get("name", k))))
        return out

    def ai_profile_ids(self) -> list[tuple[str, str]]:
        path = self.config_dir / "global.yaml"
        if path.exists():
            try:
                yf = YamlFile(path)
                profiles = yf.get("ai_profiles") or {}
                out = [
                    (str(k), str(v.get("name", k)))
                    for k, v in profiles.items()
                    if isinstance(v, dict)
                ]
                if out:
                    return out
            except Exception:
                pass
        return [
            ("aggressive", "主动进攻"),
            ("guard", "驻守"),
            ("sentinel", "哨兵"),
            ("follow", "跟随"),
            ("move_to", "前往"),
            ("retreat", "撤退"),
        ]

    # ---------- P5 追加：地图相关 ----------

    def map_ids(self) -> list[tuple[str, str]]:
        """扫描 config/maps/*.yaml，返回 (id, name)。"""
        maps_dir = self.config_dir / "maps"
        if not maps_dir.exists():
            return []
        out: list[tuple[str, str]] = []
        for path in sorted(maps_dir.glob("*.yaml")):
            try:
                yf = YamlFile(path)
                map_id = yf.get("id") or path.stem
                map_name = yf.get("name") or str(map_id)
                out.append((str(map_id), str(map_name)))
            except Exception:
                continue
        return out

    def terrain_chars(self) -> dict[str, str]:
        """从 global.yaml 的 terrain 段收集 字符 → 颜色（rich 名或 hex）。"""
        path = self.config_dir / "global.yaml"
        if not path.exists():
            return {}
        try:
            yf = YamlFile(path)
            terrain = yf.get("terrain") or {}
            out: dict[str, str] = {}
            for k, v in terrain.items():
                if isinstance(v, dict):
                    out[str(k)] = str(v.get("color", "white"))
            return out
        except Exception:
            return {}