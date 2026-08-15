from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from bilihud.platform import qt_window_platform, window_platform
from bilihud.platform.overlay_contracts import (
    DragMode,
    OverlayOperationResult,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class FakeWindowHost:
    """Minimal host for testing provider selection and compositor-owned drag."""

    def __init__(self) -> None:
        self.system_move_available = True
        self.native_pointer: int | None = None
        self.full_screen_overlay_enabled = False
        self.policies: list[WindowPolicy] = []
        self.moved_positions: list[WindowPoint] = []
        self.set_geometry_calls: list[WindowRectangle] = []
        self.actions: list[str] = []

    def apply_window_policy(self, policy: WindowPolicy) -> None:
        self.policies.append(policy)

    def native_window_pointer(self) -> int | None:
        return self.native_pointer

    def native_window_id(self) -> int | None:
        return None

    def window_position(self) -> WindowPoint:
        return WindowPoint(0, 0)

    def geometry(self) -> WindowRectangle:
        return WindowRectangle(0, 0, 300, 450)

    def screen_geometry(self) -> WindowRectangle | None:
        return WindowRectangle(0, 0, 1920, 1080)

    def full_screen_overlay(self) -> bool:
        return self.full_screen_overlay_enabled

    def set_geometry(self, geometry: WindowRectangle) -> None:
        self.set_geometry_calls.append(geometry)

    def move_window(self, position: WindowPoint) -> None:
        self.moved_positions.append(position)

    def show_window(self) -> None:
        self.actions.append("show")

    def hide_window(self) -> None:
        self.actions.append("hide")

    def raise_window(self) -> None:
        self.actions.append("raise")

    def activate_window(self) -> None:
        self.actions.append("activate")

    def start_system_move(self) -> bool:
        return self.system_move_available

    def refresh(self) -> None:
        pass


class FakeLayerShellBridge:
    """Native-free Layer Shell fake for strategy-provider integration tests."""

    def __init__(self) -> None:
        self.overlay_calls: list[tuple[int, bool]] = []
        self.anchor_positions: list[tuple[int, int, int]] = []

    def make_overlay(self, window_pointer: int, *, full_screen: bool = False) -> bool:
        self.overlay_calls.append((window_pointer, full_screen))
        return True

    def set_passthrough(self, _window_pointer: int, _enabled: bool) -> None:
        pass

    def set_anchor_position(self, window_pointer: int, x: int, y: int) -> None:
        self.anchor_positions.append((window_pointer, x, y))

    def set_keyboard_interactivity(self, _window_pointer: int, _enabled: bool) -> None:
        pass


@pytest.mark.parametrize("desktop", ["niri", "GNOME"])
def test_wayland_without_layer_shell_keeps_normal_window_drag_available(
    monkeypatch,
    desktop: str,
) -> None:
    """A compositor without the overlay protocol must still provide ordinary movement."""
    _app()
    monkeypatch.setattr(window_platform.QGuiApplication, "platformName", lambda: "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    monkeypatch.delenv("XDG_SESSION_DESKTOP", raising=False)
    monkeypatch.setattr(
        window_platform,
        "load_layer_shell_bridge",
        lambda _package_dir: (None, "test bridge unavailable"),
    )

    host = FakeWindowHost()
    platform = window_platform.DefaultOverlayPlatformFactory()(host)

    assert platform.capabilities.layer_shell is False
    assert platform.capabilities.gaming_mode is False
    assert platform.capabilities.drag is True
    assert platform.capabilities.unavailable_reason == (
        "Wayland compositor does not provide the Layer Shell overlay capability"
    )
    assert platform.prepare() == OverlayOperationResult.success()
    assert platform.activate() == OverlayOperationResult.success()

    drag = platform.begin_drag(WindowPoint(20, 20), WindowPoint(100, 100))
    assert drag.mode is DragMode.SYSTEM


def test_wayland_manual_drag_is_the_fallback_when_system_move_is_rejected(monkeypatch) -> None:
    """The normal-window adapter retains a manual path for compositors rejecting system move."""
    _app()
    monkeypatch.setattr(window_platform.QGuiApplication, "platformName", lambda: "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "niri")
    monkeypatch.setattr(
        window_platform,
        "load_layer_shell_bridge",
        lambda _package_dir: (None, "test bridge unavailable"),
    )

    host = FakeWindowHost()
    host.system_move_available = False
    platform = window_platform.DefaultOverlayPlatformFactory()(host)

    drag = platform.begin_drag(WindowPoint(20, 20), WindowPoint(100, 100))
    assert drag.mode is DragMode.MANUAL
    assert platform.update_drag(WindowPoint(30, 30), WindowPoint(130, 140)) == OverlayOperationResult.success()
    assert host.moved_positions == [WindowPoint(110, 120)]


def test_layer_shell_activation_falls_back_to_an_ordinary_window(monkeypatch) -> None:
    """A native activation failure must retain ordinary Wayland window behavior."""
    _app()
    monkeypatch.setattr(window_platform.QGuiApplication, "platformName", lambda: "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")

    class FailingLayerShellBridge(FakeLayerShellBridge):
        def make_overlay(self, _window_pointer: int, *, full_screen: bool = False) -> bool:
            del full_screen
            raise RuntimeError("test activation failure")

    bridge = FailingLayerShellBridge()
    monkeypatch.setattr(window_platform, "load_layer_shell_bridge", lambda _package_dir: (bridge, None))

    host = FakeWindowHost()
    host.native_pointer = 123
    platform = window_platform.DefaultOverlayPlatformFactory()(host)

    assert platform.capabilities.layer_shell is True
    assert platform.prepare() == OverlayOperationResult.success()
    assert platform.activate() == OverlayOperationResult.success()
    assert platform.capabilities.layer_shell is False
    assert platform.capabilities.gaming_mode is False
    assert platform.capabilities.drag is True
    assert platform.capabilities.unavailable_reason == (
        "Layer Shell 预配置失败: test activation failure"
    )
    assert platform.begin_drag(WindowPoint(20, 20), WindowPoint(100, 100)).mode is DragMode.SYSTEM
    assert platform.set_gaming_mode(True).succeeded is False


def test_x11_surface_restore_waits_for_mapping_and_ignores_stale_toggle(monkeypatch) -> None:
    """X11 restores geometry after remapping and never lets an old toggle win."""
    _app()
    monkeypatch.setattr(window_platform.QGuiApplication, "platformName", lambda: "xcb")
    callbacks: list[tuple[int, Callable[[], None]]] = []
    monkeypatch.setattr(
        qt_window_platform.QTimer,
        "singleShot",
        lambda delay, callback: callbacks.append((delay, callback)),
    )
    monkeypatch.setattr(
        window_platform.X11InputShape,
        "load",
        lambda: (None, "test XShape unavailable"),
    )

    host = FakeWindowHost()
    platform = window_platform.DefaultOverlayPlatformFactory()(host)
    geometry = host.geometry()

    assert platform.set_gaming_mode(True) == OverlayOperationResult.success()
    assert platform.set_gaming_mode(False) == OverlayOperationResult.success()
    assert [delay for delay, _callback in callbacks] == [50, 50]
    assert host.set_geometry_calls == []

    callbacks[0][1]()
    assert host.set_geometry_calls == []
    callbacks[1][1]()
    assert host.set_geometry_calls == [geometry]
    assert host.actions[-3:] == ["show", "raise", "activate"]


def test_niri_layer_shell_provider_uses_global_drag_deltas(monkeypatch) -> None:
    """niri gets global-delta dragging while the Layer Shell contract stays shared."""
    _app()
    monkeypatch.setattr(window_platform.QGuiApplication, "platformName", lambda: "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "niri")
    bridge = FakeLayerShellBridge()
    monkeypatch.setattr(window_platform, "load_layer_shell_bridge", lambda _package_dir: (bridge, None))

    host = FakeWindowHost()
    host.native_pointer = 123
    platform = window_platform.DefaultOverlayPlatformFactory()(host)

    assert platform.capabilities.layer_shell is True
    assert platform.prepare() == OverlayOperationResult.success()
    assert platform.activate() == OverlayOperationResult.success()
    assert platform.begin_drag(WindowPoint(30, 30), WindowPoint(100, 100)).mode is DragMode.MANUAL
    assert platform.update_drag(WindowPoint(20, 20), WindowPoint(110, 100)) == OverlayOperationResult.success()
    assert platform.update_drag(WindowPoint(20, 20), WindowPoint(120, 100)) == OverlayOperationResult.success()

    assert bridge.anchor_positions == [(123, 0, 0), (123, 10, 0), (123, 20, 0)]

    platform.end_drag()
    assert platform.begin_drag(WindowPoint(20, 20), WindowPoint(0, 0)).mode is DragMode.MANUAL
    assert platform.update_drag(WindowPoint(20, 20), WindowPoint(5000, 0)) == OverlayOperationResult.success()
    assert platform.update_drag(WindowPoint(20, 20), WindowPoint(4999, 0)) == OverlayOperationResult.success()
    assert bridge.anchor_positions[-2:] == [(123, 1870, 0), (123, 1869, 0)]


def test_layer_shell_full_screen_surface_is_configured_before_mapping(monkeypatch) -> None:
    """Gift surfaces use four-edge Layer Shell anchors and skip movable HUD margins."""
    _app()
    monkeypatch.setattr(window_platform.QGuiApplication, "platformName", lambda: "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    bridge = FakeLayerShellBridge()
    monkeypatch.setattr(window_platform, "load_layer_shell_bridge", lambda _package_dir: (bridge, None))

    host = FakeWindowHost()
    host.native_pointer = 123
    host.full_screen_overlay_enabled = True
    platform = window_platform.DefaultOverlayPlatformFactory()(host)

    assert platform.prepare() == OverlayOperationResult.success()
    assert bridge.overlay_calls == [(123, True)]
    assert platform.activate() == OverlayOperationResult.success()
    assert bridge.anchor_positions == []


@pytest.mark.parametrize("platform_name", ["cocoa", "windows"])
def test_generic_qt_platform_keeps_gaming_mode_on_non_wayland(monkeypatch, platform_name: str) -> None:
    """Qt's portable topmost/input policy remains available outside Linux Wayland."""
    _app()
    monkeypatch.setattr(window_platform.QGuiApplication, "platformName", lambda: platform_name)
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    monkeypatch.delenv("XDG_SESSION_DESKTOP", raising=False)

    host = FakeWindowHost()
    platform = window_platform.DefaultOverlayPlatformFactory()(host)

    assert platform.capabilities.gaming_mode is True
    assert platform.capabilities.click_through is True
    assert platform.prepare() == OverlayOperationResult.success()
    assert platform.set_gaming_mode(True) == OverlayOperationResult.success()
    assert platform.set_gaming_mode(False) == OverlayOperationResult.success()

    assert host.policies == [
        WindowPolicy(),
        WindowPolicy(
            transparent_for_input=True,
            does_not_accept_focus=True,
            show_without_activating=True,
            mouse_events_transparent=True,
        ),
        WindowPolicy(),
    ]


def test_non_linux_qt_provider_does_not_attempt_to_load_layer_shell_bridge(monkeypatch) -> None:
    """Windows and macOS use generic Qt activation without touching the Linux bridge."""
    _app()
    monkeypatch.setattr(window_platform.QGuiApplication, "platformName", lambda: "windows")

    def fail_if_probed(_package_dir: Path) -> tuple[None, str]:
        """Fail the test if a non-Linux provider probes the Linux bridge."""
        raise AssertionError("Layer Shell must not be probed")

    monkeypatch.setattr(
        window_platform,
        "load_layer_shell_bridge",
        fail_if_probed,
    )

    platform = window_platform.DefaultOverlayPlatformFactory()(FakeWindowHost())

    assert platform.capabilities.layer_shell is False
    assert platform.prepare() == OverlayOperationResult.success()
    assert platform.activate() == OverlayOperationResult.success()


def test_platform_probe_logs_backend_and_selected_provider(monkeypatch, caplog) -> None:
    """Startup diagnostics identify both the Qt backend and the selected provider."""
    _app()
    monkeypatch.setattr(window_platform.QGuiApplication, "platformName", lambda: "cocoa")
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    monkeypatch.delenv("XDG_SESSION_DESKTOP", raising=False)

    with caplog.at_level(logging.INFO, logger="bilihud.platform.window_platform"):
        window_platform.DefaultOverlayPlatformFactory()(FakeWindowHost())

    messages = [record.getMessage() for record in caplog.records]
    assert any("Overlay platform probe: qt_platform=cocoa" in message for message in messages)
    assert any("Generic Qt provider selected" in message for message in messages)
    assert any("Overlay platform selected: QtWindowPlatform" in message for message in messages)
