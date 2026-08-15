"""Qt-facing controller for overlay platform modes and window dragging."""

from __future__ import annotations

import logging
from typing import Protocol

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QMouseEvent
from PyQt6.QtWidgets import QListWidget, QPushButton, QSystemTrayIcon, QWidget

from bilihud.platform.overlay_contracts import (
    DragMode,
    OverlayOperationResult,
    OverlayPlatform,
    WindowPoint,
)
from bilihud.ui.hud.input import ModernInputWidget

logger = logging.getLogger(__name__)


class WindowModeView(Protocol):
    """Presentation controls updated by the platform mode controller."""

    is_gaming_mode: bool
    dragging: bool
    gaming_mode_btn: QPushButton
    header_widget: QWidget
    input_area: ModernInputWidget
    danmaku_list: QListWidget
    tray_icon: QSystemTrayIcon
    tray_gaming_action: QAction

    def update_tray_menu_state(self) -> None:
        """Refresh the tray snapshot after a window mode transition."""
        ...

    def sync_audience_visibility(self) -> None:
        """Apply mode-dependent audience popup visibility."""
        ...


class WindowModeController:
    """Translate platform capabilities into overlay UI state and drag commands."""

    def __init__(self, view: WindowModeView, platform: OverlayPlatform) -> None:
        """Create a controller around an injected platform capability boundary."""
        self._view = view
        self._platform = platform

    def activate_layer_shell(self) -> OverlayOperationResult:
        """Finish platform activation after the Qt surface has been mapped."""
        result = self._platform.activate()
        self.update_availability()
        if not result.succeeded:
            logger.warning("Platform window activation failed: %s", result.reason)
        return result

    def is_available(self) -> bool:
        """Return whether gaming mode is supported by the selected platform."""
        return self._platform.capabilities.gaming_mode

    def update_availability(self) -> None:
        """Bind capability state to the window and tray controls."""
        available = self.is_available()
        button = self._view.gaming_mode_btn
        if not available:
            button.setEnabled(False)
            button.setText("穿透不可用")
            button.setChecked(False)
            reason = self._platform.capabilities.unavailable_reason or "当前平台不支持"
            button.setToolTip(f"游戏模式不可用: {reason}\n当前仍可使用普通窗口模式。")
        else:
            button.setEnabled(True)
            button.setText("锁定穿透")
            button.setToolTip("")
        self._view.update_tray_menu_state()

    def toggle_from_tray(self, checked: bool) -> None:
        """Apply a checked state requested by the tray menu."""
        if checked and not self.is_available():
            self.show_unavailable_message()
            self._view.tray_gaming_action.setChecked(False)
            return
        if self._view.is_gaming_mode != checked:
            self.set_gaming_mode(checked)

    def toggle(self) -> None:
        """Toggle gaming mode from the HUD button."""
        enabled = not self._view.is_gaming_mode
        if enabled and not self.is_available():
            self.show_unavailable_message()
            self._view.gaming_mode_btn.setChecked(False)
            return
        self.set_gaming_mode(enabled)

    def show_unavailable_message(self, reason: str | None = None) -> None:
        """Explain a platform limitation without disabling ordinary window use."""
        limitation = reason or self._platform.capabilities.unavailable_reason or "当前平台不支持游戏模式"
        self._view.tray_icon.showMessage(
            "Danmaku Overlay",
            f"{limitation}\n当前仍可使用普通窗口模式。",
            QSystemTrayIcon.MessageIcon.Warning,
            3000,
        )

    def set_gaming_mode(self, enabled: bool) -> OverlayOperationResult:
        """Apply a platform mode transition and synchronize all related controls."""
        previous_state = self._view.is_gaming_mode
        result = self._platform.set_gaming_mode(enabled)
        if not result.succeeded:
            self._view.gaming_mode_btn.setChecked(previous_state)
            self._view.tray_gaming_action.setChecked(previous_state)
            logger.warning("Gaming mode transition failed: %s", result.reason)
            self.show_unavailable_message(result.reason)
            return result

        self._view.is_gaming_mode = enabled
        self._view.tray_gaming_action.setChecked(enabled)
        self._view.gaming_mode_btn.setChecked(enabled)
        if enabled:
            self._view.header_widget.hide()
            self._view.input_area.hide()
            self._view.danmaku_list.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._view.danmaku_list.setStyleSheet(
                """
                QListWidget {
                    background: transparent;
                    border: 2px dashed rgba(255, 255, 255, 30);
                    border-radius: 8px;
                }
                """
            )
            self._view.tray_icon.showMessage(
                "Danmaku Overlay",
                "已进入穿透模式 (游戏覆盖)\n弹幕将显示在最顶层，鼠标操作将穿透。",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
        else:
            self._view.header_widget.show()
            self._view.input_area.show()
            self._view.danmaku_list.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            self._view.danmaku_list.setStyleSheet("background: transparent; border: none;")

        self._view.sync_audience_visibility()
        self._view.update_tray_menu_state()
        return result

    def mouse_press(self, event: QMouseEvent | None) -> None:
        """Begin platform-aware dragging when the overlay is interactive."""
        if event is None or self._view.is_gaming_mode:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        local = event.position().toPoint()
        global_position = event.globalPosition().toPoint()
        result = self._platform.begin_drag(
            WindowPoint(local.x(), local.y()),
            WindowPoint(global_position.x(), global_position.y()),
        )
        if result.mode is DragMode.UNAVAILABLE:
            logger.warning("Window drag unavailable: %s", result.reason)
            return
        self._view.dragging = result.mode is DragMode.MANUAL
        event.accept()

    def mouse_move(self, event: QMouseEvent | None) -> None:
        """Forward manual drag updates to the platform adapter."""
        if event is None or not self._view.dragging:
            return
        local = event.position().toPoint()
        global_position = event.globalPosition().toPoint()
        result = self._platform.update_drag(
            WindowPoint(local.x(), local.y()),
            WindowPoint(global_position.x(), global_position.y()),
        )
        if not result.succeeded:
            logger.warning("Window drag update failed: %s", result.reason)
        event.accept()

    def mouse_release(self) -> None:
        """Finish the platform drag operation and clear local drag state."""
        self._platform.end_drag()
        self._view.dragging = False


__all__ = ("WindowModeController", "WindowModeView")
