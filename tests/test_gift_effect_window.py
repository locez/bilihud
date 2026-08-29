import os
from io import BytesIO

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QIODevice, QObject
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtNetwork import QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QApplication, QWidget

from bilihud.danmaku.messages import GiftEffectFrame, GiftEffectLayout, GiftMessage, MessageAuthor, TextSegment
from bilihud.platform.overlay_contracts import (
    DragMode,
    DragStartResult,
    OverlayCapabilities,
    OverlayOperationResult,
    OverlayPlatform,
    WindowHost,
    WindowPoint,
)
from bilihud.ui.hud.gift_effect import GiftEffectWindow, compose_gift_video_frame


def _app() -> QApplication:
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    return QApplication([])


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

    def begin_drag(self, local_position: WindowPoint, global_position: WindowPoint) -> DragStartResult:
        del local_position, global_position
        return DragStartResult(DragMode.UNAVAILABLE, "effect surface is click-through")

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
    ) -> OverlayOperationResult:
        del local_position, global_position
        return OverlayOperationResult.failure("effect surface is click-through")

    def end_drag(self) -> None:
        pass


def test_gift_effect_window_uses_a_full_screen_click_through_surface() -> None:
    app = _app()
    parent = QWidget()
    platform = FakePlatform()
    def platform_factory(host: WindowHost) -> OverlayPlatform:
        del host
        return platform

    window = GiftEffectWindow(parent, platform_factory=platform_factory)
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


def test_gift_effect_window_loads_gif_when_no_packed_video_is_available() -> None:
    app = _app()

    class GifPlatform:
        capabilities = OverlayCapabilities(
            layer_shell=False,
            gaming_mode=True,
            click_through=True,
            drag=True,
        )

        def prepare(self) -> OverlayOperationResult:
            return OverlayOperationResult.success()

        def activate(self) -> OverlayOperationResult:
            return OverlayOperationResult.success()

        def set_gaming_mode(self, enabled: bool) -> OverlayOperationResult:
            del enabled
            return OverlayOperationResult.success()

        def begin_drag(self, local_position: WindowPoint, global_position: WindowPoint) -> DragStartResult:
            del local_position, global_position
            return DragStartResult(DragMode.UNAVAILABLE, "effect surface is click-through")

        def update_drag(
            self,
            local_position: WindowPoint,
            global_position: WindowPoint,
        ) -> OverlayOperationResult:
            del local_position, global_position
            return OverlayOperationResult.failure("effect surface is click-through")

        def end_drag(self) -> None:
            pass

    class GifReply(QNetworkReply):
        def __init__(self, payload: bytes, parent: QObject | None = None) -> None:
            super().__init__(parent)
            self._payload = payload
            self._offset = 0
            self.setOpenMode(QIODevice.OpenModeFlag.ReadOnly)
            self.setHeader(QNetworkRequest.KnownHeaders.ContentLengthHeader, len(payload))
            self.setError(QNetworkReply.NetworkError.NoError, "")
            self.setFinished(True)

        def abort(self) -> None:
            pass

        def bytesAvailable(self) -> int:
            return len(self._payload) - self._offset + super().bytesAvailable()

        def readData(self, maxlen: int) -> bytes:
            chunk = self._payload[self._offset : self._offset + maxlen]
            self._offset += len(chunk)
            return chunk

    class GifNetworkManager:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload
            self.requests: list[QNetworkRequest] = []
            self.reply: GifReply | None = None

        def get(self, request: QNetworkRequest) -> QNetworkReply:
            self.requests.append(request)
            self.reply = GifReply(self.payload)
            return self.reply

    gif_buffer = BytesIO()
    first = Image.new("RGBA", (12, 12), (255, 0, 0, 255))
    second = Image.new("RGBA", (12, 12), (0, 255, 0, 255))
    first.save(gif_buffer, format="GIF", save_all=True, append_images=[second], duration=40, loop=0)
    network = GifNetworkManager(gif_buffer.getvalue())
    parent = QWidget()
    window = GiftEffectWindow(parent, platform_factory=lambda _host: GifPlatform())
    window._network_manager = network
    message = GiftMessage(
        author=MessageAuthor(uid=1, name="送礼用户", color="#FFD700"),
        segments=(TextSegment("赠送 小花花 x1"),),
        action="赠送",
        gift_name="小花花",
        quantity=1,
        gift_animation_url="https://i0.hdslb.com/bfs/live/flower.gif",
    )

    try:
        window.show_gift(message)
        assert network.reply is not None
        network.reply.finished.emit()
        app.processEvents()

        assert window._gif_movie is not None
        assert window._gif_movie.isValid()
        assert network.requests[0].url().toString() == message.gift_animation_url
        assert network.requests[0].rawHeader(b"Referer") == b"https://live.bilibili.com/"
    finally:
        window.close()
        parent.close()
        app.processEvents()
