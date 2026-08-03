"""Typed contracts for the platform-specific overlay window boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class WindowPoint:
    """A screen or window-local point without a GUI toolkit dependency."""

    x: int
    y: int

    def offset(self, dx: int, dy: int) -> WindowPoint:
        """Return a point translated by the supplied integer delta."""
        return WindowPoint(self.x + dx, self.y + dy)

    def difference(self, other: WindowPoint) -> WindowPoint:
        """Return the vector from ``other`` to this point."""
        return WindowPoint(self.x - other.x, self.y - other.y)


@dataclass(frozen=True, slots=True)
class WindowRectangle:
    """A rectangle used for geometry and screen-bound calculations."""

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class WindowPolicy:
    """Toolkit-neutral window flags and input attributes for one mode."""

    bypass_window_manager: bool = False
    transparent_for_input: bool = False
    does_not_accept_focus: bool = False
    show_without_activating: bool = False
    mouse_events_transparent: bool = False
    recreate_surface: bool = True


@dataclass(frozen=True, slots=True)
class OverlayCapabilities:
    """Capabilities exposed by the selected platform adapter."""

    layer_shell: bool
    gaming_mode: bool
    click_through: bool
    drag: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class OverlayOperationResult:
    """Result of a platform operation, including an actionable failure reason."""

    succeeded: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.succeeded and self.reason is not None:
            raise ValueError("成功结果不能包含失败原因")
        if not self.succeeded and not self.reason:
            raise ValueError("失败结果必须包含原因")

    @classmethod
    def success(cls) -> OverlayOperationResult:
        """Create a successful operation result."""
        return cls(succeeded=True)

    @classmethod
    def failure(cls, reason: str) -> OverlayOperationResult:
        """Create a failed operation result with a user-facing diagnostic."""
        return cls(succeeded=False, reason=reason)


class DragMode(Enum):
    """The movement mechanism selected for one press gesture."""

    SYSTEM = "system"
    MANUAL = "manual"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DragStartResult:
    """Result of starting a drag and the strategy that owns subsequent motion."""

    mode: DragMode
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.mode is DragMode.UNAVAILABLE and not self.reason:
            raise ValueError("不可用的拖动结果必须包含原因")
        if self.mode is not DragMode.UNAVAILABLE and self.reason is not None:
            raise ValueError("可用的拖动结果不能包含失败原因")


class WindowHost(Protocol):
    """Small presentation-owned surface used by platform adapters."""

    def apply_window_policy(self, policy: WindowPolicy) -> None:
        """Apply abstract window flags and input attributes to the GUI surface."""

    def native_window_pointer(self) -> int | None:
        """Return an opaque toolkit window pointer for native adapters."""

    def native_window_id(self) -> int | None:
        """Return the platform window id when the backend exposes one."""

    def geometry(self) -> WindowRectangle:
        """Return the current top-left and size of the window."""

    def window_position(self) -> WindowPoint | None:
        """Return the best-known global position when toolkit geometry is unreliable."""

    def screen_geometry(self) -> WindowRectangle | None:
        """Return the geometry of the window's current screen, if known."""

    def set_geometry(self, geometry: WindowRectangle) -> None:
        """Restore a window geometry after a toolkit surface recreation."""

    def move_window(self, position: WindowPoint) -> None:
        """Move a normal window to a global position."""

    def show_window(self) -> None:
        """Show the window."""

    def hide_window(self) -> None:
        """Hide the window while changing recreation-sensitive flags."""

    def raise_window(self) -> None:
        """Raise the window above sibling windows when supported."""

    def activate_window(self) -> None:
        """Request input focus for normal mode when supported."""

    def start_system_move(self) -> bool:
        """Ask the compositor to own the current pointer move gesture."""

    def refresh(self) -> None:
        """Request a repaint after a non-recreating native surface update."""


class OverlayDragStrategy(Protocol):
    """Pluggable drag behavior for a selected desktop/window backend."""

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> DragStartResult:
        """Start a gesture and choose system or manual movement."""

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> OverlayOperationResult:
        """Apply one pointer update for the active gesture."""

    def end_drag(self) -> None:
        """Release strategy-owned drag state."""

    def synchronize_position(self) -> OverlayOperationResult:
        """Synchronize backend position after the native surface is mapped."""


class OverlayPlatform(Protocol):
    """Platform capability and lifecycle contract used by the presentation widget."""

    @property
    def capabilities(self) -> OverlayCapabilities:
        """Return immutable capabilities and the reason for unavailable features."""

    def prepare(self) -> OverlayOperationResult:
        """Apply the initial normal-window policy before the window is shown."""

    def activate(self) -> OverlayOperationResult:
        """Activate native overlay integration after the window is mapped."""

    def set_gaming_mode(self, enabled: bool) -> OverlayOperationResult:
        """Toggle pass-through/overlay behavior while preserving window geometry."""

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> DragStartResult:
        """Start a normal-mode drag through the selected backend strategy."""

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> OverlayOperationResult:
        """Forward one normal-mode pointer update to the active strategy."""

    def end_drag(self) -> None:
        """End the current drag and release backend state."""


class OverlayPlatformFactory(Protocol):
    """Callable composition-root factory for a platform adapter bound to one Qt surface."""

    def __call__(self, host: WindowHost) -> OverlayPlatform:
        """Create an adapter for one presentation-owned window host."""
