"""Rendering adapter for typed HUD state and event contracts."""

from __future__ import annotations

from typing import Protocol

from PyQt6.QtWidgets import QLineEdit, QPushButton, QWidget

from bilihud.app.hud import (
    HudConnectionStatus,
    HudEvent,
    HudLoginFailed,
    HudMessageReceived,
    HudOperationFailed,
    HudState,
    HudStateChanged,
)
from bilihud.danmaku.messages import HudMessage, SystemMessageLevel
from bilihud.ui.hud.audience import AudiencePopup, AudienceStatusWidget


class HudStateView(Protocol):
    """Controls and callbacks required to render one HUD state snapshot."""

    _hud_state: HudState
    room_id: int
    is_gaming_mode: bool
    room_id_input: QLineEdit
    connect_button: QPushButton
    audience_status: AudienceStatusWidget
    audience_popup: AudiencePopup
    popup_parent: QWidget

    def on_message_received(self, message: HudMessage) -> None:
        """Forward one normalized message to the HUD message path."""
        ...

    def on_login_failed(self, message: str) -> None:
        """Forward an authentication failure to the account presentation bridge."""
        ...

    def add_system_message(self, message: str, level: SystemMessageLevel) -> None:
        """Render one local system notice."""
        ...

    def update_tray_menu_state(self) -> None:
        """Refresh tray state after a HUD transition."""
        ...


class HudStateRenderer:
    """Bind immutable application HUD state to the existing Qt controls."""

    def __init__(self, view: HudStateView) -> None:
        """Create the renderer around one presentation view."""
        self._view = view

    def handle_event(self, event: HudEvent) -> None:
        """Translate one typed controller event into rendering or notification calls."""
        if isinstance(event, HudStateChanged):
            self.bind_state(event.state)
        elif isinstance(event, HudMessageReceived):
            self._view.on_message_received(event.message)
        elif isinstance(event, HudLoginFailed):
            self._view.on_login_failed(event.message)
        elif isinstance(event, HudOperationFailed):
            self._view.add_system_message(event.message, SystemMessageLevel.ERROR)

    def open_audience_popup(self) -> None:
        """Show the audience snapshot below its HUD control when available."""
        snapshot = self._view._hud_state.audience_snapshot
        if snapshot is None or self._view.is_gaming_mode:
            return
        self._view.audience_popup.set_snapshot(snapshot)
        self._view.audience_popup.show_below(
            self._view.audience_status.online_button,
            self._view.popup_parent,
        )

    def sync_audience_visibility(self) -> None:
        """Hide audience controls while gaming mode or missing state prevents interaction."""
        visible = self._view._hud_state.audience_snapshot is not None and not self._view.is_gaming_mode
        self._view.audience_status.setVisible(visible)
        if not visible:
            self._view.audience_popup.hide()

    def bind_state(self, state: HudState) -> None:
        """Render a complete snapshot without reading third-party network objects."""
        previous_room_id = self._view._hud_state.room_id
        self._view._hud_state = state
        if state.room_id is not None and state.room_id != previous_room_id:
            self._view.room_id = state.room_id
            self._view.room_id_input.setText(str(state.room_id))

        if state.connection is HudConnectionStatus.CONNECTING:
            self._set_connecting()
        elif state.connection is HudConnectionStatus.DISCONNECTING:
            self._set_disconnecting()
        elif state.connection is HudConnectionStatus.CONNECTED:
            self._set_connected()
        else:
            self._set_disconnected()

        snapshot = state.audience_snapshot
        if snapshot is None:
            self._view.audience_popup.hide()
            self._view.audience_status.clear()
        else:
            self._view.audience_status.set_snapshot(snapshot)
            self._view.audience_popup.set_snapshot(snapshot)
        self.sync_audience_visibility()
        self._view.update_tray_menu_state()

    def _set_connecting(self) -> None:
        """Render the connecting HUD state."""
        self._view.connect_button.setText("连接中...")
        self._view.connect_button.setEnabled(False)

    def _set_disconnecting(self) -> None:
        """Render the disconnecting HUD state."""
        self._view.connect_button.setText("断开中...")
        self._view.connect_button.setChecked(True)
        self._view.connect_button.setEnabled(False)

    def _set_connected(self) -> None:
        """Render the connected HUD state."""
        self._view.connect_button.setText("断开")
        self._view.connect_button.setChecked(True)
        self._view.connect_button.setEnabled(True)
        self._view.connect_button.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(244, 67, 54, 150);
                color: white;
                border: 1px solid rgba(244, 67, 54, 200);
                border-radius: 6px; padding: 4px 10px;
            }
            QPushButton:hover { background-color: rgba(244, 67, 54, 200); }
            """
        )

    def _set_disconnected(self) -> None:
        """Render the disconnected HUD state."""
        self._view.connect_button.setText("连接")
        self._view.connect_button.setChecked(False)
        self._view.connect_button.setEnabled(True)
        self._view.connect_button.setStyleSheet(
            """
            QPushButton {
                color: white;
                background-color: rgba(255, 255, 255, 20);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 6px;
                padding: 4px 10px;
            }
            QPushButton:hover { background-color: rgba(255, 255, 255, 40); }
            QPushButton:checked { background-color: rgba(76, 175, 80, 150); }
            """
        )


__all__ = ("HudStateRenderer", "HudStateView")
