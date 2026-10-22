"""公式引擎：全游戏所有数值公式统一从这里求值。

新增 `_DotDict`：支持 vars.friend_chat 这种点访问的 dict 包装，
缺失键返回 0。用于剧情变量在 simpleeval 公式中直接点访问。
"""
from __future__ import annotations

import keyword
import re

from simpleeval import simple_eval, DEFAULT_FUNCTIONS

_FUNCS: dict = dict(DEFAULT_FUNCTIONS)
_FUNCS.update({"max": max, "min": min, "abs": abs, "round": round})

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_SAFE_KEYWORDS = {"and", "or", "not", "in", "is", "True", "False", "None"}


class _DotDict(dict):
    """支持 .key 访问的 dict，缺失键返回 0。

    用于 vars.friend_chat == 1 这类公式。不改原本 dict 行为。
    """

    def __getattr__(self, key: str):
        return self.get(key, 0)


def _sanitize(expr: str, ctx: dict) -> tuple[str, dict]:
    names = dict(ctx)

    def repl(m: "re.Match[str]") -> str:
        w = m.group(0)
        if keyword.iskeyword(w) and w not in _SAFE_KEYWORDS:
            names.setdefault("kw_" + w, names.get(w, 0))
            return "kw_" + w
        return w

    return _IDENT_RE.sub(repl, expr), names


def ev(expr: str, ctx: dict) -> float:
    try:
        expr, names = _sanitize(str(expr), ctx)
        return simple_eval(expr, names=names, functions=_FUNCS)
    except Exception as e:  # noqa: BLE001
        print(f"[公式错误] {expr} -> {e}")
        return 0