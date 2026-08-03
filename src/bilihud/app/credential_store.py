"""Application-owned storage capability for the OBS WebSocket password."""

from __future__ import annotations

from typing import Protocol


class ObsPasswordStore(Protocol):
    """Secure storage capability required by live-control settings."""

    def load_obs_password(self) -> str | None:
        """Load the OBS password, or return ``None`` when it is absent."""
        ...

    def save_obs_password(self, password: str) -> bool:
        """Save the OBS password and report whether storage succeeded."""
        ...

    def clear_obs_password(self) -> None:
        """Remove the OBS password from secure storage."""
        ...


__all__ = ("ObsPasswordStore",)
