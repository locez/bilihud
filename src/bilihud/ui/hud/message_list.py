"""Message-list rendering for normalized HUD messages."""

from __future__ import annotations

import html

from PyQt6.QtCore import QModelIndex, QSize, Qt, QUrl
from PyQt6.QtGui import QFont, QImage, QPainter, QTextDocument
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QAbstractItemView, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from bilihud.danmaku.format import (
    danmaku_author_badges_html,
    danmaku_message_content_html,
    danmaku_message_emoticon_urls,
)
from bilihud.danmaku.messages import (
    DanmakuMessage,
    GiftMessage,
    HudMessage,
    InteractMessage,
    SystemMessage,
)


class DanmakuDelegate(QStyledItemDelegate):
    """Render normalized HUD messages with document and image caching."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create an item delegate with an owned image request manager."""
        super().__init__(parent)
        self._cache: dict[int, tuple[HudMessage, QTextDocument]] = {}
        self._emoticon_cache: dict[str, QImage | None] = {}
        self._emoticon_docs: dict[str, list[QTextDocument]] = {}
        self._network_manager = QNetworkAccessManager(self)

    def _get_document(self, message: HudMessage, width: int, font: QFont) -> QTextDocument:
        """Retrieve or create the cached document for one message."""
        msg_id = id(message)
        cached = self._cache.get(msg_id)
        if cached is not None:
            cached_message, doc = cached
            if cached_message is message:
                if doc.textWidth() != width:
                    doc.setTextWidth(width)
                return doc

        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(font)
        doc.setHtml(self.get_html_for_message(message))
        doc.setTextWidth(width)
        self._attach_emoticon_resource(doc, message)
        self._cache[msg_id] = (message, doc)
        return doc

    def forget_message(self, message: HudMessage) -> None:
        """Release the cached document for a message removed from the list."""
        msg_id = id(message)
        cached = self._cache.get(msg_id)
        if cached is not None and cached[0] is message:
            self._cache.pop(msg_id, None)

    def _attach_emoticon_resource(self, doc: QTextDocument, message: HudMessage) -> None:
        if not isinstance(message, DanmakuMessage):
            return

        for url in danmaku_message_emoticon_urls(message):
            qurl = QUrl(url)
            cached = self._emoticon_cache.get(url)
            if cached is not None:
                doc.addResource(QTextDocument.ResourceType.ImageResource, qurl, cached)
                continue
            if url not in self._emoticon_cache:
                self._emoticon_cache[url] = None
                request = QNetworkRequest(qurl)
                request.setRawHeader(b"Referer", b"https://live.bilibili.com/")
                request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0 BiliHUD")
                reply = self._network_manager.get(request)
                if reply is None:
                    self._emoticon_cache.pop(url, None)
                    return
                reply.finished.connect(lambda reply=reply, url=url: self._on_emoticon_loaded(reply, url))

            self._emoticon_docs.setdefault(url, []).append(doc)

    def _on_emoticon_loaded(self, reply: QNetworkReply, url: str) -> None:
        image = QImage.fromData(reply.readAll())
        reply.deleteLater()
        docs = self._emoticon_docs.pop(url, [])
        if image.isNull():
            self._emoticon_cache.pop(url, None)
            return

        self._emoticon_cache[url] = image
        qurl = QUrl(url)
        for doc in docs:
            doc.addResource(QTextDocument.ResourceType.ImageResource, qurl, image)

        parent = self.parent()
        if isinstance(parent, QAbstractItemView):
            viewport = parent.viewport()
            if viewport is not None:
                viewport.update()

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Paint one normalized message document into the item rectangle."""
        if painter is None:
            return
        options = option
        self.initStyleOption(options, index)
        msg_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg_data, HudMessage):
            return

        painter.save()
        width = options.rect.width() or 300
        doc = self._get_document(msg_data, width, options.font)
        painter.translate(options.rect.x(), options.rect.y() + 1)
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Calculate the item height required by one rendered message."""
        msg_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg_data, HudMessage):
            return QSize(0, 0)

        width = option.rect.width()
        parent = self.parent()
        if width <= 0 and isinstance(parent, QAbstractItemView):
            viewport = parent.viewport()
            if viewport is not None:
                width = viewport.width()
        width = width or 300
        doc = self._get_document(msg_data, width, option.font)
        return QSize(width, int(doc.size().height()) + 2)

    def get_html_for_message(self, message: HudMessage) -> str:
        """Construct the HTML representation for one normalized message."""
        if isinstance(message, DanmakuMessage):
            user_color = self.get_user_color(message)
            badges_html = danmaku_author_badges_html(message)
            content_html = danmaku_message_content_html(message)
            author_html = f'<span class="user">{html.escape(message.author.name, quote=True)}</span>'
            content_span = f'<span class="content">{content_html}</span>'
            user_style = (
                f".user {{ color: {user_color}; "
                "font-weight: bold; font-family: 'Segoe UI', 'Microsoft YaHei'; "
                "font-size: 12px; }"
            )
            colon_style = (
                ".colon { color: white; "
                "font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 12px; }"
            )
            content_style = (
                ".content { color: white; "
                "font-family: 'Segoe UI', 'Microsoft YaHei'; "
                "font-size: 13px; font-weight: 500; }"
            )
            reply_style = (
                ".reply { color: #FF79C6; "
                "font-family: 'Segoe UI', 'Microsoft YaHei'; "
                "font-size: 13px; font-weight: 700; }"
            )
            return f"""
            <style>
                .meta-badge {{
                    display: inline-block;
                    padding: 0 4px;
                    font-family: 'Segoe UI', 'Microsoft YaHei';
                    font-size: 10px;
                    line-height: 13px;
                    font-weight: 700;
                    color: white;
                    vertical-align: 1px;
                }}
                .medal-badge {{
                    letter-spacing: 0;
                }}
                .wealth-badge {{
                    color: #C9B6FF;
                }}
                .privilege-badge {{
                    color: #FFD700;
                    min-width: 13px;
                    text-align: center;
                }}
                {user_style}
                {colon_style}
                {content_style}
                {reply_style}
                .emoticon {{ vertical-align: middle; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p>{badges_html}{author_html}<span class="colon"> : </span>{content_span}</p>
            """
        if isinstance(message, GiftMessage):
            return f"""
            <style>
                .user {{ color: #FFD700; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 12px; }}
                .action {{ color: #FF66CC; font-family: 'Microsoft YaHei'; font-size: 12px; }}
                .gift {{ color: #FF66CC; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 12px; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p><span class="user">{html.escape(message.author.name, quote=True)}</span>
            <span class="action"> {html.escape(message.action, quote=True)} </span>
            <span class="gift">{html.escape(message.gift_name, quote=True)} x{message.quantity}</span></p>
            """
        if isinstance(message, InteractMessage):
            return f"""
            <style>
                .user {{ color: #AAAAAA; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 11px; }}
                .info {{ color: #AAAAAA; font-family: 'Microsoft YaHei'; font-size: 11px; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p><span class="user">{html.escape(message.author.name, quote=True)}</span>
            <span class="info"> {html.escape(message.interaction.text, quote=True)}</span></p>
            """
        if isinstance(message, SystemMessage):
            author_html = f'<span class="user">{html.escape(message.author.name, quote=True)}</span>'
            content_html = html.escape(message.text, quote=True)
            user_style = (
                f".user {{ color: {message.author.color}; "
                "font-weight: bold; font-family: 'Segoe UI', 'Microsoft YaHei'; "
                "font-size: 12px; }"
            )
            content_style = (
                ".content { color: white; "
                "font-family: 'Segoe UI', 'Microsoft YaHei'; "
                "font-size: 13px; font-weight: 500; }"
            )
            return f"""
            <style>
                {user_style}
                .colon {{ color: white; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 12px; }}
                {content_style}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p>{author_html}<span class="colon"> : </span><span class="content">{content_html}</span></p>
            """
        return ""

    def get_user_color(self, message: HudMessage) -> str:
        """Return the normalized author color used by the message template."""
        return message.author.color


__all__ = ("DanmakuDelegate",)
