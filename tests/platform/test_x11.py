from collections.abc import Callable

from bilihud.platform.x11 import X11InputShape


class FakeNativeFunction:
    """Provide the mutable ctypes attributes required by the native boundary."""

    def __init__(self, callback: Callable[..., object]) -> None:
        self._callback = callback
        self.argtypes: list[object] | None = None
        self.restype: object | None = None

    def __call__(self, *arguments: object) -> object:
        return self._callback(*arguments)


def test_x11_display_cleanup_failure_stays_inside_operation_result() -> None:
    """Optional XShape cleanup errors must not escape the platform boundary."""
    calls: list[str] = []

    def open_display(_display_name: object) -> object:
        return object()

    def flush(_display: object) -> None:
        calls.append("flush")

    def close_display(_display: object) -> None:
        calls.append("close")
        raise RuntimeError("test close failure")

    def combine_rectangles(*_arguments: object) -> None:
        calls.append("rectangles")

    def combine_mask(*_arguments: object) -> None:
        calls.append("mask")

    adapter = X11InputShape(
        x11_open_display=FakeNativeFunction(open_display),
        x11_flush=FakeNativeFunction(flush),
        x11_close_display=FakeNativeFunction(close_display),
        shape_rectangles=FakeNativeFunction(combine_rectangles),
        shape_mask=FakeNativeFunction(combine_mask),
    )

    result = adapter.set_click_through(123, enabled=True)

    assert result.succeeded is False
    assert result.reason == "X11 display close failed: test close failure"
    assert calls == ["rectangles", "flush", "close"]
