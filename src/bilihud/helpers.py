"""Compatibility export for the live-room validation contract."""

from .live.validation import validate_room_id

# TODO: remove this shim after downstream callers migrate to bilihud.live.validation.

__all__ = ("validate_room_id",)
