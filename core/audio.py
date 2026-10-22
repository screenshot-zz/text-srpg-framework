"""音频播放：有 pygame 用 pygame，没有就静默跳过。

设计原则：
- 有文件才播，没文件静默跳过
- 同一曲目不重复播放
- 播放失败静默（不打断游戏）
- pygame 是可选依赖，没装就完全不播，游戏照常运行

路径约定：传入绝对路径。调用方负责拼接 BASE_DIR。
"""
from __future__ import annotations

import os

try:
    import pygame
    _HAS_PYGAME = True
except ImportError:
    _HAS_PYGAME = False


class AudioPlayer:
    """极简 BGM 播放器。所有失败静默。"""

    def __init__(self) -> None:
        self.current: str | None = None
        self._initialized = False
        self._warned = False

    # ---------- 内部 ----------

    def _ensure_init(self) -> bool:
        if not _HAS_PYGAME:
            if not self._warned:
                print("[BGM] 未安装 pygame，音乐功能已跳过（pip install pygame 可启用）")
                self._warned = True
            return False
        if self._initialized:
            return True
        try:
            pygame.mixer.init()
            self._initialized = True
            return True
        except Exception:
            self._warned = True
            return False

    # ---------- 对外 ----------

    def play(self, path: str | None, loop: bool = True) -> bool:
        """播放音乐。返回是否真的在播放。

        - path 为空 / 文件不存在 → False，不报错
        - 同一路径已播放 → True（不重播）
        - 初始化失败 / 加载失败 → False，不报错
        """
        if not path:
            return False
        if not os.path.exists(path):
            return False
        if self.current == path:
            return True
        if not self._ensure_init():
            return False
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play(-1 if loop else 0)
            self.current = path
            return True
        except Exception:
            return False

    def stop(self) -> None:
        if not _HAS_PYGAME or not self._initialized:
            self.current = None
            return
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self.current = None