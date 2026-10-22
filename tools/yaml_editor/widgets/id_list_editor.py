"""id 列表编辑器（P3 的 classes/units 编辑器会用）。

P1 交付但暂不使用。P3 里会在以下场景用它：
  - classes.yaml 的 weapon_types（可选武器类型）
  - classes.yaml 的 class_skills（职业授予技能）
  - units.yaml 的 skills / items（单位携带的技能/道具）

交互：
    - 顶部：QComboBox（下拉）+ 添加按钮
    - 中部：QListWidget（已选项，允许删除选中）
    - 底部：移除按钮
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QComboBox,
)


class IdListEditor(QWidget):
    """id 列表编辑器。

    options_provider：每次刷新时调用，返回 [(id, name), ...]
    """

    changed = Signal()

    def __init__(
        self,
        options_provider: Callable[[], list[tuple[str, str]]] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._options_provider = options_provider

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 添加行
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.add_btn = QPushButton("添加")
        row.addWidget(self.combo, 1)
        row.addWidget(self.add_btn)
        layout.addLayout(row)

        # 已选项列表
        self.list_widget = QListWidget()
        self.list_widget.setMaximumHeight(140)
        layout.addWidget(self.list_widget)

        # 移除按钮
        self.remove_btn = QPushButton("移除选中")
        layout.addWidget(self.remove_btn)

        self.add_btn.clicked.connect(self._on_add)
        self.remove_btn.clicked.connect(self._on_remove)

    # ---------- 对外 ----------

    def refresh_options(self) -> None:
        """重新加载下拉候选（ID 集合变化后调用）。"""
        self.combo.clear()
        if self._options_provider is None:
            return
        for key, name in self._options_provider():
            self.combo.addItem(f"{name}（{key}）", key)

    def load(self, values: list[str] | None) -> None:
        self.refresh_options()
        self.list_widget.clear()
        for v in (values or []):
            self.list_widget.addItem(QListWidgetItem(str(v)))

    def get_values(self) -> list[str]:
        return [self.list_widget.item(i).text()
                for i in range(self.list_widget.count())]

    # ---------- 内部 ----------

    def _on_add(self) -> None:
        if self.combo.count() == 0:
            return
        key = self.combo.currentData()
        if not key:
            return
        # 去重
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).text() == key:
                return
        self.list_widget.addItem(QListWidgetItem(str(key)))
        self.changed.emit()

    def _on_remove(self) -> None:
        rows = sorted(
            {i.row() for i in self.list_widget.selectedIndexes()},
            reverse=True,
        )
        for r in rows:
            self.list_widget.takeItem(r)
        if rows:
            self.changed.emit()