"""Layer Shell bridge, platform adapter, and replaceable anchor drag strategy."""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .layer_shell_loader import find_layer_shell_library
from .native import NativeFunction, load_native_function
from .overlay_contracts import (
    DragMode,
    DragStartResult,
    OverlayCapabilities,
    OverlayDragStrategy,
    OverlayOperationResult,
    OverlayPlatform,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _LayerShellBindings:
    """Typed wrapper around the compiled Layer Shell bridge symbols."""

    make_overlay: NativeFunction
    set_passthrough: NativeFunction
    set_anchor_position: NativeFunction
    set_keyboard_interactivity: NativeFunction | None

    @classmethod
    def load(cls, package_dir: Path) -> tuple[_LayerShellBindings | None, str | None]:
        """Load the bridge and validate required symbols without failing application startup."""
        library_path = find_layer_shell_library(package_dir)
        if library_path is None:
            logger.info("Layer Shell bridge not found in %s", package_dir)
            return None, "Layer Shell bridge library is not installed"

        logger.info("Loading Layer Shell bridge: %s", library_path)
        try:
            library = ctypes.CDLL(library_path)
            make_overlay = load_native_function(
                library,
                "make_overlay",
                [ctypes.c_void_p],
            )
            set_passthrough = load_native_function(
                library,
                "set_passthrough",
                [ctypes.c_void_p, ctypes.c_bool],
            )
            set_anchor_position = load_native_function(
                library,
                "set_anchor_position",
                [ctypes.c_void_p, ctypes.c_int, ctypes.c_int],
            )
            set_keyboard_interactivity = load_native_function(
                library,
                "set_keyboard_interactivity",
                [ctypes.c_void_p, ctypes.c_bool],
            )
        except OSError as exc:
            logger.info("Layer Shell bridge load failed: %s", exc)
            return None, f"Layer Shell bridge could not be loaded: {exc}"

        if make_overlay is None:
            logger.info("Layer Shell bridge missing required symbol: make_overlay")
            return None, "Layer Shell bridge is missing symbol: make_overlay"
        if set_passthrough is None:
            logger.info("Layer Shell bridge missing required symbol: set_passthrough")
            return None, "Layer Shell bridge is missing symbol: set_passthrough"
        if set_anchor_position is None:
            logger.info("Layer Shell bridge missing required symbol: set_anchor_position")
            return None, "Layer Shell bridge is missing symbol: set_anchor_position"

        logger.info(
            "Layer Shell bridge loaded: keyboard_interactivity=%s",
            set_keyboard_interactivity is not None,
        )
        return cls(
            make_overlay=make_overlay,
            set_passthrough=set_passthrough,
            set_anchor_position=set_anchor_position,
            set_keyboard_interactivity=set_keyboard_interactivity,
        ), None


class LayerShellBridge(Protocol):
    """Native Layer Shell operations expressed without ctypes or Qt types."""

    def make_overlay(self, window_pointer: int) -> None:
        """Promote a mapped Qt window to the compositor overlay layer."""

    def set_passthrough(self, window_pointer: int, enabled: bool) -> None:
        """Set the native input region to empty or default."""

    def set_anchor_position(self, window_pointer: int, x: int, y: int) -> None:
        """Commit top-left Layer Shell margins."""

    def set_keyboard_interactivity(self, window_pointer: int, enabled: bool) -> None:
        """Set whether the overlay may receive keyboard focus on demand."""


class _CtypesLayerShellBridge:
    """Translate the compiled bridge's ctypes ABI into the platform strategy capability."""

    def __init__(self, bindings: _LayerShellBindings) -> None:
        self._bindings = bindings

    def make_overlay(self, window_pointer: int) -> None:
        """Invoke the native overlay promotion function."""
        self._bindings.make_overlay(ctypes.c_void_p(window_pointer))

    def set_passthrough(self, window_pointer: int, enabled: bool) -> None:
        """Invoke the native input-region function."""
        self._bindings.set_passthrough(ctypes.c_void_p(window_pointer), enabled)

    def set_anchor_position(self, window_pointer: int, x: int, y: int) -> None:
        """Invoke the native margin function."""
        self._bindings.set_anchor_position(ctypes.c_void_p(window_pointer), x, y)

    def set_keyboard_interactivity(self, window_pointer: int, enabled: bool) -> None:
        """Invoke the optional keyboard function when the installed bridge supports it."""
        function = self._bindings.set_keyboard_interactivity
        if function is not None:
            function(ctypes.c_void_p(window_pointer), enabled)


def load_layer_shell_bridge(package_dir: Path) -> tuple[LayerShellBridge | None, str | None]:
    """Load a typed Layer Shell bridge while keeping ctypes private to this module."""
    bindings, reason = _LayerShellBindings.load(package_dir)
    if bindings is None:
        return None, reason
    return _CtypesLayerShellBridge(bindings), None


def _initial_layer_position(
    host: WindowHost,
) -> tuple[WindowPoint, WindowRectangle | None]:
    """Resolve one trusted screen-relative position and bind it to its output."""
    known_position = host.window_position()
    if known_position is None:
        geometry = host.geometry()
        known_position = WindowPoint(geometry.x, geometry.y)
    screen = host.screen_geometry()
    if screen is None:
        return known_position, None
    return WindowPoint(known_position.x - screen.x, known_position.y - screen.y), screen


def _commit_layer_position(
    host: WindowHost,
    bridge: LayerShellBridge,
    position: WindowPoint,
) -> OverlayOperationResult:
    """Commit one screen-relative position through the typed Layer Shell bridge."""
    pointer = host.native_window_pointer()
    if pointer is None:
        return OverlayOperationResult.failure("Layer Shell 窗口句柄不可用")
    try:
        bridge.set_anchor_position(pointer, position.x, position.y)
    except (OSError, RuntimeError, ctypes.ArgumentError) as exc:
        return OverlayOperationResult.failure(f"Layer Shell 位置更新失败: {exc}")
    return OverlayOperationResult.success()


def _clamp_layer_position(
    host: WindowHost,
    screen: WindowRectangle | None,
    position: WindowPoint,
) -> WindowPoint:
    """Keep a Layer Shell surface reachable within its bound output."""
    active_screen = screen
    if active_screen is None:
        active_screen = host.screen_geometry()
    if active_screen is None:
        return position
    geometry = host.geometry()
    min_x = -geometry.width + 50
    max_x = active_screen.width - 50
    min_y = -50
    max_y = active_screen.height - 50
    return WindowPoint(
        x=max(min_x, min(position.x, max_x)),
        y=max(min_y, min(position.y, max_y)),
    )


class LayerShellAnchorDragStrategy:
    """Keep the existing KDE-friendly margin drag behavior behind a replaceable strategy."""

    def __init__(self, host: WindowHost, bridge: LayerShellBridge) -> None:
        self._host = host
        self._bridge = bridge
        self._position = WindowPoint(0, 0)
        self._drag_origin: WindowPoint | None = None
        self._position_synchronized = False

    def synchronize_position(self) -> OverlayOperationResult:
        """Derive the initial Layer Shell margin from the host's trusted position."""
        if self._position_synchronized:
            return _commit_layer_position(self._host, self._bridge, self._position)
        self._position, _screen = _initial_layer_position(self._host)
        result = _commit_layer_position(self._host, self._bridge, self._position)
        if result.succeeded:
            self._position_synchronized = True
        return result

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> DragStartResult:
        """Start anchor movement from the fixed local coordinate used by KDE."""
        del global_position
        self._drag_origin = local_position
        return DragStartResult(DragMode.MANUAL)

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> OverlayOperationResult:
        """Apply the press-relative pointer delta and clamp the overlay to its screen."""
        del global_position
        drag_origin = self._drag_origin
        if drag_origin is None:
            return OverlayOperationResult.failure("Layer Shell 拖动尚未开始")

        # The compositor moves the Layer Shell surface while Qt keeps its local
        # event origin stable. Preserve the existing KDE anchor semantics.
        delta = local_position.difference(drag_origin)
        target = _clamp_layer_position(self._host, None, self._position.offset(delta.x, delta.y))
        result = _commit_layer_position(self._host, self._bridge, target)
        if result.succeeded:
            self._position = target
        return result

    def end_drag(self) -> None:
        """Release the local pointer anchor."""
        self._drag_origin = None



class NiriLayerShellDragStrategy:
    """Use global pointer deltas for compositors with asynchronous configure feedback."""

    def __init__(self, host: WindowHost, bridge: LayerShellBridge) -> None:
        self._host = host
        self._bridge = bridge
        self._position = WindowPoint(0, 0)
        self._last_global_position: WindowPoint | None = None
        self._screen: WindowRectangle | None = None
        self._position_synchronized = False

    def synchronize_position(self) -> OverlayOperationResult:
        """Synchronize the anchor and bind future clamping to the same output."""
        if self._position_synchronized:
            return _commit_layer_position(self._host, self._bridge, self._position)
        self._position, self._screen = _initial_layer_position(self._host)
        result = _commit_layer_position(self._host, self._bridge, self._position)
        if result.succeeded:
            self._position_synchronized = True
        return result

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> DragStartResult:
        """Start integrating global pointer motion independently from local surface feedback."""
        del local_position
        self._last_global_position = global_position
        return DragStartResult(DragMode.MANUAL)

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> OverlayOperationResult:
        """Apply one global delta and discard overdrag at the output edge."""
        del local_position
        previous_global_position = self._last_global_position
        if previous_global_position is None:
            return OverlayOperationResult.failure("niri Layer Shell 拖动尚未开始")

        delta = global_position.difference(previous_global_position)
        target = _clamp_layer_position(self._host, self._screen, self._position.offset(delta.x, delta.y))
        result = _commit_layer_position(self._host, self._bridge, target)
        if result.succeeded:
            self._position = target
            self._last_global_position = global_position
        return result

    def end_drag(self) -> None:
        """Release the global pointer anchor."""
        self._last_global_position = None


class LayerShellWindowPlatform(OverlayPlatform):
    """Layer Shell adapter whose drag implementation can be replaced independently."""

    def __init__(
        self,
        host: WindowHost,
        bridge: LayerShellBridge,
        drag_strategy: OverlayDragStrategy | None = None,
        fallback_factory: Callable[[str], OverlayPlatform] | None = None,
    ) -> None:
        self._host = host
        self._bridge = bridge
        if drag_strategy is None:
            self._drag_strategy: OverlayDragStrategy = LayerShellAnchorDragStrategy(host, bridge)
        else:
            self._drag_strategy = drag_strategy
        self._fallback_factory = fallback_factory
        self._fallback_platform: OverlayPlatform | None = None
        self._fallback_reason: str | None = None
        self._activation_logged = False
        self._gaming_mode = False
        self._capabilities = OverlayCapabilities(
            layer_shell=True,
            gaming_mode=True,
            click_through=True,
            drag=True,
        )

    @property
    def capabilities(self) -> OverlayCapabilities:
        """Return Layer Shell capabilities."""
        return self._capabilities

    def prepare(self) -> OverlayOperationResult:
        """Apply the base flags before Layer Shell takes ownership of the surface."""
        try:
            self._host.apply_window_policy(WindowPolicy(recreate_surface=True))
        except RuntimeError as exc:
            reason = f"Layer Shell 窗口初始化失败: {exc}"
            self._mark_layer_shell_unavailable(reason)
            return OverlayOperationResult.failure(reason)
        return OverlayOperationResult.success()

    def activate(self) -> OverlayOperationResult:
        """Promote the mapped Qt window and synchronize its initial anchor position."""
        if self._fallback_platform is not None:
            return OverlayOperationResult.success()
        if self._fallback_reason is not None:
            return self._activate_fallback(self._fallback_reason)

        pointer = self._host.native_window_pointer()
        if pointer is None:
            return self._activate_fallback("Layer Shell 窗口句柄不可用")
        try:
            self._bridge.make_overlay(pointer)
            self._bridge.set_keyboard_interactivity(pointer, True)
        except (OSError, RuntimeError, ctypes.ArgumentError) as exc:
            return self._activate_fallback(f"Layer Shell 激活失败: {exc}")

        result = self._drag_strategy.synchronize_position()
        if not result.succeeded:
            return self._activate_fallback(result.reason or "Layer Shell 初始位置同步失败")
        if not self._activation_logged:
            logger.info(
                "Layer Shell overlay activated: drag_strategy=%s",
                type(self._drag_strategy).__name__,
            )
            self._activation_logged = True
        return OverlayOperationResult.success()

    def _mark_layer_shell_unavailable(self, reason: str) -> None:
        """Record a native failure before the widget has enough state to fall back."""
        self._fallback_reason = reason
        self._capabilities = OverlayCapabilities(
            layer_shell=False,
            gaming_mode=False,
            click_through=False,
            drag=True,
            unavailable_reason=reason,
        )

    def _activate_fallback(self, reason: str) -> OverlayOperationResult:
        """Replace failed Layer Shell activation with an ordinary Wayland window."""
        self._mark_layer_shell_unavailable(reason)
        fallback_factory = self._fallback_factory
        if fallback_factory is None:
            return OverlayOperationResult.failure(reason)

        logger.warning("Layer Shell unavailable; falling back to an ordinary window: %s", reason)
        geometry = self._host.geometry()
        try:
            fallback = fallback_factory(reason)
            prepare_result = fallback.prepare()
            if not prepare_result.succeeded:
                fallback_reason = prepare_result.reason or "普通窗口初始化失败"
                return OverlayOperationResult.failure(
                    f"{reason}; 普通窗口降级失败: {fallback_reason}"
                )
            self._host.set_geometry(geometry)
            self._host.show_window()
            self._host.raise_window()
            activate_result = fallback.activate()
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"{reason}; 普通窗口降级失败: {exc}")

        if not activate_result.succeeded:
            fallback_reason = activate_result.reason or "普通窗口激活失败"
            return OverlayOperationResult.failure(
                f"{reason}; 普通窗口降级失败: {fallback_reason}"
            )
        self._fallback_platform = fallback
        self._capabilities = fallback.capabilities
        return OverlayOperationResult.success()

    def set_gaming_mode(self, enabled: bool) -> OverlayOperationResult:
        """Toggle Layer Shell input and keyboard interactivity without recreating the surface."""
        fallback_platform = self._fallback_platform
        if fallback_platform is not None:
            return fallback_platform.set_gaming_mode(enabled)
        if self._fallback_reason is not None:
            return OverlayOperationResult.failure(self._fallback_reason)

        pointer = self._host.native_window_pointer()
        if pointer is None:
            return OverlayOperationResult.failure("Layer Shell 窗口句柄不可用")

        try:
            self._host.apply_window_policy(
                WindowPolicy(
                    does_not_accept_focus=enabled,
                    show_without_activating=enabled,
                    mouse_events_transparent=enabled,
                    recreate_surface=False,
                )
            )
            self._bridge.set_passthrough(pointer, enabled)
            self._bridge.set_keyboard_interactivity(pointer, not enabled)
            self._host.refresh()
        except (OSError, RuntimeError, ctypes.ArgumentError) as exc:
            return OverlayOperationResult.failure(f"Layer Shell 穿透模式切换失败: {exc}")

        self._gaming_mode = enabled
        return OverlayOperationResult.success()

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> DragStartResult:
        """Start the injected Layer Shell drag strategy in normal mode."""
        fallback_platform = self._fallback_platform
        if fallback_platform is not None:
            return fallback_platform.begin_drag(local_position, global_position)
        if self._fallback_reason is not None:
            return DragStartResult(DragMode.UNAVAILABLE, self._fallback_reason)
        if self._gaming_mode:
            return DragStartResult(DragMode.UNAVAILABLE, "游戏模式下窗口不接受输入")
        return self._drag_strategy.begin_drag(local_position, global_position)

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> OverlayOperationResult:
        """Forward Layer Shell pointer motion to its selected strategy."""
        fallback_platform = self._fallback_platform
        if fallback_platform is not None:
            return fallback_platform.update_drag(local_position, global_position)
        if self._fallback_reason is not None:
            return OverlayOperationResult.failure(self._fallback_reason)
        return self._drag_strategy.update_drag(local_position, global_position)

    def end_drag(self) -> None:
        """Release Layer Shell drag state."""
        fallback_platform = self._fallback_platform
        if fallback_platform is not None:
            fallback_platform.end_drag()
            return
        self._drag_strategy.end_drag()
