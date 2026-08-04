"""Stacked settings content sizing helpers."""

from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QStackedWidget, QWidget


class AdaptiveStackedWidget(QStackedWidget):
    """Size a stacked page container from its visible page, not hidden maxima."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create a stack that updates its size hint after a page change."""
        super().__init__(parent)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def sizeHint(self) -> QSize:
        """Return the visible page's preferred size for scrollbar decisions."""
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        """Return the visible page's minimum size instead of hidden page maxima."""
        page = self.currentWidget()
        return page.minimumSizeHint() if page is not None else super().minimumSizeHint()


__all__ = ("AdaptiveStackedWidget",)
