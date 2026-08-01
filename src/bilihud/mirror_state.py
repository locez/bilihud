from __future__ import annotations

import re
from typing import Any

import blivedm.models.web as web_models

from .danmaku_format import (
    danmaku_author_badges,
    danmaku_emoticon_scaled_size,
    danmaku_emoticon_url,
    danmaku_inline_emoticons,
    danmaku_reply_text,
)

MIRROR_DEFAULT_PORT = 2233
MIRROR_ROUTE = "/bilihud-mirror"
MIRROR_EVENTS_ROUTE = "/bilihud-mirror/events"
MIRROR_IMAGE_ROUTE = "/bilihud-mirror/image"
MIRROR_MAX_MESSAGES = 200


def user_color_for_message(message: Any) -> str:
    if getattr(message, "is_system_error", False):
        return "#FF5555"
    if getattr(message, "is_system_info", False):
        return "#AAAAAA"
    if getattr(message, "privilege_type", 0) > 0:
        return "#FFD700"
    if isinstance(message, web_models.GiftMessage):
        return "#FFD700"
    if isinstance(message, web_models.InteractWordV2Message):
        return "#AAAAAA"
    if getattr(message, "vip", False) or getattr(message, "svip", False):
        return "#FF69B4"
    if getattr(message, "admin", False):
        return "#FF4500"
    return "#66CCFF"


def _image_segment(text: str, url: str, options: dict[str, Any]) -> dict[str, Any]:
    width, height = danmaku_emoticon_scaled_size(options)
    return {
        "type": "image",
        "text": text,
        "url": url,
        "width": width,
        "height": height,
    }


def danmaku_segments(message: web_models.DanmakuMessage) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    reply_text = danmaku_reply_text(message)
    if reply_text:
        segments.append({"type": "reply", "text": reply_text})

    pure_url = danmaku_emoticon_url(message)
    if pure_url:
        segments.append(_image_segment(message.msg.strip() or "表情", pure_url, message.emoticon_options_dict))
        return segments

    text = message.msg.strip()
    inline = {
        token: options
        for token, options in danmaku_inline_emoticons(message).items()
        if token in text
    }
    if not inline:
        segments.append({"type": "text", "text": text})
        return segments

    pattern = re.compile("|".join(re.escape(token) for token in sorted(inline, key=len, reverse=True)))
    last_end = 0
    for match in pattern.finditer(text):
        if match.start() > last_end:
            segments.append({"type": "text", "text": text[last_end:match.start()]})
        token = match.group(0)
        options = inline[token]
        segments.append(_image_segment(token, str(options.get("url") or ""), options))
        last_end = match.end()
    if last_end < len(text):
        segments.append({"type": "text", "text": text[last_end:]})
    return segments


def _interact_text(msg_type: int) -> str:
    return {
        1: "进入直播间",
        2: "关注了主播",
        3: "分享了直播间",
        4: "特别关注了主播",
        5: "互粉了主播",
        6: "为主播点赞了",
    }.get(msg_type, "进入直播间")


def message_to_mirror_entry(seq: int, message: Any) -> dict[str, Any]:
    if isinstance(message, web_models.DanmakuMessage):
        entry = {
            "seq": seq,
            "kind": "danmaku",
            "user": message.uname,
            "userColor": user_color_for_message(message),
            "segments": danmaku_segments(message),
        }
        badges = danmaku_author_badges(message)
        if badges:
            entry["badges"] = badges
        return entry

    if isinstance(message, web_models.GiftMessage):
        return {
            "seq": seq,
            "kind": "gift",
            "user": message.uname,
            "userColor": user_color_for_message(message),
            "segments": [{"type": "text", "text": f"{message.action} {message.gift_name} x{message.num}"}],
        }

    if isinstance(message, web_models.InteractWordV2Message):
        return {
            "seq": seq,
            "kind": "interact",
            "user": message.username,
            "userColor": user_color_for_message(message),
            "segments": [{"type": "text", "text": _interact_text(message.msg_type)}],
        }

    if hasattr(message, "uname") and hasattr(message, "msg") and not getattr(message, "is_system_info", False) and not getattr(message, "is_system_error", False):
        return {
            "seq": seq,
            "kind": "danmaku",
            "user": str(getattr(message, "uname", "")),
            "userColor": user_color_for_message(message),
            "segments": [{"type": "text", "text": str(getattr(message, "msg", ""))}],
        }

    return {
        "seq": seq,
        "kind": "system",
        "user": str(getattr(message, "uname", "")),
        "userColor": user_color_for_message(message),
        "segments": [{"type": "text", "text": str(getattr(message, "msg", ""))}],
    }


class MirrorState:
    def __init__(self, max_messages: int = MIRROR_MAX_MESSAGES):
        self.max_messages = max_messages
        self._next_seq = 1
        self._messages: list[dict[str, Any]] = []

    def add_message(self, message: Any) -> dict[str, Any]:
        entry = message_to_mirror_entry(self._next_seq, message)
        self._next_seq += 1
        self._messages.append(entry)
        if len(self._messages) > self.max_messages:
            self._messages = self._messages[-self.max_messages:]
        return entry

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._messages)
