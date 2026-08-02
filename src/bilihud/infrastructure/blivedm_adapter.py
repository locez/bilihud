"""Convert raw blivedm web messages into stable HUD domain messages."""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

import blivedm.models.web as web_models

from ..domain.messages import (
    DanmakuMessage,
    GiftCurrency,
    GiftMessage,
    HudMessage,
    ImageSegment,
    InteractionKind,
    InteractMessage,
    MessageAuthor,
    MessageBadge,
    MessageBadgeKind,
    MessageSegment,
    ReplySegment,
    SystemMessageLevel,
    TextSegment,
    make_system_message,
)

logger = logging.getLogger(__name__)

DEFAULT_DANMAKU_COLOR = "#66CCFF"
GIFT_COLOR = "#FFD700"
INTERACT_COLOR = "#AAAAAA"
VIP_COLOR = "#FF69B4"
ADMIN_COLOR = "#FF4500"
MEDAL_BADGE_COLOR = "#FF79C6"
WEALTH_BADGE_COLOR = "#C9B6FF"


class MessageConversionError(ValueError):
    """Indicate that a third-party message cannot satisfy the domain contract."""


def to_hud_message(message: object) -> HudMessage:
    """Convert one supported blivedm message or raise a typed conversion error."""
    try:
        if isinstance(message, web_models.DanmakuMessage):
            return _danmaku_message(message)
        if isinstance(message, web_models.GiftMessage):
            return _gift_message(message)
        if isinstance(message, web_models.InteractWordV2Message):
            return _interact_message(message)
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise MessageConversionError("blivedm message fields are invalid") from error

    message_type = type(message).__name__
    raise MessageConversionError(f"unsupported blivedm message type: {message_type}")


def to_hud_message_or_system(message: object) -> HudMessage:
    """Convert a message and return a visible error message when conversion fails."""
    try:
        return to_hud_message(message)
    except MessageConversionError as error:
        logger.warning("Failed to convert blivedm message: %s", error)
        return make_system_message("收到无法解析的直播消息", SystemMessageLevel.ERROR)


def _danmaku_message(message: web_models.DanmakuMessage) -> DanmakuMessage:
    """Normalize a raw danmaku model, including reply and emoticon fragments."""
    author = _danmaku_author(message)
    segments = _danmaku_segments(message)
    return DanmakuMessage(author=author, segments=segments)


def _gift_message(message: web_models.GiftMessage) -> GiftMessage:
    """Normalize the fields needed to render a gift event."""
    action = _string(message.action)
    gift_name = _string(message.gift_name)
    quantity = max(0, _integer(message.num))
    unit_price = max(0, _integer(message.price))
    author = MessageAuthor(uid=max(0, _integer(message.uid)), name=_string(message.uname), color=GIFT_COLOR)
    return GiftMessage(
        author=author,
        segments=(TextSegment(f"{action} {gift_name} x{quantity}"),),
        action=action,
        gift_name=gift_name,
        quantity=quantity,
        unit_price=unit_price,
        currency=_gift_currency(message.coin_type),
    )


def _gift_currency(value: object) -> GiftCurrency:
    """Normalize an upstream coin type without leaking its string values."""
    coin_type = _string(value).lower()
    return {
        "gold": GiftCurrency.GOLD,
        "silver": GiftCurrency.SILVER,
    }.get(coin_type, GiftCurrency.UNKNOWN)


def _interact_message(message: web_models.InteractWordV2Message) -> InteractMessage:
    """Normalize an audience interaction and preserve its shared description."""
    interaction = _interaction_kind(_integer(message.msg_type))
    author = MessageAuthor(
        uid=max(0, _integer(message.uid)),
        name=_string(message.username),
        color=INTERACT_COLOR,
    )
    return InteractMessage(
        author=author,
        segments=(TextSegment(interaction.text),),
        interaction=interaction,
    )


def _danmaku_author(message: web_models.DanmakuMessage) -> MessageAuthor:
    """Build the normalized author color and badges from raw danmaku metadata."""
    privilege_type = _integer(message.privilege_type)
    if privilege_type > 0:
        color = GIFT_COLOR
    elif _boolean(message.vip) or _boolean(message.svip):
        color = VIP_COLOR
    elif _boolean(message.admin):
        color = ADMIN_COLOR
    else:
        color = DEFAULT_DANMAKU_COLOR

    return MessageAuthor(
        uid=max(0, _integer(message.uid)),
        name=_string(message.uname),
        color=color,
        badges=_danmaku_badges(message, privilege_type),
    )


def _danmaku_badges(
    message: web_models.DanmakuMessage,
    privilege_type: int,
) -> tuple[MessageBadge, ...]:
    """Translate raw author metadata into the badges shared by both renderers."""
    badges: list[MessageBadge] = []
    medal_name = _string(message.medal_name).strip()
    medal_level = _integer(message.medal_level)
    if medal_name and medal_level > 0:
        badges.append(
            MessageBadge(
                kind=MessageBadgeKind.MEDAL,
                text=f"{medal_name} {medal_level}",
                title="粉丝牌",
                color=MEDAL_BADGE_COLOR,
            )
        )

    wealth_level = _integer(message.wealth_level)
    if wealth_level > 0:
        badges.append(
            MessageBadge(
                kind=MessageBadgeKind.WEALTH,
                text=f"✦ {wealth_level}",
                title="财富等级",
                color=WEALTH_BADGE_COLOR,
            )
        )

    privilege_badge = _privilege_badge(privilege_type)
    if privilege_badge is not None:
        badges.append(privilege_badge)
    return tuple(badges)


