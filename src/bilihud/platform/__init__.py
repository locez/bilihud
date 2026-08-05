"""Toolkit-neutral overlay contracts and desktop/OS platform adapters."""

from .overlay_contracts import (
    DragMode,
    DragStartResult,
    OverlayCapabilities,
    OverlayOperationResult,
    OverlayPlatform,
    OverlayPlatformFactory,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)

__all__ = (
    "DragMode",
    "DragStartResult",
    "OverlayCapabilities",
    "OverlayOperationResult",
    "OverlayPlatform",
    "OverlayPlatformFactory",
    "WindowHost",
    "WindowPoint",
    "WindowPolicy",
    "WindowRectangle",
)
