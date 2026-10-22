"""地图网格只读预览控件（方案 A 基础版）。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


_RICH_TO_HEX = {
    "white": "#ffffff", "black": "#000000",
    "red": "#c00000", "green": "#00a000", "blue": "#0000c0",
    "yellow": "#c0c000", "grey": "#808080", "gray": "#808080",
    "cyan": "#00c0c0", "magenta": "#c000c0",
    "bright_white": "#ffffff", "bright_red": "#ff4040",
    "bright_green": "#40ff40", "bright_blue": "#4040ff",
    "bright_yellow": "#ffff00", "bright_cyan": "#40ffff",
    "bright_magenta": "#ff40ff",
    "dark_red": "#800000", "dark_green": "#006000",
    "dark_blue": "#000060", "dark_cyan": "#006060",
    "dark_magenta": "#600060", "dark_yellow": "#606000",
}


def to_qcolor(color_str: str, fallback: str = "#ffffff") -> QColor:
    if not color_str:
        return QColor(fallback)
    s = str(color_str).strip().lower()
    if s.startswith("#"):
        c = QColor(s)
        return c if c.isValid() else QColor(fallback)
    hex_str = _RICH_TO_HEX.get(s)
    if hex_str:
        return QColor(hex_str)
    return QColor(fallback)


class MapGridView(QWidget):
    cell_clicked = Signal(int, int)   # (x, y)

    CELL_SIZE = 18

    def __init__(self, parent=None):
        super().__init__(parent)

        self._table = QTableWidget()
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.NoSelection)
        self._table.setShowGrid(False)
        self._table.horizontalHeader().setVisible(False)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setDefaultSectionSize(self.CELL_SIZE)
        self._table.verticalHeader().setDefaultSectionSize(self.CELL_SIZE)
        self._table.setStyleSheet(
            "QTableWidget { background: #222; border: none; }")
        font = QFont("Consolas")
        font.setPointSize(10)
        self._table.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)

        self._table.cellClicked.connect(self._on_cell_clicked)

        self._colors: dict[str, QColor] = {}
        self._grid: list[str] = []
        self._selected: tuple[int, int] | None = None

    def set_terrain_colors(self, colors: dict[str, str]) -> None:
        self._colors = {
            str(k): to_qcolor(v) for k, v in (colors or {}).items()
        }
        if self._grid:
            self._render()

    def set_grid(self, grid: list[str] | list[list[str]]) -> None:
        normalized: list[str] = []
        for row in grid or []:
            if isinstance(row, (list, tuple)):
                normalized.append("".join(str(c) for c in row))
            else:
                normalized.append(str(row))
        self._grid = normalized
        self._selected = None
        self._render()

    def set_selected(self, x: int, y: int | None) -> None:
        if x < 0 or y is None or y < 0:
            self._selected = None
        else:
            self._selected = (x, y)
        self._render()

    def get_grid(self) -> list[str]:
        return list(self._grid)

    def get_cell_size(self) -> int:
        return self.CELL_SIZE

    def _render(self) -> None:
        h = len(self._grid)
        w = len(self._grid[0]) if h else 0
        self._table.setRowCount(h)
        self._table.setColumnCount(w)

        default_fg = QColor("#000000")
        sel_bg = QColor("#00ffff")  # 亮青色高亮

        for y in range(h):
            row = self._grid[y]
            for x in range(w):
                ch = row[x] if x < len(row) else "."
                item = QTableWidgetItem(ch)
                item.setTextAlignment(Qt.AlignCenter)

                is_sel = self._selected == (x, y)
                bg = sel_bg if is_sel else self._colors.get(ch, QColor("#ffffff"))
                item.setBackground(QBrush(bg))

                if is_sel:
                    item.setForeground(QBrush(QColor("#000000")))
                    item.setToolTip(f"选中：({x}, {y})")
                else:
                    fg = QColor("#ffffff") if bg.lightness() < 128 else default_fg
                    item.setForeground(QBrush(fg))

                self._table.setItem(y, x, item)

    def _on_cell_clicked(self, row: int, col: int) -> None:
        self.cell_clicked.emit(col, row)