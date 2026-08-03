"""Platform providers for overlay windows and normal-window dragging."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PyQt6.QtGui import QGuiApplication

from .layer_shell import (
    LayerShellAnchorDragStrategy,
    LayerShellBridge,
    LayerShellWindowPlatform,
    NiriLayerShellDragStrategy,
    load_layer_shell_bridge,
)
from .layer_shell_loader import should_disable_layer_shell
from .ports import (
    OverlayDragStrategy,
    OverlayPlatform,
    WindowHost,
)
from .qt_window_platform import QtWindowPlatform, create_wayland_fallback_platform
from .x11 import X11InputShape

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _PlatformContext:
    """External platform facts shared by capability providers."""

    platform_name: str
    current_desktop: str
    package_dir: Path

    @property
    def is_wayland(self) -> bool:
        """Return whether Qt selected a Wayland backend."""
        return self.platform_name.startswith("wayland")


class _PlatformProvider(Protocol):
    """Provider that claims a window backend when its capability is available."""

    def select(
        self,
        context: _PlatformContext,
        host: WindowHost,
    ) -> tuple[OverlayPlatform | None, str | None]:
        """Return an adapter and an optional diagnostic for this backend."""


class _LayerShellDragProvider(Protocol):
    """Create a drag strategy when a Layer Shell backend matches its behavior."""

    def create(
        self,
        context: _PlatformContext,
        host: WindowHost,
        bridge: LayerShellBridge,
    ) -> OverlayDragStrategy | None:
        """Return a strategy or leave selection to the next provider."""


class _NiriLayerShellDragProvider:
    """Select the global-delta strategy for niri's asynchronous configure model."""

    def create(
        self,
        context: _PlatformContext,
        host: WindowHost,
        bridge: LayerShellBridge,
    ) -> OverlayDragStrategy | None:
        """Claim desktops advertising niri without changing other Wayland desktops."""
        desktops = {part.strip().lower() for part in context.current_desktop.split(":")}
        if "niri" not in desktops:
            return None
        return NiriLayerShellDragStrategy(host, bridge)


class _DefaultLayerShellDragProvider:
    """Keep the existing KDE-compatible local-anchor strategy as the baseline."""

    def create(
        self,
        context: _PlatformContext,
        host: WindowHost,
        bridge: LayerShellBridge,
    ) -> OverlayDragStrategy | None:
        """Provide the baseline strategy for every unclaimed Layer Shell desktop."""
        del context
        return LayerShellAnchorDragStrategy(host, bridge)


class _LayerShellProvider:
    """Select the existing KDE-friendly Layer Shell implementation when possible."""

    def __init__(self, drag_providers: tuple[_LayerShellDragProvider, ...] | None = None) -> None:
        """Build an ordered Layer Shell drag-strategy registry."""
        if drag_providers is None:
            drag_providers = (
                _NiriLayerShellDragProvider(),
                _DefaultLayerShellDragProvider(),
            )
        self._drag_providers = drag_providers

    def select(
        self,
        context: _PlatformContext,
        host: WindowHost,
    ) -> tuple[OverlayPlatform | None, str | None]:
        """Claim Wayland surfaces with a usable Layer Shell bridge."""
        if not context.is_wayland:
            return None, None
        if should_disable_layer_shell(context.platform_name, context.current_desktop):
            logger.info(
                "Layer Shell provider skipped: compositor is not compatible (%s, desktop=%s)",
                context.platform_name,
                context.current_desktop or "unknown",
            )
            return None, "Wayland compositor does not provide the Layer Shell overlay capability"

        bridge, reason = load_layer_shell_bridge(context.package_dir)
        if bridge is None:
            if reason is None:
                reason = "Layer Shell overlay capability is unavailable"
            logger.info("Layer Shell provider unavailable: %s", reason)
            return None, reason

        def fallback_factory(failure_reason: str) -> OverlayPlatform:
            return create_wayland_fallback_platform(host, failure_reason)

        for provider in self._drag_providers:
            drag_strategy = provider.create(context, host, bridge)
            if drag_strategy is not None:
                logger.info(
                    "Layer Shell provider selected: drag_strategy=%s",
                    type(drag_strategy).__name__,
                )
                return (
                    LayerShellWindowPlatform(
                        host,
                        bridge,
                        drag_strategy,
                        fallback_factory=fallback_factory,
                    ),
                    None,
                )
        return LayerShellWindowPlatform(host, bridge, fallback_factory=fallback_factory), None


