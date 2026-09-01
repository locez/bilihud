"""In-memory Mirror state and serialization for normalized HUD messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

from ..danmaku.format import danmaku_emoticon_scaled_size, gift_value_text
from ..danmaku.messages import (
    DanmakuMessage,
    GiftEffectFrame,
    GiftEffectLayout,
    GiftMessage,
    HudMessage,
    ImageSegment,
    InteractMessage,
    MessageBadge,
    MessageSegment,
    ReplySegment,
    SuperChatMessage,
    SystemMessage,
)

MIRROR_DEFAULT_PORT = 2233
MIRROR_ROUTE = "/bilihud-mirror"
MIRROR_EVENTS_ROUTE = "/bilihud-mirror/events"
MIRROR_IMAGE_ROUTE = "/bilihud-mirror/image"
MIRROR_MEDIA_ROUTE = "/bilihud-mirror/media"
MIRROR_ICON_ROUTE = "/bilihud-mirror/icon.png"
MIRROR_MAX_MESSAGES = 200


@dataclass(frozen=True, slots=True)
class MirrorDisplaySettings:
    """Describe the live browser presentation settings shared with Mirror clients."""

    gift_effects_enabled: bool = False
    danmaku_x: int = 4
    danmaku_y: int = 4
    font_family: str = ""
    user_avatars_enabled: bool = False

    def __post_init__(self) -> None:
        """Reject positions outside the viewport percentage range."""
        if not 0 <= self.danmaku_x <= 100 or not 0 <= self.danmaku_y <= 100:
            raise ValueError("Mirror danmaku position must be between 0 and 100")


class MirrorTextSegment(TypedDict):
    """Serialized literal text fragment sent to the Mirror browser."""

    type: Literal["text"]
    text: str


class MirrorReplySegment(TypedDict):
    """Serialized reply prefix sent to the Mirror browser."""

    type: Literal["reply"]
    text: str


class MirrorImageSegment(TypedDict):
    """Serialized image fragment sent to the Mirror browser."""

    type: Literal["image"]
    text: str
    url: str
    width: int
    height: int


type MirrorSegment = MirrorTextSegment | MirrorReplySegment | MirrorImageSegment


class MirrorBadge(TypedDict):
    """Serialized author badge sent to the Mirror browser."""

    type: str
    text: str
    title: str
    color: str


class MirrorGiftEffectFrame(TypedDict):
    """Serialized packed-video rectangle used by the Mirror compositor."""

    x: int
    y: int
    width: int
    height: int


class MirrorGiftEffectLayout(TypedDict):
    """Serialized color and alpha rectangles for one packed gift video."""

    rgbFrame: MirrorGiftEffectFrame
    alphaFrame: MirrorGiftEffectFrame


class MirrorEntry(TypedDict):
    """Stable JSON-compatible representation of one HUD message."""

    seq: int
    kind: Literal["danmaku", "gift", "super_chat", "interact", "system"]
    user: str
    userColor: str
    userAvatarUrl: NotRequired[str]
    segments: list[MirrorSegment]
    badges: NotRequired[list[MirrorBadge]]
    giftId: NotRequired[int]
    giftAction: NotRequired[str]
    giftValue: NotRequired[str]
    giftName: NotRequired[str]
    giftQuantity: NotRequired[int]
    giftImageUrl: NotRequired[str]
    giftEffectUrl: NotRequired[str]
    giftAnimationUrl: NotRequired[str]
    giftEffectLayout: NotRequired[MirrorGiftEffectLayout]
    scId: NotRequired[int]
    scPrice: NotRequired[int]
    scBackgroundColor: NotRequired[str]
    scBackgroundBottomColor: NotRequired[str]
    scBackgroundPriceColor: NotRequired[str]


class MirrorSettingsPayload(TypedDict):
    """Serialized display settings sent to already-connected Mirror clients."""

    giftEffects: bool
    userAvatars: bool
    fontFamily: str
    danmakuX: int
    danmakuY: int


def mirror_settings_payload(settings: MirrorDisplaySettings) -> MirrorSettingsPayload:
    """Serialize validated display settings for the browser event protocol."""
    return {
        "giftEffects": settings.gift_effects_enabled,
        "userAvatars": settings.user_avatars_enabled,
        "fontFamily": settings.font_family,
        "danmakuX": settings.danmaku_x,
        "danmakuY": settings.danmaku_y,
    }


def user_color_for_message(message: HudMessage) -> str:
    """Return the color normalized by the infrastructure adapter."""
    return message.author.color


def _badge_to_mirror(badge: MessageBadge) -> MirrorBadge:
    """Serialize one typed message badge without exposing its enum instance."""
    return {
        "type": badge.kind.value,
        "text": badge.text,
        "title": badge.title,
        "color": badge.color,
    }


def _segment_to_mirror(segment: MessageSegment) -> MirrorSegment:
    """Serialize one typed message fragment for the browser protocol."""
    if isinstance(segment, ImageSegment):
        width, height = danmaku_emoticon_scaled_size(segment)
        return {
            "type": "image",
            "text": segment.text,
            "url": segment.url,
            "width": width,
            "height": height,
        }
    if isinstance(segment, ReplySegment):
        return {"type": "reply", "text": segment.text}
    return {"type": "text", "text": segment.text}


def _gift_effect_frame_to_mirror(frame: GiftEffectFrame) -> MirrorGiftEffectFrame:
    """Serialize one validated packed-video rectangle for browser code."""
    return {
        "x": frame.x,
        "y": frame.y,
        "width": frame.width,
        "height": frame.height,
    }


def _gift_effect_layout_to_mirror(layout: GiftEffectLayout) -> MirrorGiftEffectLayout:
    """Serialize the color/mask layout without exposing the domain dataclass."""
    return {
        "rgbFrame": _gift_effect_frame_to_mirror(layout.rgb_frame),
        "alphaFrame": _gift_effect_frame_to_mirror(layout.alpha_frame),
    }


def danmaku_segments(message: DanmakuMessage) -> list[MirrorSegment]:
    """Serialize normalized danmaku fragments using the Mirror wire contract."""
    return [_segment_to_mirror(segment) for segment in message.segments]


def _segments_for(message: HudMessage) -> list[MirrorSegment]:
    """Serialize any supported message variant's shared fragment sequence."""
    if isinstance(message, DanmakuMessage):
        return danmaku_segments(message)
    return [_segment_to_mirror(segment) for segment in message.segments]


