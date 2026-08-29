"""Convert raw blivedm web messages into stable HUD message contracts."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

import blivedm.models.open_live as open_models
import blivedm.models.web as web_models

from ..live.gift_effects import normalize_official_resource_url
from .messages import (
    DanmakuMessage,
    GiftCurrency,
    GiftEffectLayout,
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
    SuperChatMessage,
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
SC_DEFAULT_BACKGROUND_COLOR = "#3C2A4D"
SC_DEFAULT_BOTTOM_COLOR = "#2A2038"
SC_DEFAULT_PRICE_COLOR = "#FFD86E"
GUARD_NAMES = {1: "总督", 2: "提督", 3: "舰长"}
GUARD_GIFT_IDS = {1: 10001, 2: 10002, 3: 10003}
# ``effect_id`` is the buyer-side animation; these are the room-side fallbacks
# used by the anchor's live-room view when ``room_effect_id`` is absent.
GUARD_DEFAULT_EFFECT_IDS = {1: 592, 2: 591, 3: 590}


class MessageConversionError(ValueError):
    """Indicate that a third-party message cannot satisfy the message contract."""


@dataclass(frozen=True, slots=True)
class GuardPurchase:
    """Normalized Bilibili guard purchase data and its optional effect id."""

    uid: int
    username: str
    guard_level: int
    quantity: int
    unit_price: int
    gift_id: int
    gift_name: str
    effect_id: int
    event_id: str = ""


def to_hud_message(message: object) -> HudMessage:
    """Convert one supported blivedm message or raise a typed conversion error."""
    try:
        if isinstance(message, web_models.DanmakuMessage):
            return _danmaku_message(message)
        if isinstance(message, web_models.SuperChatMessage):
            return _super_chat_message(message)
        if isinstance(message, web_models.GiftMessage):
            return _gift_message(message)
        if isinstance(message, web_models.GuardBuyMessage):
            return to_hud_guard_message(guard_purchase_from_guard_buy(message))
        if isinstance(message, web_models.UserToastV2Message):
            purchase = guard_purchase_from_user_toast(message)
            if purchase is None:
                raise MessageConversionError("gifted guard toast is not a display event")
            return to_hud_guard_message(purchase)
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
    return to_hud_gift_message(message)


def _super_chat_message(message: web_models.SuperChatMessage) -> SuperChatMessage:
    """Normalize a web Super Chat event into the shared HUD contract."""
    return to_hud_super_chat_message(message)


def to_hud_super_chat_message(message: web_models.SuperChatMessage) -> SuperChatMessage:
    """Convert a web Super Chat event and preserve its official card colors and assets."""
    content = _string(message.message).strip()
    price_color = _sc_color(message.background_price_color, SC_DEFAULT_PRICE_COLOR)
    author = MessageAuthor(
        uid=max(0, _integer(message.uid)),
        name=_string(message.uname),
        color=price_color,
    )
    return SuperChatMessage(
        author=author,
        segments=(TextSegment(content),),
        message_id=max(0, _integer(message.id)),
        price=max(0, _integer(message.price)),
        message=content,
        start_time=max(0, _integer(message.start_time)),
        end_time=max(0, _integer(message.end_time)),
        background_color=_sc_color(message.background_color, SC_DEFAULT_BACKGROUND_COLOR),
        background_bottom_color=_sc_color(message.background_bottom_color, SC_DEFAULT_BOTTOM_COLOR),
        background_icon=normalize_official_resource_url(message.background_icon),
        background_image=normalize_official_resource_url(message.background_image),
        background_price_color=price_color,
    )


def to_hud_open_super_chat_message(message: open_models.SuperChatMessage) -> SuperChatMessage:
    """Convert an open-platform Super Chat event using the shared fallback theme."""
    content = _string(message.message).strip()
    author = MessageAuthor(
        uid=0,
        name=_string(message.uname),
        color=SC_DEFAULT_PRICE_COLOR,
    )
    return SuperChatMessage(
        author=author,
        segments=(TextSegment(content),),
        message_id=max(0, _integer(message.message_id)),
        price=max(0, _integer(message.rmb)),
        message=content,
        start_time=max(0, _integer(message.start_time)),
        end_time=max(0, _integer(message.end_time)),
    )


def to_hud_gift_message(
    message: web_models.GiftMessage,
    *,
    gift_effect_url: str = "",
    gift_animation_url: str = "",
    gift_effect_layout: GiftEffectLayout | None = None,
) -> GiftMessage:
    """Normalize a gift and attach validated official effect resource URLs."""
    action = _string(message.action)
    gift_name = _string(message.gift_name)
    quantity = max(0, _integer(message.num))
    unit_price = max(0, _integer(message.price))
    gift_id = max(0, _integer(message.gift_id))
    gift_image_url = _http_url(message.gift_img_basic)
    author = MessageAuthor(uid=max(0, _integer(message.uid)), name=_string(message.uname), color=GIFT_COLOR)
    return GiftMessage(
        author=author,
        segments=(TextSegment(f"{action} {gift_name} x{quantity}"),),
        action=action,
        gift_name=gift_name,
        quantity=quantity,
        unit_price=unit_price,
        currency=_gift_currency(message.coin_type),
        gift_id=gift_id,
        gift_image_url=gift_image_url,
        gift_effect_url=_http_url(gift_effect_url),
        gift_animation_url=normalize_official_resource_url(gift_animation_url),
        gift_effect_layout=gift_effect_layout,
    )


def to_hud_guard_message(
    purchase: GuardPurchase,
    *,
    gift_effect_url: str = "",
    gift_animation_url: str = "",
    gift_effect_layout: GiftEffectLayout | None = None,
) -> GiftMessage:
    """Convert one normalized guard purchase into the shared gift contract."""
    gift_name = purchase.gift_name
    if not gift_name:
        gift_name = GUARD_NAMES.get(purchase.guard_level, "大航海")
    quantity = max(0, purchase.quantity)
    unit_price = max(0, purchase.unit_price)
    gift_id = max(0, purchase.gift_id)
    author = MessageAuthor(
        uid=max(0, purchase.uid),
        name=purchase.username,
        color=GIFT_COLOR,
        badges=_guard_badges(purchase.guard_level),
    )
    return GiftMessage(
        author=author,
        segments=(TextSegment(f"开通 {gift_name} x{quantity}"),),
        action="开通",
        gift_name=gift_name,
        quantity=quantity,
        unit_price=unit_price,
        currency=GiftCurrency.GOLD,
        gift_id=gift_id,
        gift_effect_url=_http_url(gift_effect_url),
        gift_animation_url=normalize_official_resource_url(gift_animation_url),
        gift_effect_layout=gift_effect_layout,
    )


def parse_guard_purchase(data: Mapping[str, object]) -> GuardPurchase | None:
    """Parse a web guard command and reject malformed or gifted duplicate events."""
    guard_info = _mapping(data.get("guard_info"))
    pay_info = _mapping(data.get("pay_info"))
    gift_info = _mapping(data.get("gift_info"))
    option = _mapping(data.get("option"))
    sender_info = _mapping(data.get("sender_uinfo"))
    sender_base = _mapping(sender_info.get("base"))
    effect_info = _mapping(data.get("effect_info"))

    uid = _integer(_preferred(sender_info.get("uid"), data.get("uid")))
    username = _string(
        _preferred(
            sender_base.get("name"),
            _preferred(sender_info.get("username"), data.get("username")),
        )
    )
    guard_level = _integer(_preferred(guard_info.get("guard_level"), data.get("guard_level")))
    if guard_level not in GUARD_NAMES:
        return None

    source = _integer(_preferred(option.get("source"), data.get("source")))
    if source == 2:
        return None

    quantity = _integer(_preferred(pay_info.get("num"), _preferred(data.get("num"), data.get("guard_num"))))
    unit_price = _integer(_preferred(pay_info.get("price"), data.get("price")))
    gift_id = _integer(_preferred(gift_info.get("gift_id"), data.get("gift_id")))
    if gift_id <= 0:
        gift_id = GUARD_GIFT_IDS[guard_level]
    gift_name = _string(
        _preferred(
            gift_info.get("gift_name"),
            _preferred(data.get("gift_name"), data.get("role_name")),
        )
    )
    start_time = _integer(_preferred(guard_info.get("start_time"), data.get("start_time")))
    event_id = _string(data.get("payflow_id"))
    if not event_id:
        event_id = _string(data.get("tid"))
    if not event_id and start_time > 0:
        event_id = str(start_time)

    is_group = _boolean(_preferred(option.get("is_group"), data.get("is_group")))
    if is_group:
        effect_id = _integer(
            _preferred(effect_info.get("room_group_effect_id"), data.get("room_group_effect_id"))
        )
    else:
        effect_id = _integer(_preferred(effect_info.get("room_effect_id"), data.get("room_effect_id")))
    if effect_id <= 0:
        effect_id = GUARD_DEFAULT_EFFECT_IDS[guard_level]

    return GuardPurchase(
        uid=max(0, uid),
        username=username,
        guard_level=guard_level,
        quantity=max(0, quantity),
        unit_price=max(0, unit_price),
        gift_id=max(0, gift_id),
        gift_name=gift_name,
        effect_id=max(0, effect_id),
        event_id=event_id,
    )


def guard_purchase_from_guard_buy(
    message: web_models.GuardBuyMessage,
    *,
    effect_id: int = 0,
) -> GuardPurchase:
    """Normalize the legacy typed GUARD_BUY model for direct handler callbacks."""
    resolved_effect_id = effect_id
    if resolved_effect_id <= 0:
        resolved_effect_id = GUARD_DEFAULT_EFFECT_IDS.get(message.guard_level, 0)
    gift_id = message.gift_id
    if gift_id <= 0:
        gift_id = GUARD_GIFT_IDS.get(message.guard_level, 0)
    return GuardPurchase(
        uid=max(0, message.uid),
        username=_string(message.username),
        guard_level=message.guard_level,
        quantity=max(0, message.num),
        unit_price=max(0, message.price),
        gift_id=max(0, gift_id),
        gift_name=_string(message.gift_name),
        effect_id=max(0, resolved_effect_id),
        event_id=str(message.start_time) if message.start_time > 0 else "",
    )


def guard_purchase_from_user_toast(
    message: web_models.UserToastV2Message,
    *,
    effect_id: int = 0,
) -> GuardPurchase | None:
    """Normalize a typed V2 toast while suppressing Bilibili's gifted duplicate."""
    if message.source == 2:
        return None
    resolved_effect_id = effect_id
    if resolved_effect_id <= 0:
        resolved_effect_id = GUARD_DEFAULT_EFFECT_IDS.get(message.guard_level, 0)
    gift_id = message.gift_id
    if gift_id <= 0:
        gift_id = GUARD_GIFT_IDS.get(message.guard_level, 0)
    return GuardPurchase(
        uid=max(0, message.uid),
        username=_string(message.username),
        guard_level=message.guard_level,
        quantity=max(0, message.num),
        unit_price=max(0, message.price),
        gift_id=max(0, gift_id),
        gift_name=GUARD_NAMES.get(message.guard_level, "大航海"),
        effect_id=max(0, resolved_effect_id),
        event_id=str(message.start_time) if message.start_time > 0 else "",
    )


