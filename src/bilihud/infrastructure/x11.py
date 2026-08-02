"""X11 input-shape adapter isolated from the window presentation."""

from __future__ import annotations

import ctypes

from ..overlay_ports import OverlayOperationResult
from .native import NativeFunction, load_native_function


class X11InputShape:
    """Isolate XShape input-region calls from the presentation and application layers."""

    def __init__(
        self,
        x11_open_display: NativeFunction,
        x11_flush: NativeFunction,
        x11_close_display: NativeFunction,
        shape_rectangles: NativeFunction,
        shape_mask: NativeFunction,
    ) -> None:
        self._x11_open_display = x11_open_display
        self._x11_flush = x11_flush
        self._x11_close_display = x11_close_display
        self._shape_rectangles = shape_rectangles
        self._shape_mask = shape_mask

    @classmethod
    def load(cls) -> tuple[X11InputShape | None, str | None]:
        """Load X11 and XShape symbols, returning a reason when the capability is absent."""
        try:
            x11 = ctypes.CDLL("libX11.so.6")
            xext = ctypes.CDLL("libXext.so.6")
            x11_open_display = load_native_function(
                x11,
                "XOpenDisplay",
                [ctypes.c_void_p],
                ctypes.c_void_p,
            )
            x11_flush = load_native_function(x11, "XFlush", [ctypes.c_void_p])
            x11_close_display = load_native_function(x11, "XCloseDisplay", [ctypes.c_void_p])
            shape_rectangles = load_native_function(
                xext,
                "XShapeCombineRectangles",
                [
                    ctypes.c_void_p,
                    ctypes.c_ulong,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_void_p,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                ],
            )
            shape_mask = load_native_function(
                xext,
                "XShapeCombineMask",
                [
                    ctypes.c_void_p,
                    ctypes.c_ulong,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_void_p,
                    ctypes.c_int,
                ],
            )
        except OSError as exc:
            return None, f"X11 click-through support is unavailable: {exc}"

        if x11_open_display is None:
            return None, "X11 click-through support is missing symbol: XOpenDisplay"
        if x11_flush is None:
            return None, "X11 click-through support is missing symbol: XFlush"
        if x11_close_display is None:
            return None, "X11 click-through support is missing symbol: XCloseDisplay"
        if shape_rectangles is None:
            return None, "X11 click-through support is missing symbol: XShapeCombineRectangles"
        if shape_mask is None:
            return None, "X11 click-through support is missing symbol: XShapeCombineMask"

        return cls(
            x11_open_display=x11_open_display,
            x11_flush=x11_flush,
            x11_close_display=x11_close_display,
            shape_rectangles=shape_rectangles,
            shape_mask=shape_mask,
        ), None

    def set_click_through(self, window_id: int, enabled: bool) -> OverlayOperationResult:
        """Set or clear an XShape input region for one X11 window."""
        display = self._x11_open_display(None)
        if not display:
            return OverlayOperationResult.failure("X11 display could not be opened")

        result = OverlayOperationResult.success()
        try:
            shape_input = 2
            shape_set = 0
            if enabled:
                self._shape_rectangles(
                    display,
                    window_id,
                    shape_input,
                    0,
                    0,
                    None,
                    0,
                    shape_set,
                    0,
                )
            else:
                self._shape_mask(
                    display,
                    window_id,
                    shape_input,
                    0,
                    0,
                    None,
                    shape_set,
                )
            self._x11_flush(display)
        except (OSError, RuntimeError, ctypes.ArgumentError) as exc:
            result = OverlayOperationResult.failure(f"X11 click-through update failed: {exc}")

        try:
            self._x11_close_display(display)
        except (OSError, RuntimeError, ctypes.ArgumentError) as exc:
            if result.succeeded:
                result = OverlayOperationResult.failure(f"X11 display close failed: {exc}")

        return result
