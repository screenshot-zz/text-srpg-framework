"""使 `python -m tools.yaml_editor` 可执行。"""
from __future__ import annotations

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())