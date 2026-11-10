"""HUD mouse gestures must respect native move ownership on Windows."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QGuiApplication, QMouseEvent, QWindow
from PyQt6.QtWidgets import QApplication

from bilihud.app.services import create_default_services
from bilihud.ui.hud.window import DanmakuWidget


@pytest.mark.parametrize("native_move_available", [True, False])
def test_header_drag_respects_native_move_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    native_move_available: bool,
) -> None:
    """Header motion changes geometry only when Qt rejects native movement."""
    instance = QApplication.instance()
    app = instance if isinstance(instance, QApplication) else QApplication([])
    monkeypatch.setattr(QGuiApplication, "platformName", lambda: "windows")
    native_moves: list[QWindow] = []

    def start_system_move(window: QWindow) -> bool:
        native_moves.append(window)
        return native_move_available

    monkeypatch.setattr(QWindow, "startSystemMove", start_system_move)
    widget = DanmakuWidget(services=create_default_services(tmp_path / "config.json"))
    try:
        widget.show()
        app.processEvents()
        handle = widget.windowHandle()
        assert handle is not None
        # Start another gesture after release to catch stale drag state.
        for gesture in range(2):
            original_geometry = widget.geometry()
            local = QPoint(10 + gesture * 10, 10)
            global_start = widget.header_widget.mapToGlobal(local)
            delta = QPoint(200, 50)
            press = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(local),
                QPointF(global_start),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            app.sendEvent(widget.header_widget, press)
            assert native_moves == [handle] * (gesture + 1)
            assert widget.dragging is (not native_move_available)

            move = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(local + delta),
                QPointF(global_start + delta),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            app.sendEvent(widget.header_widget, move)
            expected = original_geometry if native_move_available else original_geometry.translated(delta)
            assert widget.geometry() == expected

            release = QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(local),
                QPointF(global_start + delta),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
            app.sendEvent(widget.header_widget, release)
            assert widget.dragging is False
            app.sendEvent(widget.header_widget, move)
            assert widget.geometry() == expected
    finally:
        asyncio.run(widget.shutdown())
        widget.close()
