"""Presentation-owned full-screen gift effects for the desktop overlay."""

from __future__ import annotations

import logging
import math
from typing import Protocol

from PyQt6.QtCore import QBuffer, QElapsedTimer, QIODevice, QRect, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QMovie,
    QPainter,
    QPaintEvent,
    QPen,
)
from PyQt6.QtMultimedia import QMediaPlayer, QVideoFrame, QVideoSink
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QApplication, QWidget

from bilihud.danmaku.messages import GiftEffectLayout, GiftMessage
from bilihud.platform.overlay_contracts import (
    OverlayOperationResult,
    OverlayPlatform,
    OverlayPlatformFactory,
    WindowRectangle,
)
from bilihud.ui.window_host import QtWindowHost

logger = logging.getLogger(__name__)


class GiftAnimationNetworkManager(Protocol):
    """Network capability used to download one official GIF for the overlay."""

    def get(self, request: QNetworkRequest) -> QNetworkReply | None:
        """Start one bounded official GIF request and return its reply handle."""
        ...


def compose_gift_video_frame(frame: QImage, layout: GiftEffectLayout) -> QImage | None:
    """Extract the color frame and apply the packed video's grayscale alpha mask."""
    if frame.isNull():
        return None
    rgb_rect = QRect(
        layout.rgb_frame.x,
        layout.rgb_frame.y,
        layout.rgb_frame.width,
        layout.rgb_frame.height,
    )
    alpha_rect = QRect(
        layout.alpha_frame.x,
        layout.alpha_frame.y,
        layout.alpha_frame.width,
        layout.alpha_frame.height,
    )
    if not frame.rect().contains(rgb_rect) or not frame.rect().contains(alpha_rect):
        return None

    color = frame.copy(rgb_rect).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    alpha = (
        frame.copy(alpha_rect)
        .convertToFormat(QImage.Format.Format_Grayscale8)
        .scaled(
            color.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )
    color.setAlphaChannel(alpha)
    return color


class GiftEffectWindow(QWidget):
    """Show one temporary click-through gift animation in a separate screen surface."""

    _DURATION_MS = 3000
    _VIDEO_DURATION_MS = 15000
    _GIF_MAX_BYTES = 5 * 1024 * 1024
    _FRAME_INTERVAL_MS = 16
    _VIDEO_MAX_SIZE_RATIO = 0.80
    _VIDEO_VERTICAL_OFFSET_RATIO = 0.10

    def __init__(self, parent: QWidget, *, platform_factory: OverlayPlatformFactory) -> None:
        """Create an independent hidden surface without starting animation or network work."""
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("BiliHUD Gift Effect")

        self._parent_widget: QWidget = parent
        self._window_host: QtWindowHost = QtWindowHost(self, full_screen_overlay=True)
        self._platform: OverlayPlatform = platform_factory(self._window_host)
        self._available: bool = self._prepare_platform()
        self._message: GiftMessage | None = None
        self._font_family: str = ""
        self._clock: QElapsedTimer = QElapsedTimer()
        self._active_duration_ms: int = self._DURATION_MS
        self._video_player: QMediaPlayer = QMediaPlayer(self)
        self._video_sink: QVideoSink = QVideoSink(self)
        self._video_frame: QImage | None = None
        self._video_player.setVideoOutput(self._video_sink)
        self._video_sink.videoFrameChanged.connect(self._on_video_frame_changed)
        self._video_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._video_player.errorOccurred.connect(self._on_media_error)
        self._network_manager: GiftAnimationNetworkManager = QNetworkAccessManager(self)
        self._gif_generation: int = 0
        self._gif_reply: QNetworkReply | None = None
        self._gif_buffer: QBuffer | None = None
        self._gif_movie: QMovie | None = None
        self._animation_timer: QTimer = QTimer(self)
        self._animation_timer.setInterval(self._FRAME_INTERVAL_MS)
        self._animation_timer.timeout.connect(self._advance_animation)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def set_font_family(self, font_family: str) -> None:
        """Apply the shared HUD font to text rendered by the fallback effect."""
        self._font_family = font_family.strip()

    def _prepare_platform(self) -> bool:
        """Prepare the injected surface and require a pass-through overlay capability."""
        result = self._platform.prepare()
        if not result.succeeded:
            logger.warning("Gift effect window preparation failed: %s", result.reason)
            return False
        if not self._platform.capabilities.gaming_mode:
            logger.info(
                "Gift effect window disabled because pass-through overlay is unavailable: %s",
                self._platform.capabilities.unavailable_reason or "unknown reason",
            )
            return False
        return True

    def show_gift(self, message: GiftMessage) -> None:
        """Display the newest gift for a bounded duration on the parent window's screen."""
        if not self._available:
            return
        screen_geometry = self._screen_geometry()
        if screen_geometry is None:
            logger.warning("Gift effect skipped because no target screen is available")
            return

        self._window_host.set_geometry(
            WindowRectangle(
                screen_geometry.x(),
                screen_geometry.y(),
                screen_geometry.width(),
                screen_geometry.height(),
            )
        )
        self._clear_gift_animation()
        self._message = message
        has_video = bool(message.gift_effect_url and message.gift_effect_layout is not None)
        self._active_duration_ms = self._VIDEO_DURATION_MS if has_video else self._DURATION_MS
        self._clock.restart()
        self.show()
        self.raise_()

        activation = self._platform.activate()
        if not activation.succeeded:
            self._hide_after_failure("激活失败", activation)
            return
        passthrough = self._platform.set_gaming_mode(True)
        if not passthrough.succeeded:
            self._hide_after_failure("穿透模式切换失败", passthrough)
            return

        if has_video:
            self._video_player.setSource(QUrl(message.gift_effect_url))
            self._video_player.play()
        elif message.gift_animation_url:
            self._load_gif_animation(message.gift_animation_url)
        self._animation_timer.start()
        self.update()

    def _screen_geometry(self) -> QRect | None:
        """Resolve the screen containing the main HUD, with a primary-screen fallback."""
        screen = self._parent_widget.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        return None if screen is None else screen.geometry()

    def _hide_after_failure(self, operation: str, result: OverlayOperationResult) -> None:
        """Hide a surface that could not become a safe click-through overlay."""
        logger.warning("Gift effect %s: %s", operation, result.reason)
        self._animation_timer.stop()
        self._clear_gift_animation()
        self.hide()

    def _on_video_frame_changed(self, frame: QVideoFrame) -> None:
        """Keep the newest decoded official frame for the transparent Qt surface."""
        image = frame.toImage()
        message = self._message
        if image.isNull() or message is None:
            self._video_frame = None
        elif message.gift_effect_layout is None:
            self._video_frame = None
        else:
            self._video_frame = compose_gift_video_frame(image, message.gift_effect_layout)
        self.update()

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        """Close the effect when the official video reaches its natural end."""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._animation_timer.stop()
            self._video_player.stop()
            self._video_frame = None
            self.hide()

    def _on_media_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        """Stop a failed official video and leave the normal visual fallback available."""
        if error == QMediaPlayer.Error.NoError:
            return
        logger.warning("Official gift video playback failed: %s", error_string)
        self._video_player.stop()
        self._video_frame = None
        self._active_duration_ms = self._DURATION_MS
        message = self._message
        if message is not None and message.gift_animation_url:
            self._load_gif_animation(message.gift_animation_url)
        self.update()

    def _clear_gift_animation(self) -> None:
        """Stop current media and cancel stale GIF downloads before reuse or close."""
        self._gif_generation += 1
        reply = self._gif_reply
        self._gif_reply = None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

        movie = self._gif_movie
        self._gif_movie = None
        if movie is not None:
            movie.stop()
            movie.deleteLater()

        buffer = self._gif_buffer
        self._gif_buffer = None
        if buffer is not None:
            buffer.close()
            buffer.deleteLater()

        self._video_player.stop()
        self._video_frame = None

    def _load_gif_animation(self, url: str) -> None:
        """Fetch one validated official GIF and attach it to the overlay movie."""
        self._gif_generation += 1
        generation = self._gif_generation
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Referer", b"https://live.bilibili.com/")
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0 BiliHUD")
        reply = self._network_manager.get(request)
        if reply is None:
            return
        self._gif_reply = reply
        reply.setReadBufferSize(self._GIF_MAX_BYTES + 1)
        reply.downloadProgress.connect(
            lambda received, _total, reply=reply: self._abort_oversized_gif(reply, received)
        )
        reply.finished.connect(
            lambda reply=reply, generation=generation: self._on_gif_loaded(reply, generation)
        )

    def _abort_oversized_gif(self, reply: QNetworkReply, received: int) -> None:
        """Stop an official GIF download before it exceeds the bounded overlay cache."""
        if self._gif_reply is reply and received > self._GIF_MAX_BYTES:
            reply.abort()

    def _on_gif_loaded(self, reply: QNetworkReply, generation: int) -> None:
        """Install a valid GIF only when it belongs to the currently visible gift."""
        if self._gif_reply is reply:
            self._gif_reply = None
        error = reply.error()
        if generation != self._gif_generation or error is not QNetworkReply.NetworkError.NoError:
            reply.deleteLater()
            return
        if reply.size() > self._GIF_MAX_BYTES:
            reply.deleteLater()
            return

        payload = reply.readAll()
        reply.deleteLater()
        if not payload or payload.size() > self._GIF_MAX_BYTES:
            return

        buffer = QBuffer(self)
        buffer.setData(payload)
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            buffer.deleteLater()
            return
        movie = QMovie(buffer, b"gif", self)
        movie.setCacheMode(QMovie.CacheMode.CacheAll)
        if not movie.isValid():
            movie.deleteLater()
            buffer.close()
            buffer.deleteLater()
            return

        self._gif_buffer = buffer
        self._gif_movie = movie
        movie.frameChanged.connect(self._on_gif_frame_changed)
        movie.start()
        self.update()

    def _on_gif_frame_changed(self, _frame_number: int) -> None:
        """Repaint the transparent surface when the downloaded GIF advances."""
        self.update()

    def _advance_animation(self) -> None:
        """Advance the owned timer and close the surface after its animation window."""
        if not self._clock.isValid() or self._clock.elapsed() >= self._active_duration_ms:
            self._animation_timer.stop()
            self._clear_gift_animation()
            self.hide()
            return
        self.update()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """Paint a bounded gift pulse without changing the underlying HUD window."""
        del a0
        message = self._message
        if message is None:
            return

        progress = min(1.0, max(0.0, self._clock.elapsed() / self._active_duration_ms))
        fade = math.sin(math.pi * progress)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(18, 8, 30, round(34 * fade)))

        video_frame = self._video_frame
        if video_frame is not None and not video_frame.isNull():
            frame_size = video_frame.size()
            max_video_size = QSize(
                min(frame_size.width(), max(1, round(self.width() * self._VIDEO_MAX_SIZE_RATIO))),
                min(frame_size.height(), max(1, round(self.height() * self._VIDEO_MAX_SIZE_RATIO))),
            )
            scaled = video_frame.scaled(
                max_video_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            vertical_offset = round(scaled.height() * self._VIDEO_VERTICAL_OFFSET_RATIO)
            painter.drawImage(
                self.rect().center().x() - scaled.width() // 2,
                self.rect().center().y() - scaled.height() // 2 - vertical_offset,
                scaled,
            )
            painter.end()
            return

        gif_movie = self._gif_movie
        if gif_movie is not None:
            gif_pixmap = gif_movie.currentPixmap()
            if not gif_pixmap.isNull():
                max_gif_size = QSize(
                    max(1, round(self.width() * self._VIDEO_MAX_SIZE_RATIO)),
                    max(1, round(self.height() * self._VIDEO_MAX_SIZE_RATIO)),
                )
                scaled = gif_pixmap.scaled(
                    max_gif_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                vertical_offset = round(scaled.height() * self._VIDEO_VERTICAL_OFFSET_RATIO)
                painter.drawPixmap(
                    self.rect().center().x() - scaled.width() // 2,
                    self.rect().center().y() - scaled.height() // 2 - vertical_offset,
                    scaled,
                )
                painter.end()
                return

        center = self.rect().center()
        base_radius = max(120, min(self.width(), self.height()) // 7)
        for index in range(3):
            radius = round(base_radius * (0.72 + progress * (0.5 + index * 0.22)))
            alpha = max(0, round((170 - index * 42) * fade))
            painter.setPen(QPen(QColor(255, 220, 116, alpha), 2))
            painter.drawEllipse(center, radius, radius)

        panel_width = min(760, max(360, self.width() - 80))
        panel_height = 168
        panel = QRect(
            center.x() - panel_width // 2,
            center.y() - panel_height // 2,
            panel_width,
            panel_height,
        )
        painter.setPen(QPen(QColor(255, 220, 116, round(220 * fade)), 2))
        painter.setBrush(QColor(35, 12, 42, round(220 * fade)))
        painter.drawRoundedRect(panel, 18, 18)

        font_family = self._font_family if self._font_family else "Sans"
        title_font = QFont(font_family)
        title_font.setBold(True)
        title_font.setPixelSize(42)
        painter.setFont(title_font)
        painter.setPen(QColor(255, 245, 220, round(255 * fade)))
        title_metrics = QFontMetrics(title_font)
        title = title_metrics.elidedText(
            f"{message.gift_name} x{message.quantity}",
            Qt.TextElideMode.ElideRight,
            panel.width() - 48,
        )
        painter.drawText(
            panel.adjusted(24, 24, -24, -72),
            Qt.AlignmentFlag.AlignCenter,
            title,
        )

        meta_font = QFont(font_family)
        meta_font.setPixelSize(20)
        painter.setFont(meta_font)
        painter.setPen(QColor(255, 255, 255, round(220 * fade)))
        meta = f"{message.author.name} {message.action}".strip()
        painter.drawText(
            panel.adjusted(24, 96, -24, -20),
            Qt.AlignmentFlag.AlignCenter,
            meta,
        )
        painter.end()

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Stop the owned animation timer before the surface is closed."""
        self._animation_timer.stop()
        self._clear_gift_animation()
        self._message = None
        super().closeEvent(a0)


__all__ = (
    "GiftEffectWindow",
    "compose_gift_video_frame",
)
