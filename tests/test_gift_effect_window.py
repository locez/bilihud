import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QWidget

from bilihud.danmaku.messages import GiftEffectFrame, GiftEffectLayout, GiftMessage, MessageAuthor, TextSegment
from bilihud.platform.overlay_contracts import (
    DragMode,
    DragStartResult,
    OverlayCapabilities,
    OverlayOperationResult,
    WindowPoint,
)
from bilihud.ui.hud.gift_effect import GiftEffectWindow, compose_gift_video_frame


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_compose_gift_video_frame_uses_the_packed_alpha_region() -> None:
    frame = QImage(8, 4, QImage.Format.Format_ARGB32)
    frame.fill(QColor(255, 0, 0, 255))
    for y in range(4):
        for x in range(4, 8):
            frame.setPixelColor(x, y, QColor(255, 255, 255) if x >= 6 else QColor(0, 0, 0))

    composed = compose_gift_video_frame(
        frame,
        GiftEffectLayout(
            rgb_frame=GiftEffectFrame(0, 0, 4, 4),
            alpha_frame=GiftEffectFrame(4, 0, 4, 4),
        ),
    )

    assert composed is not None
    assert composed.size().width() == 4
    assert composed.size().height() == 4
    assert composed.pixelColor(0, 0).alpha() == 0
    assert composed.pixelColor(3, 0).alpha() == 255
    assert composed.pixelColor(3, 0).red() == 255


class FakePlatform:
    """Platform fake proving the effect surface requests activation and pass-through."""

    capabilities = OverlayCapabilities(
        layer_shell=False,
        gaming_mode=True,
        click_through=True,
        drag=True,
    )

    def __init__(self) -> None:
        self.prepare_calls = 0
        self.activate_calls = 0
        self.mode_calls: list[bool] = []

    def prepare(self) -> OverlayOperationResult:
        self.prepare_calls += 1
        return OverlayOperationResult.success()

    def activate(self) -> OverlayOperationResult:
        self.activate_calls += 1
        return OverlayOperationResult.success()

    def set_gaming_mode(self, enabled: bool) -> OverlayOperationResult:
        self.mode_calls.append(enabled)
        return OverlayOperationResult.success()

    def begin_drag(self, _local_position: WindowPoint, _global_position: WindowPoint) -> DragStartResult:
        return DragStartResult(DragMode.UNAVAILABLE, "effect surface is click-through")

    def update_drag(
        self,
        _local_position: WindowPoint,
        _global_position: WindowPoint,
    ) -> OverlayOperationResult:
        return OverlayOperationResult.failure("effect surface is click-through")

    def end_drag(self) -> None:
        pass


def test_gift_effect_window_uses_a_full_screen_click_through_surface() -> None:
    app = _app()
    parent = QWidget()
    platform = FakePlatform()
    window = GiftEffectWindow(parent, platform_factory=lambda _host: platform)
    message = GiftMessage(
        author=MessageAuthor(uid=1, name="送礼用户", color="#FFD700"),
        segments=(TextSegment("赠送 辣条 x2"),),
        action="赠送",
        gift_name="辣条",
        quantity=2,
    )

    try:
        window.show_gift(message)
        app.processEvents()

        screen = app.primaryScreen()
        assert screen is not None
        assert window.parent() is None
        assert window.geometry() == screen.geometry()
        assert platform.prepare_calls == 1
        assert platform.activate_calls == 1
        assert platform.mode_calls == [True]
        assert window.isVisible() is True
    finally:
        window.close()
        parent.close()
        app.processEvents()
