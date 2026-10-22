"""逻辑入口：由 __main__.py 或未来打包脚本调用。"""
from __future__ import annotations


def main() -> int:
    """启动 GUI，返回进程退出码。"""
    from .app import run_app

    return run_app()


if __name__ == "__main__":
    import sys

    sys.exit(main())