def message_to_mirror_entry(seq: int, message: HudMessage) -> MirrorEntry:
    """Convert one normalized message into the browser-facing Mirror entry."""
    if isinstance(message, DanmakuMessage):
        entry: MirrorEntry = {
            "seq": seq,
            "kind": "danmaku",
            "user": message.author.name,
            "userColor": user_color_for_message(message),
            "segments": danmaku_segments(message),
        }
        _add_author_avatar(entry, message)
        if message.author.badges:
            entry["badges"] = [_badge_to_mirror(badge) for badge in message.author.badges]
        return entry

    if isinstance(message, GiftMessage):
        entry: MirrorEntry = {
            "seq": seq,
            "kind": "gift",
            "user": message.author.name,
            "userColor": user_color_for_message(message),
            "segments": _segments_for(message),
            "giftId": message.gift_id,
            "giftAction": message.action,
            "giftValue": gift_value_text(message),
            "giftName": message.gift_name,
            "giftQuantity": message.quantity,
            "giftImageUrl": message.gift_image_url,
            "giftEffectUrl": message.gift_effect_url,
            "giftAnimationUrl": message.gift_animation_url,
        }
        _add_author_avatar(entry, message)
        if message.gift_effect_layout is not None:
            entry["giftEffectLayout"] = _gift_effect_layout_to_mirror(message.gift_effect_layout)
        return entry

    if isinstance(message, SuperChatMessage):
        entry: MirrorEntry = {
            "seq": seq,
            "kind": "super_chat",
            "user": message.author.name,
            "userColor": user_color_for_message(message),
            "segments": _segments_for(message),
            "scId": message.message_id,
            "scPrice": message.price,
            "scBackgroundColor": message.background_color,
            "scBackgroundBottomColor": message.background_bottom_color,
            "scBackgroundPriceColor": message.background_price_color,
        }
        _add_author_avatar(entry, message)
        return entry

    if isinstance(message, InteractMessage):
        entry: MirrorEntry = {
            "seq": seq,
            "kind": "interact",
            "user": message.author.name,
            "userColor": user_color_for_message(message),
            "segments": [{"type": "text", "text": message.text}],
        }
        _add_author_avatar(entry, message)
        return entry

    if isinstance(message, SystemMessage):
        entry: MirrorEntry = {
            "seq": seq,
            "kind": "system",
            "user": message.author.name,
            "userColor": user_color_for_message(message),
            "segments": _segments_for(message),
        }
        _add_author_avatar(entry, message)
        return entry

    raise TypeError(f"unsupported HUD message type: {type(message).__name__}")


def _add_author_avatar(entry: MirrorEntry, message: HudMessage) -> None:
    """Attach a normalized avatar URL when the message author provides one."""
    avatar_url = message.author.avatar_url
    if avatar_url:
        entry["userAvatarUrl"] = avatar_url


class MirrorState:
    """Keep a bounded history of serialized messages for Mirror clients."""

    def __init__(self, max_messages: int = MIRROR_MAX_MESSAGES) -> None:
        """Create state with a maximum number of retained entries."""
        if max_messages <= 0:
            raise ValueError("Mirror message limit must be positive")
        self.max_messages: int = max_messages
        self._next_seq: int = 1
        self._messages: list[MirrorEntry] = []

    def add_message(self, message: HudMessage) -> MirrorEntry:
        """Serialize and append one message, evicting the oldest entries if needed."""
        entry = message_to_mirror_entry(self._next_seq, message)
        self._next_seq += 1
        self._messages.append(entry)
        if len(self._messages) > self.max_messages:
            self._messages = self._messages[-self.max_messages :]
        return entry

    def snapshot(self) -> list[MirrorEntry]:
        """Return the current bounded history in sequence order."""
        return list(self._messages)
