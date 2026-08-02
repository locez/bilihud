from __future__ import annotations


def validate_room_id(room_id: str | int) -> bool:
    """Return whether a room identifier is a positive integer."""
    try:
        return int(room_id) > 0
    except (TypeError, ValueError):
        return False
