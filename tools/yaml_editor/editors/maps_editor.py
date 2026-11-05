"""config/maps/*.yaml 编辑器（多文件）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea,
    QLabel, QLineEdit, QSpinBox, QPlainTextEdit, QPushButton,
    QMessageBox, QInputDialog, QTabWidget, QCheckBox,
)
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from ..map_utils import (
    validate_and_fix_grid, generate_random_grid,
)
from ..yaml_io import YamlFile
from ..zh_map import value_zh
from ..widgets.form_base import FormBase
from ..widgets.list_panel import ListPanel
from ..widgets.map_grid_view import MapGridView
from ..widgets.coords_table import CoordsTable
from ..widgets.action_list_editor import ActionListEditor


_DEFAULT_TERRAIN = {
    ".": "white", "山": "grey", "林": "green",
    "河": "blue", "村": "yellow", "商": "bright_yellow",
    "丘": "grey",
}


class MapsEditor(FormBase):
    def __init__(self, maps_dir: str | Path, registry, parent=None):
        super().__init__(parent)
        self.maps_dir = Path(maps_dir)
        self.registry = registry

        self._files: dict[str, YamlFile] = {}
        self._current_map_id: str | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.list_panel = ListPanel(title="地图列表")
        self.list_panel.setMinimumWidth(220)
        self.list_panel.setMaximumWidth(320)
        layout.addWidget(self.list_panel)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self.header = QLabel("请选择左侧地图")
        self.header.setStyleSheet(
            "font-weight: bold; font-size: 14px; padding: 4px;")
        right_layout.addWidget(self.header)

        self.tabs = QTabWidget()
        self._basic_tab = _BasicInfoTab(self)
        self._terrain_tab = _TerrainGridTab(self)
        self._deploy_tab = _DeployPointsTab(self)
        self._units_tab = _InitialUnitsTab(self)
        self._shops_tab = _ShopsTab(self)
        self._events_tab = _EventsTab(self)

        self.tabs.addTab(self._basic_tab, "基本信息")
        self.tabs.addTab(self._terrain_tab, "地形网格")
        self.tabs.addTab(self._deploy_tab, "部署点")
        self.tabs.addTab(self._units_tab, "初始单位")
        self.tabs.addTab(self._shops_tab, "商店配置")
        self.tabs.addTab(self._events_tab, "地图事件")

        right_layout.addWidget(self.tabs, 1)

        layout.addWidget(right, 1)

        self.list_panel.item_selected.connect(self._on_select)
        self.list_panel.add_requested.connect(self._on_add_map)
        self.list_panel.delete_requested.connect(self._on_delete_map)
        self.list_panel.enable_buttons(add=False, delete=False)

        self._basic_tab.bounds_changed.connect(self._on_bounds_changed)

        self._load_all_maps()
        self._refresh_list()

    def _load_all_maps(self) -> None:
        self._files = {}
        if not self.maps_dir.exists():
            return
        for path in sorted(self.maps_dir.glob("*.yaml")):
            try:
                yf = YamlFile(path)
            except Exception:
                continue
            map_id = yf.get("id") or path.stem
            self._files[str(map_id)] = yf

    def _refresh_list(self, keep_id: str | None = None) -> None:
        items: list[tuple[str, str]] = []
        for map_id, yf in self._files.items():
            name = yf.get("name") or map_id
            items.append((map_id, f"{value_zh(str(name))}（{map_id}）"))
        self.list_panel.populate(
            items, current_key=keep_id or self._current_map_id)
        if not items:
            self.list_panel.enable_buttons(add=False, delete=False)

    def _on_select(self, map_id: str) -> None:
        if map_id == self._current_map_id:
            return
        self._current_map_id = map_id
        self._load_map_into_tabs(map_id)

    def _load_map_into_tabs(self, map_id: str) -> None:
        yf = self._files.get(map_id)
        if yf is None:
            return
        name = yf.get("name") or map_id
        self.header.setText(f"编辑地图：{value_zh(str(name))}（{map_id}）")

        self._basic_tab.load_from_yaml(yf)
        self._terrain_tab.load_from_yaml(yf)
        self._deploy_tab.load_from_yaml(yf)
        self._units_tab.load_from_yaml(yf)
        self._shops_tab.load_from_yaml(yf)
        self._events_tab.load_from_yaml(yf)

    def _on_bounds_changed(self, width: int, height: int) -> None:
        self._terrain_tab.update_bounds(width, height)
        self._deploy_tab.update_bounds(width, height)
        self._units_tab.update_bounds(width, height)
        self._shops_tab.update_bounds(width, height)

    def _on_add_map(self) -> None:
        new_id, ok = QInputDialog.getText(
            self, "新建地图", "请输入地图 id（英文，如 map3）：")
        if not ok or not new_id.strip():
            return
        new_id = new_id.strip()
        if not _is_valid_id(new_id):
            QMessageBox.warning(
                self, "非法 id",
                "id 只能包含字母、数字、下划线，且不能以数字开头。")
            return
        if new_id in self._files:
            QMessageBox.warning(
                self, "id 重复", f"地图 id「{new_id}」已存在。")
            return

        path = self.maps_dir / f"{new_id}.yaml"
        template = {
            "id": new_id, "name": "新地图",
            "width": 20, "height": 15, "max_deploy": 4,
            "grid": ["." * 20] * 15,
            "units": [], "deploy_points": [], "shops": [], "events": [],
        }
        import yaml as pyyaml
        with open(path, "w", encoding="utf-8") as f:
            pyyaml.safe_dump(template, f, allow_unicode=True, sort_keys=False)
        yf = YamlFile(path)
        self._files[new_id] = yf
        self._refresh_list(keep_id=new_id)

    def _on_delete_map(self) -> None:
        pass

    def has_unsaved_changes(self) -> bool:
        return any(yf.dirty for yf in self._files.values())

    def save(self) -> None:
        fixed_files: list[str] = []
        for map_id, yf in self._files.items():
            if not yf.dirty:
                continue
            width = int(yf.get("width") or 20)
            height = int(yf.get("height") or 15)
            grid = yf.get("grid") or []
            new_grid, msgs = validate_and_fix_grid(grid, width, height)
            if msgs:
                fixed_files.append(f"【{map_id}】\n" + "\n".join(msgs))
                yf.set("grid", new_grid)
            yf.save()

        if fixed_files:
            QMessageBox.information(
                self, "保存时已自动修复地图尺寸",
                "以下地图的 grid 与 width/height 不匹配，已自动修复：\n\n"
                + "\n\n".join(fixed_files))

    def refresh(self) -> None:
        self._load_all_maps()
        self._current_map_id = None
        self.header.setText("请选择左侧地图")
        self._refresh_list()

    def current_yaml(self) -> YamlFile | None:
        if self._current_map_id is None:
            return None
        return self._files.get(self._current_map_id)

    def current_cfg(self) -> CommentedMap | None:
        yf = self.current_yaml()
        return yf.data if yf else None

    def mark_current_dirty(self) -> None:
        yf = self.current_yaml()
        if yf:
            yf.mark_dirty()


class _BasicInfoTab(QWidget):
    changed = Signal()
    bounds_changed = Signal(int, int)

    def __init__(self, editor: "MapsEditor", parent=None):
        super().__init__(parent)
        self.editor = editor
        self._loading = False

        form = QFormLayout(self)
        form.setContentsMargins(8, 8, 8, 8)

        self.id_edit = QLineEdit()
        self.name_edit = QLineEdit()
        self.bgm_edit = QLineEdit()

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 200)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 200)
        self.max_deploy_spin = QSpinBox()
        self.max_deploy_spin.setRange(0, 100)

        form.addRow("地图 id", self.id_edit)
        form.addRow("名称", self.name_edit)
        form.addRow("BGM 路径", self.bgm_edit)
        form.addRow("宽度", self.width_spin)
        form.addRow("高度", self.height_spin)
        form.addRow("出战上限", self.max_deploy_spin)

        self.id_edit.textChanged.connect(
            lambda _t: self._on_change("id", self.id_edit.text()))
        self.name_edit.textChanged.connect(
            lambda _t: self._on_change("name", self.name_edit.text()))
        self.bgm_edit.textChanged.connect(
            lambda _t: self._on_change("bgm", self.bgm_edit.text()))
        self.width_spin.valueChanged.connect(
            lambda _v: self._on_dim_change("width"))
        self.height_spin.valueChanged.connect(
            lambda _v: self._on_dim_change("height"))
        self.max_deploy_spin.valueChanged.connect(
            lambda _v: self._on_change("max_deploy", self.max_deploy_spin.value()))

    def load_from_yaml(self, yf: YamlFile) -> None:
        self._loading = True
        try:
            self.id_edit.setText(str(yf.get("id") or ""))
            self.name_edit.setText(str(yf.get("name") or ""))
            self.bgm_edit.setText(str(yf.get("bgm") or ""))
            self.width_spin.setValue(int(yf.get("width") or 20))
            self.height_spin.setValue(int(yf.get("height") or 15))
            self.max_deploy_spin.setValue(int(yf.get("max_deploy") or 0))
        finally:
            self._loading = False

    def _on_change(self, key: str, value: Any) -> None:
        if self._loading:
            return
        cfg = self.editor.current_cfg()
        if cfg is None:
            return
        cfg[key] = value
        self.editor.mark_current_dirty()
        self.changed.emit()

    def _on_dim_change(self, key: str) -> None:
        if self._loading:
            return
        cfg = self.editor.current_cfg()
        if cfg is None:
            return
        new_val = (self.width_spin.value() if key == "width"
                   else self.height_spin.value())
        cfg[key] = new_val
        self.editor.mark_current_dirty()
        self.changed.emit()
        self.bounds_changed.emit(
            self.width_spin.value(), self.height_spin.value())


class _TerrainGridTab(QWidget):
    def __init__(self, editor: "MapsEditor", parent=None):
        super().__init__(parent)
        self.editor = editor
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        preview_label = QLabel("预览（只读，点击方格显示坐标）")
        preview_label.setStyleSheet("color: #666; font-weight: bold;")
        layout.addWidget(preview_label)

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #ddd; }")
        self.preview_scroll.setMinimumHeight(180)
        self.preview = MapGridView()
        self.preview.cell_clicked.connect(self._on_preview_clicked)
        self.preview_scroll.setWidget(self.preview)
        layout.addWidget(self.preview_scroll, 1)

        bar = QHBoxLayout()
        gen_btn = QPushButton("🎲 随机生成地形")
        gen_btn.clicked.connect(self._on_generate)
        bar.addWidget(gen_btn)

        check_btn = QPushButton("校验并修复")
        check_btn.setToolTip(
            "检查 grid 与 width/height 是否匹配，不匹配则截断/补齐")
        check_btn.clicked.connect(self._on_validate)
        bar.addWidget(check_btn)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #666; font-size: 11px;")
        bar.addWidget(self.status, 1)
        layout.addLayout(bar)

        edit_label = QLabel("文本编辑（每行一个字符串，长度必须等于宽度）")
        edit_label.setStyleSheet(
            "color: #666; font-weight: bold; margin-top: 4px;")
        layout.addWidget(edit_label)

        self.text = QPlainTextEdit()
        self.text.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;")
        self.text.setMinimumHeight(120)
        layout.addWidget(self.text)

        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(100)
        self._debounce.timeout.connect(self._refresh_preview)

        self.text.textChanged.connect(self._on_text_changed)

        terrain = editor.registry.terrain_chars() or {}
        if not terrain:
            terrain = dict(_DEFAULT_TERRAIN)
        self.preview.set_terrain_colors(terrain)

    def load_from_yaml(self, yf: YamlFile) -> None:
        self._loading = True
        try:
            grid = yf.get("grid") or []
            self.text.setPlainText("\n".join(str(r) for r in grid))
            self._refresh_preview()
            self.status.setText("")
            self.status.setStyleSheet("color: #666; font-size: 11px;")
        finally:
            self._loading = False

    def update_bounds(self, width: int, height: int) -> None:
        self._refresh_preview()

    def _on_preview_clicked(self, x: int, y: int) -> None:
        self.preview.set_selected(x, y)
        self.status.setText(f"📍 选中格：({x}, {y})")
        self.status.setStyleSheet(
            "color: #0066cc; font-weight: bold; font-size: 11px;")

    def _on_text_changed(self) -> None:
        if self._loading:
            return
        self._debounce.start()

    def _refresh_preview(self) -> None:
        rows = self.text.toPlainText().split("\n")
        while rows and not rows[-1]:
            rows.pop()
        self.preview.set_grid(rows)

        if not self._loading:
            cfg = self.editor.current_cfg()
            if cfg is not None:
                cfg["grid"] = self.editor.current_yaml().ensure_commented(rows)
                self.editor.mark_current_dirty()

    def _on_generate(self) -> None:
        cfg = self.editor.current_cfg()
        if cfg is None:
            return
        width = int(cfg.get("width") or 20)
        height = int(cfg.get("height") or 15)

        seed_str, ok = QInputDialog.getText(
            self, "随机生成地形",
            f"将生成 {width} x {height} 的地图。\n\n"
            f"输入整数 seed（可复现），留空则自动随机：")
        if not ok:
            return
        seed = None
        if seed_str.strip():
            try:
                seed = int(seed_str.strip())
            except ValueError:
                QMessageBox.warning(self, "非法 seed", "seed 必须是整数。")
                return

        try:
            new_grid = generate_random_grid(width, height, seed=seed)
        except Exception as e:
            QMessageBox.critical(self, "生成失败", str(e))
            return

        self._loading = True
        try:
            self.text.setPlainText("\n".join(new_grid))
        finally:
            self._loading = False
        self._refresh_preview()
        self.status.setText("✓ 已生成新地形，请检查并保存")
        self.status.setStyleSheet("color: #080; font-size: 11px;")

    def _on_validate(self) -> None:
        cfg = self.editor.current_cfg()
        if cfg is None:
            return
        width = int(cfg.get("width") or 20)
        height = int(cfg.get("height") or 15)

        rows = self.text.toPlainText().split("\n")
        while rows and not rows[-1]:
            rows.pop()

        new_grid, msgs = validate_and_fix_grid(rows, width, height)
        if not msgs:
            QMessageBox.information(
                self, "校验通过", "✓ grid 与 width/height 完全匹配。")
            return
        QMessageBox.information(
            self, "已自动修复",
            "检测到以下问题，已自动修复：\n\n" + "\n".join(msgs))
        self._loading = True
        try:
            self.text.setPlainText("\n".join(new_grid))
        finally:
            self._loading = False
        self._refresh_preview()
        self.status.setText("✓ 已自动修复")
        self.status.setStyleSheet("color: #080; font-size: 11px;")


class _DeployPointsTab(QWidget):
    def __init__(self, editor: "MapsEditor", parent=None):
        super().__init__(parent)
        self.editor = editor
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        hint = QLabel("我方出生点。按地图顺序依次部署出战单位。")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        self.table = CoordsTable(columns=[
            {"key": "x", "label": "X", "type": "int",
             "min": 0, "max": 199, "default": 0},
            {"key": "y", "label": "Y", "type": "int",
             "min": 0, "max": 199, "default": 0},
        ])
        self.table.changed.connect(self._on_changed)
        layout.addWidget(self.table, 1)

    def load_from_yaml(self, yf: YamlFile) -> None:
        self._loading = True
        try:
            self.table.load(list(yf.get("deploy_points") or []))
        finally:
            self._loading = False

    def update_bounds(self, width: int, height: int) -> None:
        self.table.update_bounds(width, height)

    def _on_changed(self) -> None:
        if self._loading:
            return
        cfg = self.editor.current_cfg()
        if cfg is None:
            return
        yf = self.editor.current_yaml()
        cfg["deploy_points"] = yf.ensure_flow_style(self.table.get_data())
        yf.mark_dirty()


class _InitialUnitsTab(QWidget):
    def __init__(self, editor: "MapsEditor", parent=None):
        super().__init__(parent)
        self.editor = editor
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        hint = QLabel(
            "地图开局时出现的敌方/NPC 单位。AI 栏直接填英文字符串（如 aggressive、guard、哨兵自定义代码等）。\n"
            "若需配置特殊 AI 参数（如 move_to 的坐标等），点行内「编辑参数...」。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        self.table = CoordsTable(columns=[
            {"key": "id", "label": "单位 id", "type": "combo",
             "options": editor.registry.unit_ids()},
            {"key": "x", "label": "X", "type": "int",
             "min": 0, "max": 199, "default": 0},
            {"key": "y", "label": "Y", "type": "int",
             "min": 0, "max": 199, "default": 0},
            {"key": "faction", "label": "阵营", "type": "combo",
             "options": [
                 ("enemy", "敌人"),
                 ("ally", "友军"),
                 ("player", "我军"),
             ],
             "default": "enemy"},
            # ⭐ AI 改成纯文本输入，方便以后自由调用全局新增的 AI
            {"key": "ai", "label": "AI", "type": "text", "default": "aggressive"},
        ], allow_extra=True)
        self.table.changed.connect(self._on_changed)
        layout.addWidget(self.table, 1)

    def load_from_yaml(self, yf: YamlFile) -> None:
        self._loading = True
        try:
            self.table.load(list(yf.get("units") or []))
        finally:
            self._loading = False

    def update_bounds(self, width: int, height: int) -> None:
        self.table.update_bounds(width, height)

    def _on_changed(self) -> None:
        if self._loading:
            return
        cfg = self.editor.current_cfg()
        if cfg is None:
            return
        yf = self.editor.current_yaml()
        cfg["units"] = yf.ensure_flow_style(self.table.get_data())
        yf.mark_dirty()


class _ShopsTab(QWidget):
    def __init__(self, editor: "MapsEditor", parent=None):
        super().__init__(parent)
        self.editor = editor
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        hint = QLabel(
            "地图上的商店。玩家控制单位站在对应坐标时，可以打开指定的商店代码。")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        self.table = CoordsTable(columns=[
            {"key": "x", "label": "X", "type": "int",
             "min": 0, "max": 199, "default": 0},
            {"key": "y", "label": "Y", "type": "int",
             "min": 0, "max": 199, "default": 0},
            {"key": "shop", "label": "商店代码", "type": "text", "default": ""},
        ])
        self.table.changed.connect(self._on_changed)
        layout.addWidget(self.table, 1)

    def load_from_yaml(self, yf: YamlFile) -> None:
        self._loading = True
        try:
            self.table.load(list(yf.get("shops") or []))
        finally:
            self._loading = False

    def update_bounds(self, width: int, height: int) -> None:
        self.table.update_bounds(width, height)

    def _on_changed(self) -> None:
        if self._loading:
            return
        cfg = self.editor.current_cfg()
        if cfg is None:
            return
        yf = self.editor.current_yaml()
        cfg["shops"] = yf.ensure_flow_style(self.table.get_data())
        yf.mark_dirty()


class _EventsTab(QWidget):
    def __init__(self, editor: "MapsEditor", parent=None):
        super().__init__(parent)
        self.editor = editor
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        hint = QLabel(
            "事件 JSON 数组。常用 trigger："
            "start（开局）/ interact（访问）/ enter（进入格）/ "
            "all_enemy_dead（全灭）/ lord_dead（主角阵亡）/ "
            "reach_point（到点）/ turn_limit（回合数超限）。\n"
            "有 result 字段的是胜负判定；无 result 的是纯剧情。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        self.editor_widget = ActionListEditor()
        self.editor_widget.changed.connect(self._on_changed)
        layout.addWidget(self.editor_widget, 1)

    def load_from_yaml(self, yf: YamlFile) -> None:
        self._loading = True
        try:
            self.editor_widget.load(list(yf.get("events") or []))
        finally:
            self._loading = False

    def _on_changed(self) -> None:
        if self._loading:
            return
        cfg = self.editor.current_cfg()
        if cfg is None:
            return
        data = self.editor_widget.get_data()
        if data is None:
            return
        yf = self.editor.current_yaml()
        cfg["events"] = yf.ensure_flow_style(data)
        yf.mark_dirty()


def _is_valid_id(s: str) -> bool:
    if not s:
        return False
    if s[0].isdigit():
        return False
    return all(c.isalnum() or c == "_" for c in s)
