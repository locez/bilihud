"""Shared operating-system facts used by platform capability adapters."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType


class PlatformKind(StrEnum):
    """Operating-system families supported by the platform adapters."""

    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class PlatformContext:
    """Immutable process facts captured once at the composition boundary."""

    kind: PlatformKind
    home: Path
    environment: Mapping[str, str]


def platform_kind(platform_name: str) -> PlatformKind:
    """Normalize one interpreter platform name into the supported OS enum."""
    if platform_name.startswith("linux"):
        return PlatformKind.LINUX
    if platform_name == "darwin":
        return PlatformKind.MACOS
    if platform_name in {"win32", "cygwin", "msys"}:
        return PlatformKind.WINDOWS
    return PlatformKind.OTHER


def create_platform_context(
    platform_name: str | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> PlatformContext:
    """Capture platform facts, with injectable inputs for deterministic tests."""
    selected_platform = sys.platform if platform_name is None else platform_name
    selected_environment = os.environ if environment is None else environment
    selected_home = Path.home() if home is None else home
    return PlatformContext(
        kind=platform_kind(selected_platform),
        home=selected_home,
        environment=MappingProxyType(dict(selected_environment)),
    )


__all__ = ("PlatformContext", "PlatformKind", "create_platform_context", "platform_kind")
