"""Qt binding for the typed application tray-menu contract."""

from __future__ import annotations

from functools import partial

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QWidget

from bilihud.app.menu import MenuCommand, TrayMenuState, tray_action_states


class TrayMenu(QMenu):
    """Render tray actions and emit typed commands without executing workflows."""

    command_requested = pyqtSignal(object, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create a stable action tree whose state can be refreshed independently."""
        super().__init__(parent)
        self._actions_by_command: dict[MenuCommand, QAction] = {}
        self._build_actions()
        self.set_theme(True)

    def _build_actions(self) -> None:
        """Create QAction objects and connect them only to the command signal."""
        send_action = self._add_command_action(MenuCommand.SEND_DANMAKU)
        self.addAction(send_action)
        self.addAction(self._add_command_action(MenuCommand.OPEN_LIVE_SETTINGS))
        self.addAction(self._add_command_action(MenuCommand.TOGGLE_VISIBILITY))
        self.addAction(self._add_command_action(MenuCommand.TOGGLE_GAMING_MODE, checkable=True))
        self.addSeparator()
        self.addAction(self._add_command_action(MenuCommand.OPEN_LOGIN))
        self.addAction(self._add_command_action(MenuCommand.OPEN_SETTINGS))
        self.addSeparator()
        self.addAction(self._add_command_action(MenuCommand.QUIT))

    def _add_command_action(self, command: MenuCommand, *, checkable: bool = False) -> QAction:
        action = QAction(self)
        action.setCheckable(checkable)
        action.triggered.connect(partial(self._emit_command, command))
        self._actions_by_command[command] = action
        return action

    def _emit_command(self, command: MenuCommand, checked: bool = False) -> None:
        """Forward one QAction event as a typed command request."""
        self.command_requested.emit(command, checked)

    def set_state(self, state: TrayMenuState) -> None:
        """Render labels, availability, and check state from one immutable snapshot."""
        for item in tray_action_states(state):
            action = self._actions_by_command[item.command]

            action.setText(item.label)
            action.setEnabled(item.enabled)
            action.setCheckable(item.checkable)
            action.setChecked(item.checked)
            action.setToolTip(item.disabled_reason or item.label)

    def action_for(self, command: MenuCommand) -> QAction:
        """Return the QAction bound to a command for presentation tests and state binding."""
        return self._actions_by_command[command]

    def set_theme(self, dark: bool) -> None:
        """Apply the fixed dark palette used by the lightweight tray surface."""
        if dark:
            background = "#1d2026"
            foreground = "#f4f5f7"
            border = "#3a3f49"
            hover = "#343a45"
            disabled = "#7f8793"
        else:
            background = "#ffffff"
            foreground = "#20232a"
            border = "#dfe3ea"
            hover = "#f0f2f6"
            disabled = "#9aa1ad"
        self.setStyleSheet(
            f"""
            QMenu {{
                background-color: {background};
                color: {foreground};
                border: 1px solid {border};
                padding: 6px;
            }}
            QMenu::item {{
                padding: 8px 14px 8px 8px;
                border-radius: 5px;
            }}
            QMenu::indicator {{
                width: 14px;
                height: 14px;
                margin: 0 4px 0 0;
            }}
            QMenu::item:selected {{
                background-color: {hover};
            }}
            QMenu::item:disabled {{
                color: {disabled};
            }}
            QMenu::separator {{
                height: 1px;
                background: {border};
                margin: 5px 8px;
            }}
            """
        )


__all__ = ("TrayMenu",)