def _privilege_badge(privilege_type: int) -> MessageBadge | None:
    """Map a Bilibili guard level to one compact, stable badge."""
    icon = {1: "🛳︎", 2: "⛴︎", 3: "⚓︎"}.get(privilege_type)
    color = {1: "#FFD700", 2: "#C9B6FF", 3: "#86C8FF"}.get(privilege_type)
    if icon is None or color is None:
        return None
    return MessageBadge(
        kind=MessageBadgeKind.PRIVILEGE,
        text=icon,
        title="大航海",
        color=color,
    )


def _danmaku_segments(message: web_models.DanmakuMessage) -> tuple[MessageSegment, ...]:
    """Parse reply and emoticon metadata into typed fragments with safe fallbacks."""
    segments: list[MessageSegment] = []
    extra = _optional_mapping(_mapping_value(message.mode_info, "extra"))
    if extra.get("show_reply") is not False:
        reply_name = _string(extra.get("reply_uname")).strip()
        if reply_name:
            segments.append(ReplySegment(f"@{reply_name} "))

    text = _string(message.msg).strip()
    options = _optional_mapping(message.emoticon_options)
    if _integer(message.dm_type) == 1:
        image = _image_segment(text or "表情", options)
        if image is not None:
            segments.append(image)
            return tuple(segments)

    inline_images = _inline_images(extra)
    segments.extend(_inline_segments(text, inline_images))
    return tuple(segments)


def _inline_segments(text: str, images: dict[str, ImageSegment]) -> tuple[MessageSegment, ...]:
    """Split text around valid inline emoticon tokens without leaking raw options."""
    if not images:
        return (TextSegment(text),)

    tokens = tuple(sorted(images, key=len, reverse=True))
    pattern = re.compile("|".join(re.escape(token) for token in tokens))
    segments: list[MessageSegment] = []
    last_end = 0
    for match in pattern.finditer(text):
        if match.start() > last_end:
            segments.append(TextSegment(text[last_end : match.start()]))
        token = match.group(0)
        segments.append(images[token])
        last_end = match.end()
    if last_end < len(text) or not segments:
        segments.append(TextSegment(text[last_end:]))
    return tuple(segments)


def _inline_images(extra: dict[str, object]) -> dict[str, ImageSegment]:
    """Extract only validated inline image metadata from the third-party payload."""
    raw_emots = extra.get("emots")
    if not isinstance(raw_emots, dict):
        return {}

    images: dict[str, ImageSegment] = {}
    for raw_token, raw_options in raw_emots.items():
        token = _string(raw_token)
        if not token:
            continue
        options = _optional_mapping(raw_options)
        image = _image_segment(token, options)
        if image is not None:
            images[token] = image
    return images


def _image_segment(text: str, options: dict[str, object]) -> ImageSegment | None:
    """Validate an external image URL and normalize dimensions for the domain."""
    url = _http_url(options.get("url"))
    if not url:
        return None
    return ImageSegment(
        text=text,
        url=url,
        width=_dimension(options.get("width")),
        height=_dimension(options.get("height")),
    )


def _interaction_kind(msg_type: int) -> InteractionKind:
    """Map a current or unknown upstream interaction code to stable semantics."""
    return {
        1: InteractionKind.ENTER,
        2: InteractionKind.FOLLOW,
        3: InteractionKind.SHARE,
        4: InteractionKind.SPECIAL_FOLLOW,
        5: InteractionKind.MUTUAL_FOLLOW,
        6: InteractionKind.LIKE,
    }.get(msg_type, InteractionKind.ENTER)


def _mapping_value(value: object, key: str) -> object:
    """Read one optional mapping field without exposing third-party dictionaries."""
    if isinstance(value, dict):
        return value.get(key)
    return None


def _optional_mapping(value: object) -> dict[str, object]:
    """Parse optional JSON-like metadata and degrade malformed metadata to empty."""
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if isinstance(key, str)}
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded: object = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {key: item for key, item in decoded.items() if isinstance(key, str)}


def _http_url(value: object) -> str:
    """Allow only absolute HTTP(S) image URLs at the external boundary."""
    if not isinstance(value, str):
        return ""
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _dimension(value: object) -> int:
    """Normalize missing or invalid source dimensions to a safe square fallback."""
    if not isinstance(value, (int, float, str)):
        return 1
    try:
        dimension = int(value)
    except ValueError:
        return 1
    return dimension if dimension > 0 else 1


def _integer(value: object) -> int:
    """Normalize a numeric third-party field without raising on malformed input."""
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _boolean(value: object) -> bool:
    """Normalize the integer flags used by blivedm's web model."""
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no"}
    return bool(value)


def _string(value: object) -> str:
    """Normalize external text fields to strings for the domain contract."""
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)
