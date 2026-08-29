"""Typed messages exchanged by the HUD, Mirror, and application workflows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MessageBadgeKind(StrEnum):
    """Classify a compact author badge shown beside a username."""

    MEDAL = "medal"
    WEALTH = "wealth"
    PRIVILEGE = "privilege"


class GiftCurrency(StrEnum):
    """Identify the Bilibili coin type used to price a gift."""

    GOLD = "gold"
    SILVER = "silver"
    UNKNOWN = "unknown"


class InteractionKind(StrEnum):
    """Normalize Bilibili interaction codes into stable HUD semantics."""

    ENTER = "enter"
    FOLLOW = "follow"
    SHARE = "share"
    SPECIAL_FOLLOW = "special_follow"
    MUTUAL_FOLLOW = "mutual_follow"
    LIKE = "like"

    @property
    def text(self) -> str:
        """Return the user-facing description shared by Qt and Mirror."""
        return {
            InteractionKind.ENTER: "进入直播间",
            InteractionKind.FOLLOW: "关注了主播",
            InteractionKind.SHARE: "分享了直播间",
            InteractionKind.SPECIAL_FOLLOW: "特别关注了主播",
            InteractionKind.MUTUAL_FOLLOW: "互粉了主播",
            InteractionKind.LIKE: "为主播点赞了",
        }[self]


class SystemMessageLevel(StrEnum):
    """Control the severity styling of a locally generated message."""

    INFO = "info"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class MessageBadge:
    """Describe one normalized badge attached to a message author."""

    kind: MessageBadgeKind
    text: str
    title: str
    color: str


@dataclass(frozen=True, slots=True)
class MessageAuthor:
    """Identify an author and carry the shared color and badge semantics."""

    uid: int
    name: str
    color: str
    badges: tuple[MessageBadge, ...] = ()


@dataclass(frozen=True, slots=True)
class TextSegment:
    """Represent a literal, already-normalized text fragment."""

    text: str


@dataclass(frozen=True, slots=True)
class ReplySegment:
    """Represent the highlighted prefix identifying a reply target."""

    text: str


@dataclass(frozen=True, slots=True)
class ImageSegment:
    """Represent an external image emoticon and its source dimensions."""

    text: str
    url: str
    width: int
    height: int

    def __post_init__(self) -> None:
        """Reject invalid dimensions before a segment reaches a renderer."""
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image segment dimensions must be positive")


type MessageSegment = TextSegment | ReplySegment | ImageSegment


@dataclass(frozen=True, slots=True)
class GiftEffectFrame:
    """Describe one rectangular frame inside a packed gift-effect video."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        """Reject negative origins and empty packed-video regions."""
        if self.x < 0 or self.y < 0:
            raise ValueError("gift effect frame origin must not be negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("gift effect frame dimensions must be positive")


@dataclass(frozen=True, slots=True)
class GiftEffectLayout:
    """Carry the color and grayscale-mask regions of one packed gift video."""

    rgb_frame: GiftEffectFrame
    alpha_frame: GiftEffectFrame


@dataclass(frozen=True, slots=True)
class HudMessage:
    """Base contract for every message consumed by presentation code."""

    author: MessageAuthor
    segments: tuple[MessageSegment, ...]


@dataclass(frozen=True, slots=True)
class DanmakuMessage(HudMessage):
    """A text or emoticon message sent to the live room."""


@dataclass(frozen=True, slots=True)
class GiftMessage(HudMessage):
    """A gift event normalized for display in the HUD and Mirror."""

    action: str
    gift_name: str
    quantity: int
    unit_price: int = 0
    currency: GiftCurrency = GiftCurrency.UNKNOWN
    gift_id: int = 0
    gift_image_url: str = ""
    gift_effect_url: str = ""
    gift_animation_url: str = ""
    gift_effect_layout: GiftEffectLayout | None = None

    def __post_init__(self) -> None:
        """Reject negative quantities or prices that cannot represent an event."""
        if self.quantity < 0:
            raise ValueError("gift quantity must not be negative")
        if self.unit_price < 0:
            raise ValueError("gift unit price must not be negative")
        if self.gift_id < 0:
            raise ValueError("gift id must not be negative")

    @property
    def total_price(self) -> int:
        """Return the total coin value represented by this gift event."""
        return self.unit_price * self.quantity


@dataclass(frozen=True, slots=True)
class SuperChatMessage(HudMessage):
    """A paid Super Chat message with the official visual theme metadata."""

    message_id: int
    price: int
    message: str
    start_time: int = 0
    end_time: int = 0
    background_color: str = "#3C2A4D"
    background_bottom_color: str = "#2A2038"
    background_icon: str = ""
    background_image: str = ""
    background_price_color: str = "#FFD86E"

    def __post_init__(self) -> None:
        """Reject negative identifiers, prices, and timestamps from the wire."""
        if self.message_id < 0:
            raise ValueError("Super Chat message id must not be negative")
        if self.price < 0:
            raise ValueError("Super Chat price must not be negative")
        if self.start_time < 0 or self.end_time < 0:
            raise ValueError("Super Chat timestamps must not be negative")


@dataclass(frozen=True, slots=True)
class InteractMessage(HudMessage):
    """An audience interaction with an optional count for batched likes."""

    interaction: InteractionKind
    count: int = 1

    def __post_init__(self) -> None:
        """Reject counts that cannot represent an interaction event."""
        if self.count < 1:
            raise ValueError("interaction count must be positive")

    @property
    def text(self) -> str:
        """Return the interaction text, including a batched like count."""
        if self.interaction is InteractionKind.LIKE and self.count > 1:
            return f"{self.interaction.text} x{self.count}"
        return self.interaction.text


@dataclass(frozen=True, slots=True)
class SystemMessage(HudMessage):
    """A local informational or error message generated by the application."""

    level: SystemMessageLevel

    @property
    def text(self) -> str:
        """Return the textual content for logging and the compact Qt renderer."""
        return "".join(
            segment.text
            for segment in self.segments
            if isinstance(segment, (TextSegment, ReplySegment))
        )


def make_system_message(
    text: str,
    level: SystemMessageLevel = SystemMessageLevel.INFO,
) -> SystemMessage:
    """Create a system message with the standard local author styling."""
    color = "#FF5555" if level is SystemMessageLevel.ERROR else "#AAAAAA"
    author = MessageAuthor(uid=0, name=" [系统]", color=color)
    return SystemMessage(
        author=author,
        segments=(TextSegment(text),),
        level=level,
    )
