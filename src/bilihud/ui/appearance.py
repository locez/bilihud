"""Presentation colors for the standalone settings window."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication

from bilihud.config.store import ThemeMode


@dataclass(frozen=True, slots=True)
class Appearance:
    """Resolved colors and contrast values for one appearance mode."""

    dark: bool
    window: str
    surface: str
    surface_alt: str
    text: str
    muted_text: str
    border: str
    accent: str
    accent_soft: str


def resolve_appearance(mode: ThemeMode) -> Appearance:
    """Resolve a stored theme mode into concrete colors for the current desktop."""
    dark = _system_is_dark() if mode is ThemeMode.SYSTEM else mode is ThemeMode.DARK
    if dark:
        return Appearance(
            dark=True,
            window="#17191e",
            surface="#22252c",
            surface_alt="#2b2f38",
            text="#f4f5f7",
            muted_text="#a0a7b3",
            border="#3a3f49",
            accent="#ff4f9a",
            accent_soft="#4a293e",
        )
    return Appearance(
        dark=False,
        window="#f5f6f8",
        surface="#ffffff",
        surface_alt="#eef0f4",
        text="#1d2026",
        muted_text="#737b88",
        border="#dfe3ea",
        accent="#ed4b91",
        accent_soft="#fbe1ed",
    )


def _system_is_dark() -> bool:
    """Read the desktop palette without assuming a running application in tests."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return True
    return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


__all__ = ("Appearance", "resolve_appearance")