def parse_open_guard_purchase(data: Mapping[str, object]) -> GuardPurchase | None:
    """Parse the open-platform guard payload into the same stable purchase contract."""
    user_info = _mapping(data.get("user_info"))
    guard_level = _integer(data.get("guard_level"))
    if guard_level not in GUARD_NAMES:
        return None
    gift_id = GUARD_GIFT_IDS[guard_level]
    return GuardPurchase(
        uid=0,
        username=_string(user_info.get("uname")),
        guard_level=guard_level,
        quantity=max(0, _integer(data.get("guard_num"))),
        unit_price=max(0, _integer(data.get("price"))),
        gift_id=gift_id,
        gift_name=GUARD_NAMES[guard_level],
        effect_id=GUARD_DEFAULT_EFFECT_IDS[guard_level],
        event_id=_string(data.get("msg_id")),
    )


def guard_purchase_from_open_guard(message: open_models.GuardBuyMessage) -> GuardPurchase:
    """Normalize a typed open-platform guard event for direct handler callbacks."""
    return GuardPurchase(
        uid=0,
        username=_string(message.user_info.uname),
        guard_level=message.guard_level,
        quantity=max(0, message.guard_num),
        unit_price=max(0, message.price),
        gift_id=GUARD_GIFT_IDS.get(message.guard_level, 0),
        gift_name=GUARD_NAMES.get(message.guard_level, "大航海"),
        effect_id=GUARD_DEFAULT_EFFECT_IDS.get(message.guard_level, 0),
        event_id=_string(message.msg_id),
    )