class _X11Provider:
    """Select Qt/X11 behavior and add XShape as an optional input enhancement."""

    def select(
        self,
        context: _PlatformContext,
        host: WindowHost,
    ) -> tuple[OverlayPlatform | None, str | None]:
        """Claim the XCB backend without making XShape a startup requirement."""
        if context.platform_name != "xcb":
            return None, None

        click_through, reason = X11InputShape.load()
        if click_through is None:
            logger.info("X11 provider selected without XShape enhancement: %s", reason)
        else:
            logger.info("X11 provider selected with XShape click-through enhancement")
        return (
            QtWindowPlatform(
                host,
                gaming_mode_supported=True,
                gaming_mode_reason=None,
                bypass_window_manager=True,
                click_through=click_through,
                click_through_supported=True,
                prefer_system_move=False,
                restore_delay_ms=50,
            ),
            reason,
        )


class _WaylandFallbackProvider:
    """Keep ordinary window behavior on Wayland without compositor overlay support."""

    def select(
        self,
        context: _PlatformContext,
        host: WindowHost,
    ) -> tuple[OverlayPlatform | None, str | None]:
        """Claim unsupported Wayland backends with safe, non-overlay capabilities."""
        if not context.is_wayland:
            return None, None
        reason = "Wayland compositor does not provide the Layer Shell overlay capability"
        logger.info("Wayland fallback provider selected: %s", reason)
        return (
            create_wayland_fallback_platform(host, reason),
            reason,
        )


class _GenericFallbackProvider:
    """Provide the Qt capability baseline for macOS, Windows, and future backends."""

    def select(
        self,
        context: _PlatformContext,
        host: WindowHost,
    ) -> tuple[OverlayPlatform | None, str | None]:
        """Claim any backend not requiring a specialized native integration."""
        del context
        logger.info("Generic Qt provider selected")
        return (
            QtWindowPlatform(
                host,
                gaming_mode_supported=True,
                gaming_mode_reason=None,
                bypass_window_manager=False,
                click_through=None,
                click_through_supported=True,
                prefer_system_move=False,
            ),
            None,
        )


class DefaultOverlayPlatformFactory:
    """Select an overlay adapter through ordered capability providers."""

    def __init__(self, providers: tuple[_PlatformProvider, ...] | None = None) -> None:
        """Build a provider registry that can be replaced by tests or future backends."""
        if providers is None:
            providers = (
                _LayerShellProvider(),
                _X11Provider(),
                _WaylandFallbackProvider(),
                _GenericFallbackProvider(),
            )
        self._providers = providers

    def __call__(self, host: WindowHost) -> OverlayPlatform:
        """Create the selected adapter for one Qt window host."""
        return self.create(host)

    def create(self, host: WindowHost) -> OverlayPlatform:
        """Probe external platform facts once and select the first claiming provider."""
        context = _PlatformContext(
            platform_name=QGuiApplication.platformName(),
            current_desktop=self._current_desktop(),
            package_dir=Path(__file__).resolve().parent.parent,
        )
        logger.info(
            "Overlay platform probe: qt_platform=%s desktop=%s package_dir=%s",
            context.platform_name,
            context.current_desktop or "unknown",
            context.package_dir,
        )
        last_reason: str | None = None
        for provider in self._providers:
            platform, reason = provider.select(context, host)
            if reason is not None:
                last_reason = reason
                logger.info("Overlay provider diagnostic: %s", reason)
            if platform is not None:
                logger.info(
                    "Overlay platform selected: %s capabilities=%s",
                    type(platform).__name__,
                    platform.capabilities,
                )
                return platform

        fallback, fallback_reason = _GenericFallbackProvider().select(context, host)
        if fallback is not None:
            return fallback
        reason = fallback_reason
        if reason is None:
            reason = last_reason
        if reason is None:
            reason = "没有可用的窗口平台实现"
        raise RuntimeError(reason)

    @staticmethod
    def _current_desktop() -> str:
        """Combine desktop environment hints used by the Layer Shell policy."""
        values = (
            os.environ.get("XDG_CURRENT_DESKTOP", ""),
            os.environ.get("XDG_SESSION_DESKTOP", ""),
        )
        return ":".join(value for value in values if value)


def create_default_overlay_platform(host: WindowHost) -> OverlayPlatform:
    """Create the production overlay adapter through the default provider registry."""
    return DefaultOverlayPlatformFactory().create(host)
