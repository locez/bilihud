"""Ports separating Mirror application coordination from its HTTP adapter."""

from __future__ import annotations

from typing import Protocol

from .mirror_state import MirrorEntry, MirrorState


class MirrorServerPort(Protocol):
    """HTTP capability required by the Mirror application coordinator."""

    @property
    def url(self) -> str:
        """Return the browser URL exposed by the server."""
        ...

    async def start(self) -> None:
        """Start serving the coordinator-owned Mirror state."""
        ...

    async def stop(self) -> None:
        """Stop serving and release all HTTP resources."""
        ...

    def publish_append(self, entry: MirrorEntry) -> None:
        """Publish one coordinator-serialized message to connected clients."""
        ...


class MirrorServerFactory(Protocol):
    """Build one infrastructure server around coordinator-owned state."""

    def __call__(self, state: MirrorState, *, port: int) -> MirrorServerPort:
        """Create a stopped server without performing network I/O."""
        ...


__all__ = ("MirrorServerFactory", "MirrorServerPort")
