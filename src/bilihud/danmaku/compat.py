"""Temporary compatibility formatting for the former generic utility module."""

from __future__ import annotations

from typing import Protocol

# TODO: remove this compatibility module after callers use normalized HudMessage values.


class DanmakuMessageLike(Protocol):
    """Minimal legacy message shape required by the compatibility formatter."""

    uname: str
    msg: str


def format_danmaku_message(danmaku_msg: DanmakuMessageLike) -> str:
    """Format the minimal legacy danmaku message shape for display."""
    return f"{danmaku_msg.uname}: {danmaku_msg.msg}"


__all__ = ("DanmakuMessageLike", "format_danmaku_message")
