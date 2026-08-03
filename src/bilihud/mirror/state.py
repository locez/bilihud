"""In-memory Mirror state and serialization for normalized HUD messages."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from ..danmaku.format import danmaku_emoticon_scaled_size
from ..danmaku.messages import (
    DanmakuMessage,
    GiftMessage,
    HudMessage,
    ImageSegment,
    InteractMessage,
    MessageBadge,
    MessageSegment,
    ReplySegment,
    SystemMessage,
)

MIRROR_DEFAULT_PORT = 2233
MIRROR_ROUTE = "/bilihud-mirror"
MIRROR_EVENTS_ROUTE = "/bilihud-mirror/events"
MIRROR_IMAGE_ROUTE = "/bilihud-mirror/image"
MIRROR_MAX_MESSAGES = 200


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


class MirrorEntry(TypedDict):
    """Stable JSON-compatible representation of one HUD message."""

    seq: int
    kind: Literal["danmaku", "gift", "interact", "system"]
    user: str
    userColor: str
    segments: list[MirrorSegment]
    badges: NotRequired[list[MirrorBadge]]


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
        if message.author.badges:
            entry["badges"] = [_badge_to_mirror(badge) for badge in message.author.badges]
        return entry

    if isinstance(message, GiftMessage):
        return {
            "seq": seq,
            "kind": "gift",
            "user": message.author.name,
            "userColor": user_color_for_message(message),
            "segments": _segments_for(message),
        }

    if isinstance(message, InteractMessage):
        return {
            "seq": seq,
            "kind": "interact",
            "user": message.author.name,
            "userColor": user_color_for_message(message),
            "segments": _segments_for(message),
        }

    if isinstance(message, SystemMessage):
        return {
            "seq": seq,
            "kind": "system",
            "user": message.author.name,
            "userColor": user_color_for_message(message),
            "segments": _segments_for(message),
        }

    raise TypeError(f"unsupported HUD message type: {type(message).__name__}")


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
