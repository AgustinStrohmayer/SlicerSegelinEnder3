"""Non-modal toast notifications.

Replaces the legacy ``messagebox.showinfo/error`` pop-ups with a
stack of auto-dismissed bubbles in the top-right corner of the main
window. Errors stay until clicked; successes auto-dismiss.
"""
from __future__ import annotations

from typing import Literal

from PyQt6.QtCore import QPropertyAnimation, Qt, QTimer
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

Severity = Literal["info", "success", "warning", "danger"]

# At most this many toasts are kept on screen; older ones fade out so the
# stack never grows past the window height.
MAX_VISIBLE = 4


class _ElidingLabel(QLabel):
    """A single-line label that middle-elides text too wide for the card.

    Toast bodies are often file names/paths. A long unbroken token can't be
    word-wrapped, so we elide in the middle ("verylong…name.gcode") to keep
    both the start and the extension legible while staying inside the card.
    """

    def __init__(self, text: str) -> None:
        super().__init__()
        self._full = text
        super().setText(text)

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full = text
        self._elide()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(0, self.width())
        elided = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, width)
        # Bypass our own override so this doesn't recurse.
        QLabel.setText(self, elided)
        if elided != self._full:
            self.setToolTip(self._full)


class ToastHost(QWidget):
    """Floating container that stacks toasts in the top-right corner."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("ToastHost")
        # Pass mouse events through the (invisible) host to the canvas below;
        # the individual toast cards stay clickable as opaque children.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(8)
        self._layout.setContentsMargins(0, 0, 0, 0)
        # Scope the transparency to the host only — an unscoped "background:
        # transparent" cascades to the toast cards and makes them see-through.
        self.setStyleSheet("QWidget#ToastHost { background: transparent; }")
        self.raise_()
        if parent is not None:
            parent.installEventFilter(self)
        self._reposition()

    def _reposition(self) -> None:
        if self.parent() is None:
            return
        parent = self.parent()
        parent_rect = parent.rect()  # type: ignore[union-attr]
        w = 360
        h = max(64, self._layout.sizeHint().height())
        self.setGeometry(parent_rect.right() - w - 24, parent_rect.top() + 24, w, h)

    def eventFilter(self, obj, event):  # type: ignore[override]
        if event.type() in (event.Type.Resize, event.Type.Move):
            self._reposition()
        return super().eventFilter(obj, event)

    def show_toast(self, title: str, body: str = "", severity: Severity = "info", duration_ms: int = 3500) -> None:
        toast = _Toast(title, body, severity)
        self._layout.addWidget(toast)
        self._reposition()
        toast.dismissed.connect(lambda t=toast: self._remove(t))
        if severity != "danger":
            QTimer.singleShot(duration_ms, toast.fade_out)
        self._enforce_cap()

    def _enforce_cap(self) -> None:
        live = [self._layout.itemAt(i).widget() for i in range(self._layout.count())]
        live = [w for w in live if w is not None]
        for w in live[:-MAX_VISIBLE]:  # fade the oldest until at most MAX_VISIBLE remain
            if not w.is_closing():
                w.fade_out()

    def _remove(self, toast: _Toast) -> None:
        self._layout.removeWidget(toast)
        toast.deleteLater()
        self._reposition()


class _Toast(QFrame):
    from PyQt6.QtCore import pyqtSignal

    dismissed = pyqtSignal()

    def __init__(self, title: str, body: str, severity: Severity) -> None:
        super().__init__()
        self.setObjectName("Toast")
        self.setProperty("severity", severity)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMaximumWidth(336)  # stay within the 360px host, never off-window
        self._closing = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        t = QLabel(title)
        t.setProperty("role", "title")
        t.setWordWrap(True)
        text_col.addWidget(t)
        if body:
            # Eliding label: long unbroken file names stay inside the card
            # instead of being clipped mid-word at the right edge.
            b = _ElidingLabel(body)
            b.setProperty("class", "muted")
            text_col.addWidget(b)
        outer.addLayout(text_col, 1)

        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def is_closing(self) -> bool:
        return self._closing

    def fade_out(self) -> None:
        if self._closing:
            return
        self._closing = True
        out = QPropertyAnimation(self._fx, b"opacity", self)
        out.setDuration(220)
        out.setStartValue(self._fx.opacity())
        out.setEndValue(0.0)
        out.finished.connect(self.dismissed.emit)
        out.start()
        self._anim = out  # keep reference

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self.fade_out()
