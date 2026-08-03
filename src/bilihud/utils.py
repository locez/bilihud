"""Compatibility exports for callers of the former generic utility module."""

from .config.legacy import get_config_path, load_config, save_config
from .danmaku.compat import DanmakuMessageLike, format_danmaku_message
from .live.validation import validate_room_id

# TODO: remove this shim after downstream callers migrate to the owning feature packages.

__all__ = (
    "DanmakuMessageLike",
    "format_danmaku_message",
    "get_config_path",
    "load_config",
    "save_config",
    "validate_room_id",
)
