"""所有编辑器的基类：统一 save / dirty / refresh 接口。

MainWindow 通过这三个方法跟所有编辑器打交道，不关心具体实现。
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ..yaml_io import YamlFile


class FormBase(QWidget):
    """编辑器基类。子类必须：

        - 在 __init__ 中设置 self.yaml_file（YamlFile 实例）
        - 实现 refresh()（重新从磁盘载入 + 刷新界面）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.yaml_file: YamlFile | None = None

    # ---------- 接口（子类可覆写） ----------

    def refresh(self) -> None:  # noqa: D401
        """重新载入磁盘数据 + 刷新界面（会丢弃内存修改）。"""
        raise NotImplementedError

    def has_unsaved_changes(self) -> bool:
        if self.yaml_file is None:
            return False
        return bool(getattr(self.yaml_file, "dirty", False))

    def save(self) -> None:
        """保存到磁盘（save 内部自动备份）。"""
        if self.yaml_file is not None:
            self.yaml_file.save()