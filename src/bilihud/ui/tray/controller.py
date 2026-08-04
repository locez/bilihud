"""Qt system-tray composition and state binding."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QSystemTrayIcon, QWidget

from bilihud.app.menu import MenuCommand, TrayMenuState

from .menu import TrayMenu

logger = logging.getLogger(__name__)

TrayCommandHandler = Callable[[MenuCommand, bool], None]
TrayStateProvider = Callable[[], TrayMenuState]
TrayActivationHandler = Callable[[QSystemTrayIcon.ActivationReason], None]


class TrayController:
    """Own the system tray surface while delegating commands to the window owner."""

    def __init__(
        self,
        parent: QWidget,
        *,
        state_provider: TrayStateProvider,
        command_handler: TrayCommandHandler,
        activation_handler: TrayActivationHandler,
    ) -> None:
        """Create and show a typed tray menu for one top-level window."""
        self._parent = parent
        self._state_provider = state_provider
        self._tray_icon = QSystemTrayIcon(parent)
        self._tray_menu = TrayMenu(parent)
        self._tray_menu.command_requested.connect(command_handler)
        self._tray_icon.activated.connect(activation_handler)
        self._tray_icon.setContextMenu(self._tray_menu)
        self._actions: dict[MenuCommand, QAction] = {
            command: self._tray_menu.action_for(command) for command in MenuCommand
        }
        self._setup_icon()
        self._tray_icon.show()

    @property
    def icon(self) -> QSystemTrayIcon:
        """Return the owned Qt tray icon."""
        return self._tray_icon

    @property
    def menu(self) -> TrayMenu:
        """Return the typed menu surface rendered by this controller."""
        return self._tray_menu

    def action_for(self, command: MenuCommand) -> QAction:
        """Return one stable action for compatibility and focused callers."""
        return self._actions[command]

    def refresh(self) -> None:
        """Render the latest immutable application tray snapshot."""
        self._tray_menu.set_state(self._state_provider())

    def close(self) -> None:
        """Hide the tray icon before the application releases its Qt resources."""
        self._tray_icon.hide()

    def _setup_icon(self) -> None:
        """Load the application icon and preserve a usable tray without the asset."""
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "icon.png"
        if not icon_path.exists():
            logger.warning("Icon not found at %s", icon_path)
            return
        icon = QIcon(str(icon_path))
        self._tray_icon.setIcon(icon)
        self._parent.setWindowIcon(icon)


__all__ = ("TrayController",)
