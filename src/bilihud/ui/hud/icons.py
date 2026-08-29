"""HUD control icons rendered from open-source SVG (Lucide, ISC license).

Lucide stroke icons are recoloured and rasterised via QtSvg so the HUD keeps
the same clean control language on desktops without an installed icon theme.
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

ICON_SIZE = 64
CONTROL_ICON_COLOR = "#9AA0A6"

_SVG_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
)

# Lucide: lock
_LOCK = _SVG_HEAD + (
    '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>'
    '<path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
)
# Lucide: lock-open
_UNLOCK = _SVG_HEAD + (
    '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>'
    '<path d="M7 11V7a5 5 0 0 1 9.9-1"/></svg>'
)
# Lucide: settings-2
_SETTINGS = _SVG_HEAD + (
    '<path d="M20 7h-9"/><path d="M14 17H5"/>'
    '<circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/></svg>'
)
_EARLIER = _SVG_HEAD + '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg>'
_LATER = _SVG_HEAD + '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>'
_SEND = _SVG_HEAD + '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>'
_SMILE = _SVG_HEAD + (
    '<circle cx="12" cy="12" r="10"/>'
    '<path d="M8 14s1.5 2 4 2 4-2 4-2"/>'
    '<path d="M9 9h.01"/><path d="M15 9h.01"/></svg>'
)


def _render(svg: str, color: str) -> QIcon:
    """Rasterise one internal SVG into a theme-independent Qt icon."""
    data = QByteArray(svg.replace("currentColor", color).encode("utf-8"))
    renderer = QSvgRenderer(data)
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def lock_icon(closed: bool, color: str = CONTROL_ICON_COLOR) -> QIcon:
    """Return a Lucide closed or open lock icon."""
    return _render(_LOCK if closed else _UNLOCK, color)


def settings_icon(color: str = CONTROL_ICON_COLOR) -> QIcon:
    """Return the two-slider settings icon."""
    return _render(_SETTINGS, color)


def earlier_icon(color: str = CONTROL_ICON_COLOR) -> QIcon:
    """Return the left-facing connection/disconnect arrow."""
    return _render(_EARLIER, color)


def later_icon(color: str = CONTROL_ICON_COLOR) -> QIcon:
    """Return the right-facing connection arrow."""
    return _render(_LATER, color)


def send_icon(color: str = "#FFFFFF") -> QIcon:
    """Return the paper-plane icon for the primary send action."""
    return _render(_SEND, color)


def smile_icon(color: str = CONTROL_ICON_COLOR) -> QIcon:
    """Return the outline smile icon for the emoticon picker."""
    return _render(_SMILE, color)


__all__ = (
    "CONTROL_ICON_COLOR",
    "ICON_SIZE",
    "earlier_icon",
    "later_icon",
    "lock_icon",
    "send_icon",
    "settings_icon",
    "smile_icon",
)
