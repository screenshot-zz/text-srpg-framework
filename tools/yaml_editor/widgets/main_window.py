"""主窗口：左侧导航 + 右侧 QStackedWidget 编辑区 + 菜单 + 状态栏。

P5 完成后 7 个编辑器全部完整：
    status / items / skills / classes / units / stories / maps
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget,
    QListWidgetItem, QStackedWidget, QMessageBox, QLabel,
)

from ..backup import Backup
from ..editors.status_editor import StatusEditor
from ..editors.items_editor import ItemsEditor
from ..editors.skills_editor import SkillsEditor
from ..editors.classes_editor import ClassesEditor
from ..editors.units_editor import UnitsEditor
from ..editors.stories_editor import StoriesEditor
from ..editors.maps_editor import MapsEditor
from ..registry import Registry


class PlaceholderEditor(QWidget):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        label = QLabel(f"「{name}」编辑器加载失败")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #c00; font-size: 14px;")
        layout.addWidget(label)

    def has_unsaved_changes(self) -> bool:
        return False

    def save(self) -> None:
        pass

    def refresh(self) -> None:
        pass


class MainWindow(QMainWindow):
    PAGES: list[tuple[str, str]] = [
        ("status", "状态"),
        ("items", "道具"),
        ("skills", "技能"),
        ("classes", "职业"),
        ("units", "单位"),
        ("stories", "剧情"),
        ("maps", "地图"),
    ]

    def __init__(self, config_dir: str | Path, parent=None):
        super().__init__(parent)
        self.config_dir = Path(config_dir)
        self.setWindowTitle(
            "火焰之纹章·文字战记 — YAML 数据管理器 (P5)")
        self.resize(1360, 820)

        try:
            self.registry = Registry(self.config_dir)
        except Exception as e:
            self.registry = None
            QMessageBox.warning(
                self, "Registry 加载失败",
                f"Registry 加载时出现异常：\n{e}")

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setMinimumWidth(140)
        self.nav.setMaximumWidth(180)
        self.nav.setStyleSheet(
            "QListWidget::item { padding: 8px 12px; }")
        for _pid, name in self.PAGES:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, _pid)
            self.nav.addItem(item)
        layout.addWidget(self.nav)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.setCentralWidget(central)

        self.editors: dict[str, QWidget] = {}
        self._build_editors()

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self._build_menus()
        self._build_statusbar()

    # ---------- 装配 ----------

    def _build_editors(self) -> None:
        self._load_editor(
            pid="status", filename="status.yaml",
            factory=lambda path: StatusEditor(path),
            fallback_label="状态",
        )
        self._load_editor(
            pid="items", filename="items.yaml",
            factory=lambda path: ItemsEditor(path, self.registry),
            fallback_label="道具",
            requires_registry=True,
        )
        self._load_editor(
            pid="skills", filename="skills.yaml",
            factory=lambda path: SkillsEditor(path, self.registry),
            fallback_label="技能",
            requires_registry=True,
        )
        self._load_editor(
            pid="classes", filename="classes.yaml",
            factory=lambda path: ClassesEditor(path, self.registry),
            fallback_label="职业",
            requires_registry=True,
        )
        self._load_editor(
            pid="units", filename="units.yaml",
            factory=lambda path: UnitsEditor(path, self.registry),
            fallback_label="单位",
            requires_registry=True,
        )
        self._load_editor(
            pid="stories", filename="stories.yaml",
            factory=lambda path: StoriesEditor(path, self.registry),
            fallback_label="剧情",
            requires_registry=True,
        )
        # maps 特殊：传目录而非文件
        self._load_editor(
            pid="maps", filename="maps",
            factory=lambda path: MapsEditor(path, self.registry),
            fallback_label="地图",
            requires_registry=True,
        )

    def _load_editor(
        self,
        pid: str,
        filename: str,
        factory: Callable[[Path], QWidget],
        fallback_label: str,
        requires_registry: bool = False,
    ) -> None:
        if requires_registry and self.registry is None:
            ed = PlaceholderEditor(f"{fallback_label}（Registry 未加载）")
            self.editors[pid] = ed
            self.stack.addWidget(ed)
            return
        try:
            editor = factory(self.config_dir / filename)
        except Exception as e:
            QMessageBox.critical(
                self, f"加载 {filename} 失败",
                f"{e}\n\n该页面已禁用。")
            editor = PlaceholderEditor(f"{fallback_label}（加载失败）")
            idx = [p for p, _n in self.PAGES].index(pid)
            self.nav.item(idx).setEnabled(False)
        self.editors[pid] = editor
        self.stack.addWidget(editor)

    # ---------- 菜单 ----------

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("文件")

        act_save = QAction("保存全部", self)
        act_save.setShortcut(QKeySequence.Save)
        act_save.triggered.connect(self._save_all)
        file_menu.addAction(act_save)

        act_reload = QAction("重载全部", self)
        act_reload.triggered.connect(self._reload_all)
        file_menu.addAction(act_reload)

        file_menu.addSeparator()

        act_backup = QAction("打开备份目录", self)
        act_backup.triggered.connect(self._open_backup_dir)
        file_menu.addAction(act_backup)

        file_menu.addSeparator()

        act_quit = QAction("退出", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

    # ---------- 状态栏 ----------

    def _build_statusbar(self) -> None:
        self._status_label = QLabel("就绪")
        self.statusBar().addWidget(self._status_label, 1)

        self._dirty_label = QLabel("未保存：0 个文件")
        self.statusBar().addPermanentWidget(self._dirty_label)

        self._backup_label = QLabel("上次备份：—")
        self.statusBar().addPermanentWidget(self._backup_label)

        self._dirty_timer = QTimer(self)
        self._dirty_timer.setInterval(800)
        self._dirty_timer.timeout.connect(self._refresh_dirty_status)
        self._dirty_timer.start()

        self._update_backup_label()

    def _dirty_editors(self) -> list[tuple[str, QWidget]]:
        return [
            (pid, e) for pid, e in self.editors.items()
            if hasattr(e, "has_unsaved_changes") and e.has_unsaved_changes()
        ]

    def _save_all(self) -> None:
        dirty = self._dirty_editors()
        if not dirty:
            self._status_label.setText("没有需要保存的修改")
            return

        saved = 0
        errors: list[str] = []
        for pid, editor in dirty:
            try:
                editor.save()
                saved += 1
            except Exception as e:
                errors.append(f"{pid}: {e}")

        if saved:
            self._status_label.setText(f"已保存 {saved} 个文件")
            if self.registry is not None:
                try:
                    self.registry.reload()
                except Exception:
                    pass
            for editor in self.editors.values():
                if hasattr(editor, "refresh"):
                    try:
                        editor.refresh()
                    except Exception:
                        pass

        if errors:
            QMessageBox.critical(
                self, "保存失败",
                "以下文件保存失败：\n\n" + "\n".join(errors))

        self._refresh_dirty_status()
        self._update_backup_label()

    def _reload_all(self) -> None:
        dirty = self._dirty_editors()
        if dirty:
            resp = QMessageBox.question(
                self, "重载确认",
                "以下文件有未保存修改，重载会丢弃：\n\n"
                + "\n".join(pid for pid, _e in dirty)
                + "\n\n是否继续？",
            )
            if resp != QMessageBox.Yes:
                return

        for pid, editor in self.editors.items():
            if hasattr(editor, "refresh"):
                try:
                    editor.refresh()
                except Exception as e:
                    QMessageBox.warning(self, "重载失败", f"{pid}: {e}")

        if self.registry is not None:
            try:
                self.registry.reload()
            except Exception:
                pass

        self._status_label.setText("已重载全部")
        self._refresh_dirty_status()

    def _open_backup_dir(self) -> None:
        bdir = Backup.backup_dir(self.config_dir / "status.yaml")
        bdir.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(str(bdir))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(bdir)])
            else:
                subprocess.Popen(["xdg-open", str(bdir)])
        except Exception as e:
            QMessageBox.information(
                self, "备份目录",
                f"备份目录路径：\n{bdir}\n\n（自动打开失败：{e}）")

    def _refresh_dirty_status(self) -> None:
        n = len(self._dirty_editors())
        if n:
            self._dirty_label.setText(f"● 未保存：{n} 个文件")
            self._dirty_label.setStyleSheet(
                "color: #c00; font-weight: bold;")
        else:
            self._dirty_label.setText("未保存：0 个文件")
            self._dirty_label.setStyleSheet("")

    def _update_backup_label(self) -> None:
        bdir = Backup.backup_dir(self.config_dir / "status.yaml")
        if not bdir.exists():
            self._backup_label.setText("上次备份：—")
            return
        try:
            files = sorted(
                bdir.glob("*.bak"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not files:
                self._backup_label.setText("上次备份：—")
                return
            ts = datetime.fromtimestamp(files[0].stat().st_mtime)
            self._backup_label.setText(
                f"上次备份：{ts.strftime('%H:%M:%S')}")
        except OSError:
            self._backup_label.setText("上次备份：—")

    def closeEvent(self, event) -> None:
        dirty = self._dirty_editors()
        if not dirty:
            event.accept()
            return

        resp = QMessageBox.question(
            self, "退出确认",
            "以下文件有未保存修改：\n\n"
            + "\n".join(pid for pid, _e in dirty)
            + "\n\n是否保存后退出？",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if resp == QMessageBox.Cancel:
            event.ignore()
            return
        if resp == QMessageBox.Save:
            self._save_all()
            if self._dirty_editors():
                event.ignore()
                return
        event.accept()