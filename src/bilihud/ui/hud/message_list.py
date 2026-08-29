"""Message-list rendering for normalized HUD messages."""

from __future__ import annotations

import html
import re

from PyQt6.QtCore import QModelIndex, QSize, Qt, QUrl
from PyQt6.QtGui import QFont, QImage, QPainter, QTextDocument
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QAbstractItemView, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from bilihud.danmaku.format import (
    danmaku_author_badges_html,
    danmaku_message_content_html,
    danmaku_message_emoticon_urls,
    gift_value_text,
)
from bilihud.danmaku.messages import (
    DanmakuMessage,
    GiftMessage,
    HudMessage,
    InteractMessage,
    SuperChatMessage,
    SystemMessage,
)
from bilihud.ui.hud.gift_animation import GIFT_ANIMATION_SIZE, GiftAnimationCache

SC_DEFAULT_BACKGROUND_COLOR = "#3C2A4D"
SC_DEFAULT_BOTTOM_COLOR = "#2A2038"
SC_DEFAULT_PRICE_COLOR = "#FFD86E"


class DanmakuDelegate(QStyledItemDelegate):
    """Render normalized HUD messages with document and image caching."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create an item delegate with an owned image request manager."""
        super().__init__(parent)
        self._cache: dict[int, tuple[HudMessage, QTextDocument]] = {}
        self._font_family: str = ""
        self._emoticon_cache: dict[str, QImage | None] = {}
        self._emoticon_docs: dict[str, list[QTextDocument]] = {}
        self._network_manager: QNetworkAccessManager = QNetworkAccessManager(self)
        self._gift_animation_cache: GiftAnimationCache = GiftAnimationCache(
            self,
            self._update_viewport,
            self._gift_animation_html,
        )

    def set_font_family(self, font_family: str) -> None:
        """Apply one shared HUD font and invalidate documents using the old family."""
        normalized = font_family.strip()
        if normalized == self._font_family:
            return
        self._font_family = normalized
        self._cache.clear()
        self._gift_animation_cache.clear_documents()
        parent = self.parent()
        if isinstance(parent, QAbstractItemView):
            parent.updateGeometry()
            viewport = parent.viewport()
            if viewport is not None:
                viewport.update()

    def _font_family_css(self) -> str:
        """Return the configured family as a safe CSS font-family value."""
        if not self._font_family:
            return "'Segoe UI', 'Microsoft YaHei', sans-serif"
        escaped = self._font_family.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

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
        if isinstance(message, GiftMessage):
            self._gift_animation_cache.attach(doc, message)
        self._cache[msg_id] = (message, doc)
        return doc

    def forget_message(self, message: HudMessage) -> None:
        """Release the cached document for a message removed from the list."""
        msg_id = id(message)
        cached = self._cache.get(msg_id)
        if cached is not None and cached[0] is message:
            self._cache.pop(msg_id, None)
        if isinstance(message, GiftMessage):
            self._gift_animation_cache.forget(message)

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

    def _update_viewport(self) -> None:
        """Request a repaint and geometry refresh after an asynchronous image update."""
        parent = self.parent()
        if isinstance(parent, QAbstractItemView):
            parent.updateGeometry()
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
        font_family = self._font_family_css()
        if isinstance(message, DanmakuMessage):
            user_color = self.get_user_color(message)
            badges_html = danmaku_author_badges_html(message)
            content_html = danmaku_message_content_html(message)
            author_html = f'<span class="user">{html.escape(message.author.name, quote=True)}</span>'
            content_span = f'<span class="content">{content_html}</span>'
            user_style = (
                f".user {{ color: {user_color}; "
                f"font-weight: bold; font-family: {font_family}; "
                "font-size: 12px; }"
            )
            colon_style = (
                ".colon { color: white; "
                f"font-family: {font_family}; font-size: 12px; }}"
            )
            content_style = (
                ".content { color: white; "
                f"font-family: {font_family}; "
                "font-size: 13px; font-weight: 500; }"
            )
            reply_style = (
                ".reply { color: #FF79C6; "
                f"font-family: {font_family}; "
                "font-size: 13px; font-weight: 700; }"
            )
            return f"""
            <style>
                .meta-badge {{
                    display: inline-block;
                    padding: 0 4px;
                    font-family: {font_family};
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
        if isinstance(message, SuperChatMessage):
            background_color = _safe_sc_color(message.background_color, SC_DEFAULT_BACKGROUND_COLOR)
            bottom_color = _safe_sc_color(message.background_bottom_color, SC_DEFAULT_BOTTOM_COLOR)
            price_color = _safe_sc_color(message.background_price_color, SC_DEFAULT_PRICE_COLOR)
            user = html.escape(message.author.name, quote=True)
            content = html.escape(message.message, quote=True).replace("\n", "<br />")
            return f"""
            <style>
                .sc-card {{
                    background-color: {background_color};
                    border-left: 4px solid {bottom_color};
                    padding: 7px 10px 8px;
                    margin: 2px 0 7px;
                }}
                .sc-label {{
                    color: {price_color};
                    font-family: {font_family};
                    font-size: 10px;
                    font-weight: 800;
                    letter-spacing: 1px;
                }}
                .sc-user {{
                    color: white;
                    font-family: {font_family};
                    font-size: 12px;
                    font-weight: 700;
                }}
                .sc-price {{
                    color: {price_color};
                    font-family: {font_family};
                    font-size: 14px;
                    font-weight: 800;
                }}
                .sc-content {{
                    color: white;
                    font-family: {font_family};
                    font-size: 13px;
                    font-weight: 500;
                }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <div class="sc-card">
                <p><span class="sc-label">SC</span>&nbsp;&nbsp;
                <span class="sc-user">{user}</span>
                <span class="sc-price">&nbsp;¥{message.price}</span></p>
                <p class="sc-content">{content}</p>
            </div>
            """
        if isinstance(message, GiftMessage) and self._gift_animation_cache.has_movie(
            message.gift_animation_url
        ):
            return self._gift_animation_html(message)
        if isinstance(message, GiftMessage):
            gift_value = gift_value_text(message)
            gift_value_html = (
                f'<span class="gift-value"> {html.escape(gift_value, quote=True)}</span>'
                if gift_value
                else ""
            )
            gift_html = (
                f'<span class="gift">{html.escape(message.gift_name, quote=True)} x{message.quantity}</span>'
            )
            return f"""
            <style>
                .user {{ color: #FFD700; font-weight: bold; font-family: {font_family}; font-size: 12px; }}
                .action {{ color: #FF66CC; font-family: {font_family}; font-size: 12px; }}
                .gift {{ color: #FF66CC; font-weight: bold; font-family: {font_family}; font-size: 12px; }}
                .gift-value {{ color: #FFD86E; font-family: {font_family}; font-size: 12px; font-weight: 700; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p><span class="user">{html.escape(message.author.name, quote=True)}</span>
            <span class="action"> {html.escape(message.action, quote=True)} </span>
            {gift_html}{gift_value_html}</p>
            """
        if isinstance(message, InteractMessage):
            return f"""
            <style>
                .user {{ color: #AAAAAA; font-weight: bold; font-family: {font_family}; font-size: 11px; }}
                .info {{ color: #AAAAAA; font-family: {font_family}; font-size: 11px; }}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p><span class="user">{html.escape(message.author.name, quote=True)}</span>
            <span class="info"> {html.escape(message.text, quote=True)}</span></p>
            """
        if isinstance(message, SystemMessage):
            author_html = f'<span class="user">{html.escape(message.author.name, quote=True)}</span>'
            content_html = html.escape(message.text, quote=True)
            user_style = (
                f".user {{ color: {message.author.color}; "
                f"font-weight: bold; font-family: {font_family}; "
                "font-size: 12px; }"
            )
            content_style = (
                ".content { color: white; "
                f"font-family: {font_family}; "
                "font-size: 13px; font-weight: 500; }"
            )
            return f"""
            <style>
                {user_style}
                .colon {{ color: white; font-family: {font_family}; font-size: 12px; }}
                {content_style}
                body, p {{ line-height: 120%; margin: 0; padding: 0; }}
            </style>
            <p>{author_html}<span class="colon"> : </span><span class="content">{content_html}</span></p>
            """
        return ""

    def _gift_animation_html(self, message: GiftMessage) -> str:
        """Render a decoded gift GIF beside its sender and quantity."""
        font_family = self._font_family_css()
        gift_value = gift_value_text(message)
        gift_value_html = (
            f'<span class="gift-animation-value"> {html.escape(gift_value, quote=True)}</span>'
            if gift_value
            else ""
        )
        return f"""
        <style>
            .gift-animation-user {{
                color: #FFD700;
                font-weight: bold;
                font-family: {font_family};
                font-size: 12px;
            }}
            .gift-animation {{ vertical-align: middle; }}
            .gift-animation-quantity {{
                color: #FF66CC;
                font-family: {font_family};
                font-size: 12px;
            }}
            .gift-animation-value {{
                color: #FFD86E;
                font-family: {font_family};
                font-size: 12px;
                font-weight: 700;
            }}
            body, p {{ line-height: 120%; margin: 0; padding: 0; }}
        </style>
        <p><span class="gift-animation-user">{html.escape(message.author.name, quote=True)}</span>
        <img class="gift-animation" src="{html.escape(message.gift_animation_url, quote=True)}"
            width="{GIFT_ANIMATION_SIZE}" height="{GIFT_ANIMATION_SIZE}"
            alt="{html.escape(message.gift_name, quote=True)}" />
        <span class="gift-animation-quantity"> x{message.quantity}</span>{gift_value_html}</p>
        """

    def get_user_color(self, message: HudMessage) -> str:
        """Return the normalized author color used by the message template."""
        return message.author.color


def _safe_sc_color(value: str, fallback: str) -> str:
    """Keep externally supplied SC theme colors inside the CSS color contract."""
    color = value.strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        return color
    return fallback


__all__ = ("DanmakuDelegate",)
