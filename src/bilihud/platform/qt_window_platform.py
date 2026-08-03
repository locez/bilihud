"""Portable Qt window behavior shared by platform providers and fallbacks."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer

from .overlay_contracts import (
    DragMode,
    DragStartResult,
    OverlayCapabilities,
    OverlayOperationResult,
    OverlayPlatform,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)
from .x11 import X11InputShape

logger = logging.getLogger(__name__)


class _ManualWindowDragStrategy:
    """Move a normal Qt window from a pointer anchor when system move is unavailable."""

    def __init__(self, host: WindowHost, *, prefer_system_move: bool) -> None:
        self._host = host
        self._prefer_system_move = prefer_system_move
        self._drag_local_position: WindowPoint | None = None

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> DragStartResult:
        """Prefer compositor-owned movement, then retain a manual fallback."""
        del global_position
        if self._prefer_system_move and self._host.start_system_move():
            return DragStartResult(DragMode.SYSTEM)
        self._drag_local_position = local_position
        return DragStartResult(DragMode.MANUAL)

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> OverlayOperationResult:
        """Move the window using the original local pointer anchor."""
        del local_position
        drag_local_position = self._drag_local_position
        if drag_local_position is None:
            return OverlayOperationResult.failure("普通窗口拖动尚未开始")
        self._host.move_window(
            global_position.offset(-drag_local_position.x, -drag_local_position.y)
        )
        return OverlayOperationResult.success()

    def end_drag(self) -> None:
        """Release the manual drag anchor."""
        self._drag_local_position = None


def _normal_window_policy() -> WindowPolicy:
    """Return the stable policy used by every normal Qt window."""
    return WindowPolicy(recreate_surface=True)


def _gaming_window_policy(*, bypass_window_manager: bool) -> WindowPolicy:
    """Return the Qt policy for a topmost, input-transparent window."""
    return WindowPolicy(
        bypass_window_manager=bypass_window_manager,
        transparent_for_input=True,
        does_not_accept_focus=True,
        show_without_activating=True,
        mouse_events_transparent=True,
        recreate_surface=True,
    )


class QtWindowPlatform(OverlayPlatform):
    """Provide portable Qt window behavior with optional native enhancements."""

    def __init__(
        self,
        host: WindowHost,
        *,
        gaming_mode_supported: bool,
        gaming_mode_reason: str | None,
        bypass_window_manager: bool,
        click_through: X11InputShape | None,
        click_through_supported: bool,
        prefer_system_move: bool,
        restore_delay_ms: int = 0,
    ) -> None:
        self._host = host
        self._gaming_mode_supported = gaming_mode_supported
        self._gaming_mode_reason = gaming_mode_reason
        self._bypass_window_manager = bypass_window_manager
        self._click_through = click_through
        self._gaming_mode = False
        self._restore_delay_ms = restore_delay_ms
        self._restore_generation = 0
        self._drag_strategy = _ManualWindowDragStrategy(
            host,
            prefer_system_move=prefer_system_move,
        )
        self._capabilities = OverlayCapabilities(
            layer_shell=False,
            gaming_mode=gaming_mode_supported,
            click_through=click_through_supported,
            drag=True,
            unavailable_reason=gaming_mode_reason if not gaming_mode_supported else None,
        )

    @property
    def capabilities(self) -> OverlayCapabilities:
        """Return the portable Qt capabilities and any unavailable feature reason."""
        return self._capabilities

    def prepare(self) -> OverlayOperationResult:
        """Apply the normal window policy before the Qt surface is shown."""
        try:
            self._host.apply_window_policy(_normal_window_policy())
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"窗口初始化失败: {exc}")
        return OverlayOperationResult.success()

    def activate(self) -> OverlayOperationResult:
        """Complete portable activation after the Qt surface has been mapped."""
        return OverlayOperationResult.success()

    def set_gaming_mode(self, enabled: bool) -> OverlayOperationResult:
        """Recreate a normal Qt surface with the requested input policy."""
        if not self._gaming_mode_supported:
            reason = self._gaming_mode_reason
            if reason is None:
                reason = "当前平台不支持游戏模式"
            return OverlayOperationResult.failure(reason)

        geometry = self._host.geometry()
        previous_mode = self._gaming_mode
        try:
            self._host.hide_window()
            policy = (
                _gaming_window_policy(bypass_window_manager=self._bypass_window_manager)
                if enabled
                else _normal_window_policy()
            )
            self._host.apply_window_policy(policy)
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"窗口模式切换失败: {exc}")

        self._gaming_mode = enabled
        self._restore_generation += 1
        generation = self._restore_generation
        if self._restore_delay_ms > 0:
            # X11 may recreate the native surface when flags change. Wait for
            # the new surface to be mapped before restoring geometry and shape.
            def restore_window_state() -> None:
                if generation != self._restore_generation:
                    return
                result = self._restore_window_state(geometry, enabled)
                if not result.succeeded:
                    self._gaming_mode = previous_mode
                    logger.warning("窗口模式延迟恢复失败: %s", result.reason)

            QTimer.singleShot(self._restore_delay_ms, restore_window_state)
            return OverlayOperationResult.success()

        result = self._restore_window_state(geometry, enabled)
        if not result.succeeded:
            self._gaming_mode = previous_mode
            return result
        return OverlayOperationResult.success()

    def _restore_window_state(
        self,
        geometry: WindowRectangle,
        enabled: bool,
    ) -> OverlayOperationResult:
        """Restore a recreated surface and apply its optional native input shape."""
        try:
            self._host.set_geometry(geometry)
            self._host.show_window()
            self._host.raise_window()
            if not enabled:
                self._host.activate_window()
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"窗口状态恢复失败: {exc}")

        self._apply_optional_click_through(enabled)
        self._host.refresh()
        return OverlayOperationResult.success()

    def _apply_optional_click_through(self, enabled: bool) -> None:
        """Apply XShape when available while retaining Qt's portable input policy."""
        click_through = self._click_through
        if click_through is None:
            return
        window_id = self._host.native_window_id()
        if window_id is None:
            logger.warning("X11 click-through enhancement skipped: window id unavailable")
            return
        result = click_through.set_click_through(window_id, enabled)
        if not result.succeeded:
            logger.warning("X11 click-through enhancement failed: %s", result.reason)

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> DragStartResult:
        """Start the portable Qt drag strategy unless gaming mode is active."""
        if self._gaming_mode:
            return DragStartResult(DragMode.UNAVAILABLE, "游戏模式下窗口不接受输入")
        return self._drag_strategy.begin_drag(local_position, global_position)

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> OverlayOperationResult:
        """Forward pointer movement to the selected normal-window strategy."""
        return self._drag_strategy.update_drag(local_position, global_position)

    def end_drag(self) -> None:
        """Release the portable drag strategy."""
        self._drag_strategy.end_drag()


def create_wayland_fallback_platform(host: WindowHost, reason: str) -> QtWindowPlatform:
    """Build the ordinary-window fallback used when Layer Shell activation fails."""
    return QtWindowPlatform(
        host,
        gaming_mode_supported=False,
        gaming_mode_reason=reason,
        bypass_window_manager=False,
        click_through=None,
        click_through_supported=False,
        prefer_system_move=True,
    )
