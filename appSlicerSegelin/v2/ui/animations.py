"""Lightweight animation helpers — fade, slide, icon cross-fade.

Qt has no CSS-style transitions; every animation needs a
``QPropertyAnimation``. Centralising the patterns here keeps timing
and easing consistent across the app.
"""
from __future__ import annotations

from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QPoint, QPropertyAnimation
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

DEFAULT_DURATION_MS = 180


def _opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect:
    existing = widget.graphicsEffect()
    if isinstance(existing, QGraphicsOpacityEffect):
        return existing
    fx = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(fx)
    return fx


def fade(widget: QWidget, *, from_: float, to: float, ms: int = DEFAULT_DURATION_MS) -> QPropertyAnimation:
    """Animate the widget's opacity. Returns the animation (kept alive
    on the widget so the caller doesn't need to)."""
    fx = _opacity_effect(widget)
    fx.setOpacity(from_)
    anim = QPropertyAnimation(fx, b"opacity", widget)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.setStartValue(from_)
    anim.setEndValue(to)
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
    widget._fade_anim = anim  # type: ignore[attr-defined]
    return anim


def fade_in(widget: QWidget, ms: int = DEFAULT_DURATION_MS) -> QPropertyAnimation:
    widget.show()
    return fade(widget, from_=0.0, to=1.0, ms=ms)


def fade_out(widget: QWidget, ms: int = DEFAULT_DURATION_MS, *, then_hide: bool = True) -> QPropertyAnimation:
    anim = fade(widget, from_=_opacity_effect(widget).opacity(), to=0.0, ms=ms)
    if then_hide:
        anim.finished.connect(widget.hide)
    return anim


def slide_to(widget: QWidget, target: QPoint, ms: int = 220) -> QPropertyAnimation:
    anim = QPropertyAnimation(widget, b"pos", widget)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.setStartValue(widget.pos())
    anim.setEndValue(target)
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
    widget._slide_anim = anim  # type: ignore[attr-defined]
    return anim


def cross_fade_icon(button, new_icon: QIcon, ms: int = 150) -> None:  # type: ignore[no-untyped-def]
    """Swap a button's icon with a quick opacity dip."""
    fx = _opacity_effect(button)
    anim = QPropertyAnimation(fx, b"opacity", button)
    anim.setDuration(ms // 2)
    anim.setStartValue(1.0)
    anim.setEndValue(0.45)

    def _swap_and_restore() -> None:
        button.setIcon(new_icon)
        back = QPropertyAnimation(fx, b"opacity", button)
        back.setDuration(ms // 2)
        back.setStartValue(0.45)
        back.setEndValue(1.0)
        back.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
        button._icon_anim_back = back  # type: ignore[attr-defined]

    anim.finished.connect(_swap_and_restore)
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
    button._icon_anim = anim  # type: ignore[attr-defined]
