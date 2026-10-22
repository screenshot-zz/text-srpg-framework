"""备份机制：保存前生成带时间戳的 .bak，保留最近 20 份。

备份位置（方案 6.5 指定）：
    config/.backup/{filename}.{YYYYMMDD_HHMMSS}.bak

只写 .bak，不动任何 .yaml —— 不违反"只动 config 下的 yaml 文件"这条红线。
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


class Backup:
    KEEP = 20
    BACKUP_DIR_NAME = ".backup"

    # ---------- 路径 ----------

    @classmethod
    def _backup_dir(cls, source: Path) -> Path:
        return source.parent / cls.BACKUP_DIR_NAME

    @classmethod
    def backup_dir(cls, source: str | Path) -> Path:
        """对外暴露：给「打开备份目录」按钮用。

        Backup.backup_dir(Path("config/status.yaml"))
            -> Path("config/.backup")
        """
        return cls._backup_dir(Path(source))

    # ---------- 生成 ----------

    @classmethod
    def create(cls, source: str | Path) -> Path:
        """生成一份 .bak，返回新文件路径。超 KEEP 份自动删最旧。"""
        src = Path(source)
        if not src.exists():
            raise FileNotFoundError(f"无法备份，源文件不存在：{src}")

        bdir = cls._backup_dir(src)
        bdir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = bdir / f"{src.name}.{ts}.bak"
        n = 1
        # 同一秒内多次保存（Ctrl+S 连按）时加后缀
        while target.exists():
            target = bdir / f"{src.name}.{ts}_{n}.bak"
            n += 1
        shutil.copy2(src, target)

        cls._cleanup(bdir, src.name)
        return target

    # ---------- 清理 ----------

    @classmethod
    def _cleanup(cls, bdir: Path, filename: str) -> None:
        """保留最近 KEEP 份，删最旧的。"""
        pattern = f"{filename}.*.bak"
        files = sorted(
            bdir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[cls.KEEP:]:
            try:
                old.unlink()
            except OSError:
                pass