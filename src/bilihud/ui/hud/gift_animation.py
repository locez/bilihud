"""Bounded animated GIF resources for the desktop HUD message list."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PyQt6.QtCore import QBuffer, QIODevice, QObject, QUrl
from PyQt6.QtGui import QImage, QMovie, QTextDocument
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from bilihud.danmaku.messages import GiftMessage

GIFT_ANIMATION_SIZE = 44
_GIFT_ANIMATION_MAX_BYTES = 5 * 1024 * 1024


class GiftAnimationNetworkManager(Protocol):
    """Network capability used to fetch one gift GIF for the message list."""

    def get(self, request: QNetworkRequest) -> QNetworkReply | None:
        """Start a bounded official GIF request and return its reply handle."""
        ...


class GiftAnimationCache:
    """Own, share, and animate validated GIFs referenced by visible gift messages."""

    def __init__(
        self,
        owner: QObject,
        on_updated: Callable[[], None],
        render_html: Callable[[GiftMessage], str],
    ) -> None:
        """Create a cache whose Qt resources are owned by the delegate surface."""
        self._owner: QObject = owner
        self._on_updated: Callable[[], None] = on_updated
        self._render_html: Callable[[GiftMessage], str] = render_html
        self._network_manager: GiftAnimationNetworkManager = QNetworkAccessManager(owner)
        self._replies: dict[str, QNetworkReply] = {}
        self._buffers: dict[str, QBuffer] = {}
        self._movies: dict[str, QMovie] = {}
        self._documents: dict[str, list[tuple[GiftMessage, QTextDocument]]] = {}
        self._failed: set[str] = set()

    def has_movie(self, url: str) -> bool:
        """Return whether a URL has a decoded movie ready for document rendering."""
        return url in self._movies

    def attach(self, doc: QTextDocument, message: GiftMessage) -> None:
        """Register a gift document and start one shared bounded request when needed."""
        url = message.gift_animation_url
        if not url or url in self._failed:
            return

        documents = self._documents.setdefault(url, [])
        if not any(existing_doc is doc for _, existing_doc in documents):
            documents.append((message, doc))

        movie = self._movies.get(url)
        if movie is not None:
            self._set_frame(doc, url, movie.currentImage())
            return
        if url in self._replies:
            return

        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Referer", b"https://live.bilibili.com/")
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0 BiliHUD")
        reply = self._network_manager.get(request)
        if reply is None:
            self._mark_failed(url)
            return

        self._replies[url] = reply
        reply.setReadBufferSize(_GIFT_ANIMATION_MAX_BYTES + 1)
        reply.downloadProgress.connect(
            lambda received, _total, reply=reply, url=url: self._abort_oversized(reply, url, received)
        )
        reply.finished.connect(lambda reply=reply, url=url: self._on_loaded(reply, url))

    def clear_documents(self) -> None:
        """Forget document listeners before the delegate rebuilds its font-specific cache."""
        self._documents.clear()

    def forget(self, message: GiftMessage) -> None:
        """Release one removed gift message from all frame-update listener lists."""
        for url, documents in tuple(self._documents.items()):
            remaining = [(doc_message, doc) for doc_message, doc in documents if doc_message is not message]
            if remaining:
                self._documents[url] = remaining
            else:
                self._documents.pop(url, None)

    def _abort_oversized(self, reply: QNetworkReply, url: str, received: int) -> None:
        """Stop a gift GIF download before it exceeds the bounded cache size."""
        if self._replies.get(url) is reply and received > _GIFT_ANIMATION_MAX_BYTES:
            reply.abort()

    def _on_loaded(self, reply: QNetworkReply, url: str) -> None:
        """Decode a completed gift GIF and replace registered text documents with its frames."""
        if self._replies.get(url) is not reply:
            reply.deleteLater()
            return
        self._replies.pop(url, None)
        if reply.error() is not QNetworkReply.NetworkError.NoError:
            self._mark_failed(url)
            reply.deleteLater()
            return
        if reply.size() > _GIFT_ANIMATION_MAX_BYTES:
            self._mark_failed(url)
            reply.deleteLater()
            return

        payload = reply.readAll()
        reply.deleteLater()
        if not payload or payload.size() > _GIFT_ANIMATION_MAX_BYTES:
            self._mark_failed(url)
            return

        buffer = QBuffer(self._owner)
        buffer.setData(payload)
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            buffer.deleteLater()
            self._mark_failed(url)
            return

        movie = QMovie(buffer, b"gif", self._owner)
        movie.setCacheMode(QMovie.CacheMode.CacheAll)
        if not movie.isValid():
            movie.deleteLater()
            buffer.close()
            buffer.deleteLater()
            self._mark_failed(url)
            return

        self._buffers[url] = buffer
        self._movies[url] = movie
        movie.frameChanged.connect(lambda _frame_number, url=url: self._on_frame(url))
        movie.start()
        self._refresh_documents(url)

    def _mark_failed(self, url: str) -> None:
        """Remember an unusable GIF and release documents waiting for its frames."""
        self._failed.add(url)
        self._documents.pop(url, None)

    def _on_frame(self, url: str) -> None:
        """Publish the newest GIF frame to every visible document using its URL."""
        movie = self._movies.get(url)
        if movie is None:
            return
        image = movie.currentImage()
        if image.isNull():
            return
        for _, doc in self._documents.get(url, []):
            self._set_frame(doc, url, image)
        self._on_updated()

    def _refresh_documents(self, url: str) -> None:
        """Switch pending gift documents from text to the first decoded GIF frame."""
        movie = self._movies.get(url)
        if movie is None:
            return
        image = movie.currentImage()
        for message, doc in self._documents.get(url, []):
            width = doc.textWidth()
            doc.setHtml(self._render_html(message))
            doc.setTextWidth(width)
            self._set_frame(doc, url, image)
        self._on_updated()

    def _set_frame(self, doc: QTextDocument, url: str, image: QImage) -> None:
        """Attach one decoded frame to the resource key used by the gift HTML."""
        if not image.isNull():
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), image)

__all__ = ("GIFT_ANIMATION_SIZE", "GiftAnimationCache")
