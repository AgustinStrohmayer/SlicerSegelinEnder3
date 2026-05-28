"""Render the active theme's QSS file with token substitution.

We avoid pulling Jinja for one curly-brace pattern. ``{{token.name}}``
in the QSS file is replaced by the value at ``getattr(tokens.<group>,
<field>)``. Unknown placeholders raise — silent typos in QSS are
miserable to debug.
"""
from __future__ import annotations

import re
from pathlib import Path

from .tokens import ThemeName, Tokens, get_tokens

_THEMES_DIR = Path(__file__).parent / "themes"
_PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def render_qss(theme: ThemeName) -> str:
    tokens = get_tokens(theme)
    template = (_THEMES_DIR / f"{theme}.qss").read_text(encoding="utf-8")
    return _PLACEHOLDER.sub(lambda m: _resolve(tokens, m.group(1)), template)


def _resolve(tokens: Tokens, path: str) -> str:
    parts = path.split(".")
    obj: object = tokens
    for part in parts:
        if not hasattr(obj, part):
            raise KeyError(f"Unknown token reference: {path!r}")
        obj = getattr(obj, part)
    return str(obj)
