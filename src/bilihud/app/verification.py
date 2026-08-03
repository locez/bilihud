"""Verification-image capability required by presentation workflows."""

from __future__ import annotations

from io import BytesIO
from typing import Protocol


class QrImageGenerator(Protocol):
    """Generate an in-memory QR image for a verification URL."""

    def generate_qr_image(self, url: str) -> BytesIO | None:
        """Return PNG bytes for the URL, or ``None`` when generation fails."""
        ...


__all__ = ("QrImageGenerator",)
