"""图形化 YAML 数据管理器（独立工具，零 core 依赖）。

设计边界：
  - 只读写 config/ 下的 5 个核心 YAML（status/items/skills/classes/units）
  - 不 import core/，不认识 Unit / Game / ev()
  - 注释保留是第一红线（ruamel round-trip mode）
  - 只通过 .backup/ 写备份，不新增 yaml 字段、不改 key
"""
__version__ = "0.1.0-p1"