"""Manual resize grip used by the layer-shell HUD window."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import QWidget


class CustomSizeGrip(QWidget):
    """Resize the explicitly owned HUD window when Qt's native grip is unavailable."""

    def __init__(self, parent: QWidget) -> None:
        """Create a fixed-size grip bound to its parent window."""
        super().__init__(parent)
        self._target = parent
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setStyleSheet("background-color: transparent;")
        self._resizing = False
        self._start_mouse_pos: QPoint | None = None
        self._start_size: QSize | None = None

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        """Capture the pointer and target size when resizing starts."""
        if a0 is None:
            return
        if a0.button() == Qt.MouseButton.LeftButton:
            self._resizing = True
            self._start_mouse_pos = a0.globalPosition().toPoint()
            self._start_size = self._target.size()
            a0.accept()
            return
        super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        """Apply pointer deltas while the left button owns the resize gesture."""
        if a0 is None:
            return
        if self._resizing and self._start_mouse_pos is not None and self._start_size is not None:
            delta = a0.globalPosition().toPoint() - self._start_mouse_pos
            new_width = max(self._target.minimumWidth(), self._start_size.width() + delta.x())
            new_height = max(self._target.minimumHeight(), self._start_size.height() + delta.y())
            self._target.resize(new_width, new_height)
            a0.accept()
            return
        super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        """Release the resize state after the pointer gesture ends."""
        self._resizing = False
        self._start_mouse_pos = None
        self._start_size = None
        super().mouseReleaseEvent(a0)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """Paint the small diagonal grip indicator."""
        del a0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 100)))
        painter.drawEllipse(10, 10, 3, 3)
        painter.drawEllipse(6, 10, 3, 3)
        painter.drawEllipse(10, 6, 3, 3)


__all__ = ("CustomSizeGrip",)
