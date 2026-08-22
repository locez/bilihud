"""Qt presentation adapter for the toolkit-neutral overlay window contract."""

from __future__ import annotations

import PyQt6.sip as sip
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from bilihud.platform.overlay_contracts import WindowHost, WindowPoint, WindowPolicy, WindowRectangle


class QtWindowHost(WindowHost):
    """Translate abstract window operations to one top-level Qt widget."""

    def __init__(self, widget: QWidget, *, full_screen_overlay: bool = False) -> None:
        """Bind one widget and describe whether Layer Shell should fill its output."""
        self._widget = widget
        self._full_screen_overlay: bool = full_screen_overlay
        self._known_position: WindowPoint | None = None

    def apply_window_policy(self, policy: WindowPolicy) -> None:
        """Map platform-selected flags and attributes to Qt."""
        # Clear Qt's input-transparent state before rebuilding normal flags. Qt
        # otherwise keeps WindowTransparentForInput on the recreated surface.
        self._widget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            policy.mouse_events_transparent,
        )
        if policy.recreate_surface:
            self._widget.setWindowFlags(self._base_window_flags(policy))

        self._widget.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            policy.show_without_activating,
        )

    def _base_window_flags(self, policy: WindowPolicy) -> Qt.WindowType:
        """Build the Qt flags that correspond to one abstract policy."""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Window
        )
        if policy.bypass_window_manager:
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        if policy.transparent_for_input:
            flags |= Qt.WindowType.WindowTransparentForInput
        if policy.does_not_accept_focus:
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus
        return flags

    def native_window_pointer(self) -> int | None:
        """Return the opaque QWindow pointer used only inside platform infrastructure."""
        self._widget.winId()
        handle = self._widget.windowHandle()
        if handle is None:
            return None
        try:
            pointer = sip.unwrapinstance(handle)
        except (RuntimeError, TypeError):
            return None
        if pointer is None:
            return None
        return int(pointer)

    def native_window_id(self) -> int | None:
        """Return the X11 window id when Qt exposes one."""
        try:
            return int(self._widget.winId())
        except RuntimeError:
            return None

    def geometry(self) -> WindowRectangle:
        """Return the widget geometry using global top-level coordinates."""
        geometry = self._widget.geometry()
        return self._rectangle(geometry)

    def window_position(self) -> WindowPoint | None:
        """Return an explicit move position before falling back to Qt geometry."""
        if self._known_position is not None:
            return self._known_position
        geometry = self._widget.geometry()
        return WindowPoint(geometry.x(), geometry.y())

    def screen_geometry(self) -> WindowRectangle | None:
        """Return the current screen geometry, falling back to the primary screen."""
        handle = self._widget.windowHandle()
        screen = handle.screen() if handle is not None else QApplication.primaryScreen()
        if screen is None:
            return None
        return self._rectangle(screen.geometry())

    def full_screen_overlay(self) -> bool:
        """Return the explicit Layer Shell anchoring mode for this widget."""
        return self._full_screen_overlay

    def set_geometry(self, geometry: WindowRectangle) -> None:
        """Restore a geometry after Qt recreates a native surface."""
        self._known_position = WindowPoint(geometry.x, geometry.y)
        self._widget.setGeometry(
            QRect(geometry.x, geometry.y, geometry.width, geometry.height)
        )

    def move_window(self, position: WindowPoint) -> None:
        """Move the widget using global coordinates."""
        self._known_position = position
        self._widget.move(position.x, position.y)

    def show_window(self) -> None:
        """Show the bound widget."""
        self._widget.show()

    def hide_window(self) -> None:
        """Hide the bound widget."""
        self._widget.hide()

    def raise_window(self) -> None:
        """Raise the bound widget."""
        self._widget.raise_()

    def activate_window(self) -> None:
        """Request focus for the bound widget."""
        self._widget.activateWindow()

    def start_system_move(self) -> bool:
        """Ask Qt/Wayland to run the compositor-owned move gesture."""
        handle = self._widget.windowHandle()
        if handle is None:
            return False
        try:
            # Qt versions without this Wayland capability raise AttributeError here.
            return bool(handle.startSystemMove())
        except (AttributeError, RuntimeError):
            return False

    def refresh(self) -> None:
        """Request a repaint after a native policy update."""
        self._widget.update()

    @staticmethod
    def _rectangle(rectangle: QRect) -> WindowRectangle:
        """Convert a Qt rectangle at the presentation boundary."""
        return WindowRectangle(
            x=rectangle.x(),
            y=rectangle.y(),
            width=rectangle.width(),
            height=rectangle.height(),
        )
