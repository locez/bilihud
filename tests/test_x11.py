from bilihud.infrastructure.x11 import X11InputShape


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
        x11_open_display=open_display,
        x11_flush=flush,
        x11_close_display=close_display,
        shape_rectangles=combine_rectangles,
        shape_mask=combine_mask,
    )

    result = adapter.set_click_through(123, enabled=True)

    assert result.succeeded is False
    assert result.reason == "X11 display close failed: test close failure"
    assert calls == ["rectangles", "flush", "close"]
