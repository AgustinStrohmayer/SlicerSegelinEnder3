"""Reusable graphical effects that QSS cannot express.

Qt's QSS engine ignores ``box-shadow`` and CSS transitions, so the
elevation system from :mod:`tokens` is realised here by attaching a
``QGraphicsDropShadowEffect`` to widgets that should appear lifted
above the surface (toasts, palette, overlays, floating canvas
controls).
"""
from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from .tokens import ShadowSpec, Tokens


def apply_shadow(widget: QWidget, spec: ShadowSpec) -> QGraphicsDropShadowEffect:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(spec.radius)
    effect.setOffset(0, spec.offset_y)
    effect.setColor(_qcolor(spec.color))
    widget.setGraphicsEffect(effect)
    return effect


def apply_elevation(widget: QWidget, tokens: Tokens, level: str = "md") -> QGraphicsDropShadowEffect:
    """Convenience: ``apply_elevation(w, tokens, "lg")``."""
    spec = getattr(tokens.shadow, level)
    return apply_shadow(widget, spec)


def _qcolor(value: str) -> QColor:
    """Parse hex (#RRGGBB / #RRGGBBAA) or ``rgba(…)`` into a QColor."""
    value = value.strip()
    if value.startswith("#"):
        if len(value) == 9:  # #RRGGBBAA
            r = int(value[1:3], 16)
            g = int(value[3:5], 16)
            b = int(value[5:7], 16)
            a = int(value[7:9], 16)
            return QColor(r, g, b, a)
        return QColor(value)
    if value.startswith("rgba"):
        inside = value[value.index("(") + 1 : value.rindex(")")]
        parts = [p.strip() for p in inside.split(",")]
        r, g, b = (int(parts[0]), int(parts[1]), int(parts[2]))
        a = round(float(parts[3]) * 255) if len(parts) > 3 else 255
        return QColor(r, g, b, a)
    return QColor(value)
