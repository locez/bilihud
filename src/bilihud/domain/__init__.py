"""Stable domain contracts used by the application and presentation layers."""

from .messages import (
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
    SystemMessage,
    SystemMessageLevel,
    TextSegment,
    make_system_message,
)

__all__ = (
    "DanmakuMessage",
    "GiftMessage",
    "GiftCurrency",
    "HudMessage",
    "ImageSegment",
    "InteractionKind",
    "InteractMessage",
    "MessageAuthor",
    "MessageBadge",
    "MessageBadgeKind",
    "MessageSegment",
    "ReplySegment",
    "SystemMessage",
    "SystemMessageLevel",
    "TextSegment",
    "make_system_message",
)