def _gift_currency(value: object) -> GiftCurrency:
    """Normalize an upstream coin type without leaking its string values."""
    coin_type = _string(value).lower()
    return {
        "gold": GiftCurrency.GOLD,
        "silver": GiftCurrency.SILVER,
    }.get(coin_type, GiftCurrency.UNKNOWN)


def _sc_color(value: object, fallback: str) -> str:
    """Accept only six-digit hex colors before they reach Qt rich-text CSS."""
    color = _string(value).strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        return color
    return fallback


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


def to_hud_like_message(
    data: Mapping[str, object],
    *,
    count: int | None = None,
) -> InteractMessage:
    """Normalize one web ``LIKE_INFO_V3_CLICK`` payload for HUD consumers."""
    interaction = InteractionKind.LIKE
    like_count = max(1, _integer(data.get("count"))) if count is None else max(1, count)
    author = MessageAuthor(
        uid=max(0, _integer(data.get("uid"))),
        name=_string(data.get("uname")),
        color=INTERACT_COLOR,
    )
    return InteractMessage(
        author=author,
        segments=(TextSegment(interaction.text),),
        interaction=interaction,
        count=like_count,
    )


def to_hud_total_likes(data: Mapping[str, object]) -> int:
    """Normalize the room total from one web ``LIKE_INFO_V3_UPDATE`` payload."""
    return max(0, _integer(data.get("click_count")))


def to_hud_voice_report_like_messages(
    data: Mapping[str, object],
) -> tuple[InteractMessage, ...]:
    """Normalize per-user entries and preserve a single-user like count."""
    raw_users = data.get("users")
    if not isinstance(raw_users, list):
        return ()

    users = tuple(
        _mapping(raw_user)
        for raw_user in raw_users
        if isinstance(raw_user, Mapping)
    )
    if len(users) != 1:
        return tuple(to_hud_like_message(user) for user in users)

    like_count = max(1, _integer(data.get("count")))
    return (to_hud_like_message(users[0], count=like_count),)


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


def _guard_badges(guard_level: int) -> tuple[MessageBadge, ...]:
    """Attach the same compact guard badge to a normalized guard purchase."""
    badge = _privilege_badge(guard_level)
    if badge is None:
        return ()
    return (badge,)


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
    """Validate an external image URL and normalize dimensions for the message contract."""
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


def _mapping(value: object) -> dict[str, object]:
    """Narrow a raw nested object to a string-key mapping at the protocol boundary."""
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _preferred(primary: object, fallback: object) -> object:
    """Prefer a present nested field while preserving valid falsey values."""
    return fallback if primary is None else primary


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
    """Normalize external text fields to strings for the message contract."""
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)
