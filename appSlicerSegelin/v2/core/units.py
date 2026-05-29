"""Locale-safe numeric parsing.

The legacy app sprinkles ``texto.replace(",", ".")`` everywhere and
calls ``float()`` directly, which:

* fails on perfectly valid scientific notation like ``"1e-3"`` when the
  user's locale uses ``,`` as the decimal separator and the string is
  ``"1,0e-3"``,
* leaves no single entry point to reason about valid input.

``parse_float`` is the single entry point everywhere in v2.
"""
from __future__ import annotations

import math
from typing import Final

_MM_PER_INCH: Final[float] = 25.4


def parse_float(text: str | float | int | None) -> float:
    """Parse a user-entered number, accepting comma or period decimals.

    Accepts scientific notation (``1e-3``, ``-2.5E+2``) and tolerates
    surrounding whitespace. Returns ``float`` or raises ``ValueError``
    with the offending text — never returns ``NaN``.
    """
    if text is None:
        raise ValueError("empty value")
    if isinstance(text, (int, float)):
        value = float(text)
    else:
        stripped = text.strip().replace(",", ".")
        if not stripped:
            raise ValueError("empty value")
        value = float(stripped)
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"not a finite number: {text!r}")
    return value


def try_parse_float(text: str | float | int | None, default: float | None = None) -> float | None:
    """Like :func:`parse_float` but returns ``default`` on failure."""
    try:
        return parse_float(text)
    except (ValueError, TypeError):
        return default


def mm_from_inches(value: float) -> float:
    return value * _MM_PER_INCH


def inches_from_mm(value: float) -> float:
    return value / _MM_PER_INCH
