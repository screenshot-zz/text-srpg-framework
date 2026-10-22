"""左侧 id 列表：显示「中文名（id）」+ 新建/删除按钮。

主窗口 P1 的 status_editor 用它；P2/P3 的 items/skills/classes/units
编辑器复用同一个类（接口不变）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel,
)


class ListPanel(QWidget):
    """左侧列表。信号：

        - item_selected(key)   选中某项（key 是 yaml 里的 id）
        - add_requested()      点「+ 新建」
        - delete_requested()   点「删除」
    """

    item_selected = Signal(str)
    add_requested = Signal()
    delete_requested = Signal()

    def __init__(self, title: str = "列表", parent=None):
        super().__init__(parent)
        # _silent 用于 populate 期间抑制 currentItemChanged 信号
        self._silent = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 标题
        self._title = QLabel(title)
        self._title.setStyleSheet(
            "font-weight: bold; padding: 4px; font-size: 13px;")
        layout.addWidget(self._title)

        # 列表
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.list_widget, 1)

        # 底部按钮
        btns = QHBoxLayout()
        self.add_btn = QPushButton("+ 新建")
        self.del_btn = QPushButton("删除")
        btns.addWidget(self.add_btn)
        btns.addWidget(self.del_btn)
        layout.addLayout(btns)

        self.add_btn.clicked.connect(self.add_requested.emit)
        self.del_btn.clicked.connect(self.delete_requested.emit)

        self.enable_buttons(add=False, delete=False)

    # ---------- 对外 ----------

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def enable_buttons(self, add: bool = True, delete: bool = True) -> None:
        self.add_btn.setEnabled(add)
        self.del_btn.setEnabled(delete)

    def populate(self, items: list[tuple[str, str]],
                 current_key: str | None = None) -> None:
        """items: [(key, display_text)]。populate 期间不触发 item_selected。"""
        self._silent = True
        try:
            self.list_widget.clear()
            for key, display in items:
                it = QListWidgetItem(display)
                it.setData(Qt.UserRole, key)
                self.list_widget.addItem(it)
        finally:
            self._silent = False

        if current_key and self.select_key(current_key):
            return
        if items:
            self.list_widget.setCurrentRow(0)

    def current_key(self) -> str | None:
        cur = self.list_widget.currentItem()
        return None if cur is None else cur.data(Qt.UserRole)

    def select_key(self, key: str) -> bool:
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).data(Qt.UserRole) == key:
                self.list_widget.setCurrentRow(i)
                return True
        return False

    # ---------- 内部 ----------

    def _on_current_changed(self, current, _previous) -> None:
        if self._silent or current is None:
            return
        key = current.data(Qt.UserRole)
        if key is not None:
            self.item_selected.emit(str(key))