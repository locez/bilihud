"""Presentation formatting for normalized HUD danmaku messages."""

from __future__ import annotations

import html

from .domain.messages import (
    DanmakuMessage,
    ImageSegment,
    MessageBadge,
    MessageSegment,
    ReplySegment,
    TextSegment,
)

DANMAKU_EMOTICON_MAX_HEIGHT = 34
DANMAKU_EMOTICON_MAX_WIDTH = 140


def _badge(text: str, css_class: str, *, title: str = "", style: str = "") -> str:
    """Render one escaped metadata badge for the Qt rich-text document."""
    safe_text = html.escape(text, quote=True)
    safe_title = html.escape(title, quote=True)
    title_attr = f' title="{safe_title}"' if safe_title else ""
    style_attr = f' style="{style}"' if style else ""
    return f'<span class="meta-badge {css_class}"{title_attr}{style_attr}>{safe_text}</span>'


def danmaku_author_badges(message: DanmakuMessage) -> tuple[MessageBadge, ...]:
    """Return the already-normalized badges attached to a danmaku author."""
    return message.author.badges


def danmaku_author_badges_html(message: DanmakuMessage) -> str:
    """Render normalized author badges as escaped Qt rich text."""
    badges = []
    for badge in danmaku_author_badges(message):
        style = f"color: {badge.color};"
        badges.append(
            _badge(
                badge.text,
                f"{badge.kind.value}-badge",
                title=badge.title,
                style=style,
            )
        )

    if not badges:
        return ""
    return "&nbsp;".join(badges) + "&nbsp;"


def danmaku_emoticon_url(message: DanmakuMessage) -> str:
    """Return the URL for a pure emoticon message, if its segments allow one."""
    image_segments = [segment for segment in message.segments if isinstance(segment, ImageSegment)]
    has_text = any(isinstance(segment, TextSegment) for segment in message.segments)
    if len(image_segments) == 1 and not has_text:
        return image_segments[0].url
    return ""


def danmaku_emoticon_scaled_size(segment: ImageSegment) -> tuple[int, int]:
    """Scale a source image to the compact Qt danmaku bounds."""
    scale = DANMAKU_EMOTICON_MAX_HEIGHT / segment.height
    width = max(1, round(segment.width * scale))
    height = DANMAKU_EMOTICON_MAX_HEIGHT
    if width > DANMAKU_EMOTICON_MAX_WIDTH:
        width = DANMAKU_EMOTICON_MAX_WIDTH
        height = max(1, round(segment.height * (DANMAKU_EMOTICON_MAX_WIDTH / segment.width)))
    return width, height


def _danmaku_segment_html(segment: MessageSegment) -> str:
    """Render one normalized message segment for the Qt rich-text document."""
    if isinstance(segment, ImageSegment):
        width, height = danmaku_emoticon_scaled_size(segment)
        alt = html.escape(segment.text.strip() or "表情", quote=True)
        src = html.escape(segment.url, quote=True)
        return f'<img class="emoticon" src="{src}" width="{width}" height="{height}" alt="{alt}" />'
    if isinstance(segment, ReplySegment):
        reply_text = segment.text.rstrip()
        if not reply_text:
            return ""
        return f'<span class="reply">{html.escape(reply_text, quote=True)}&nbsp;</span>'
    return html.escape(segment.text, quote=True)


def danmaku_message_content_html(message: DanmakuMessage) -> str:
    """Render all normalized danmaku fragments with HTML escaping."""
    return "".join(_danmaku_segment_html(segment) for segment in message.segments)


def danmaku_message_emoticon_urls(message: DanmakuMessage) -> list[str]:
    """Return unique image URLs used by a danmaku for asynchronous Qt loading."""
    urls: list[str] = []
    seen: set[str] = set()
    for segment in message.segments:
        if not isinstance(segment, ImageSegment) or segment.url in seen:
            continue
        urls.append(segment.url)
        seen.add(segment.url)
    return urls
