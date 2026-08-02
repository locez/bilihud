from __future__ import annotations


def validate_room_id(room_id_str: str) -> bool:
    """Return whether a user-entered room identifier is a positive integer."""
    try:
        return int(room_id_str) > 0
    except ValueError:
        return False
