"""Load packaged static resources used by the Mirror browser surface."""

from __future__ import annotations

from importlib.resources import files


def read_bilihud_icon() -> bytes:
    """Return the packaged BiliHUD PNG icon for browser clients."""
    return files("bilihud").joinpath("assets", "icon.png").read_bytes()


__all__ = ("read_bilihud_icon",)
