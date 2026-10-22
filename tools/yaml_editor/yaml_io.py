"""ruamel.yaml round-trip 封装 —— 注释保留是整个项目第一红线。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .backup import Backup


class YamlFile:
    """单个 YAML 文件的读写器。"""

    def __init__(self, path: str | Path, auto_load: bool = True):
        self.path = Path(path)
        self._yaml = YAML(typ="rt")
        self._yaml.preserve_quotes = True
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self._yaml.width = 4096
        self._yaml.allow_unicode = True
        self._data: CommentedMap | None = None
        self._dirty = False

        if auto_load:
            self.load()

    # ---------- 载入 / 保存 ----------

    def load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"YAML 文件不存在：{self.path}")
        with open(self.path, "r", encoding="utf-8") as f:
            data = self._yaml.load(f)
        if data is None:
            data = CommentedMap()
        if not isinstance(data, CommentedMap):
            raise ValueError(
                f"{self.path.name} 顶层必须是映射（dict），当前是 "
                f"{type(data).__name__}"
            )
        self._data = data
        self._dirty = False

    def save(self, backup: bool = True) -> None:
        if self._data is None:
            raise RuntimeError("save() 之前必须先 load()")
        if backup and self.path.exists():
            Backup.create(self.path)
        with open(self.path, "w", encoding="utf-8") as f:
            self._yaml.dump(self._data, f)
        self._dirty = False

    # ---------- 访问 ----------

    @property
    def data(self) -> CommentedMap:
        if self._data is None:
            raise RuntimeError("尚未 load()")
        return self._data

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        self._dirty = True

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def __len__(self) -> int:
        return len(self.data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def keys(self) -> list[str]:
        return [str(k) for k in self.data.keys()]

    def items(self):
        return self.data.items()

    def set(self, key: str, value: Any) -> None:
        """修改或新增一项（不插入空行）。"""
        self.data[key] = self.ensure_commented(value)
        self._dirty = True

    def delete(self, key: str) -> None:
        if key in self.data:
            del self.data[key]
            self._dirty = True

    # ---------- 插入（带空行） ----------

    def add_with_separator(self, key: str, value: Any) -> None:
        """在顶层 self.data 中新增一项，并在前面插入空行。"""
        self.add_to_map(self.data, key, value, separator=True)

    def add_to_map(self, target_map: CommentedMap, key: str, value: Any,
                   separator: bool = True) -> None:
        """在指定的 CommentedMap 中新增一项。"""
        if key in target_map:
            target_map[key] = self.ensure_commented(value)
            return
        target_map[key] = self.ensure_commented(value)
        if separator:
            try:
                target_map.yaml_set_comment_before_after_key(key, before="\n")
            except Exception:
                pass
        self._dirty = True

    def remove_blank_line_before(self, target_map: CommentedMap, key: str) -> None:
        """强制清理某些版本 ruamel 为新插入的块级节点自动添加的空行。"""
        try:
            target_map.yaml_set_comment_before_after_key(key, before="")
        except Exception:
            pass
        
        if key in target_map.ca.items:
            item = target_map.ca.items[key]
            for i in range(len(item)):
                if item[i] is not None and hasattr(item[i], "value"):
                    if item[i].value.strip() == "":
                        item[i].value = ""

    # ---------- 类型归一 ----------

    def ensure_commented(self, value: Any) -> Any:
        if isinstance(value, (CommentedMap, CommentedSeq)):
            return value
        if isinstance(value, dict):
            cm = CommentedMap()
            for k, v in value.items():
                cm[k] = self.ensure_commented(v)
            return cm
        if isinstance(value, list):
            cs = CommentedSeq()
            for v in value:
                cs.append(self.ensure_commented(v))
            return cs
        return value

    def ensure_flow_style(self, value: Any) -> Any:
        v = self.ensure_commented(value)
        if isinstance(v, CommentedSeq):
            v.fa.set_flow_style()
            for item in v:
                if isinstance(item, (CommentedMap, CommentedSeq)):
                    item.fa.set_flow_style()
        elif isinstance(v, CommentedMap):
            v.fa.set_flow_style()
        return v