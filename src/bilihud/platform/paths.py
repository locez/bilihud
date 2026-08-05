"""Platform-specific user configuration directory resolution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .system import PlatformContext, PlatformKind, create_platform_context

APP_CONFIG_NAME = "bilihud"
CONFIG_FILE_NAME = "config.json"


@dataclass(frozen=True, slots=True)
class UserConfigPaths:
    """Canonical user configuration directory and file for one platform."""

    directory: Path

    @property
    def file(self) -> Path:
        """Return the canonical JSON configuration file below ``directory``."""
        return self.directory / CONFIG_FILE_NAME


UserConfigPathResolver = Callable[[PlatformContext], UserConfigPaths]


def _linux_paths(context: PlatformContext) -> UserConfigPaths:
    """Resolve Linux configuration through the XDG user configuration rule."""
    xdg_config_home = context.environment.get("XDG_CONFIG_HOME")
    if xdg_config_home is not None:
        candidate = Path(xdg_config_home)
        if xdg_config_home.strip() and candidate.is_absolute():
            return UserConfigPaths(candidate / APP_CONFIG_NAME)
    return UserConfigPaths(context.home / ".config" / APP_CONFIG_NAME)


def _macos_paths(context: PlatformContext) -> UserConfigPaths:
    """Resolve macOS configuration below the user's Application Support directory."""
    return UserConfigPaths(context.home / "Library" / "Application Support" / APP_CONFIG_NAME)


def _windows_paths(context: PlatformContext) -> UserConfigPaths:
    """Resolve Windows configuration below APPDATA with a controlled fallback."""
    appdata = context.environment.get("APPDATA")
    if appdata is not None:
        candidate = Path(appdata)
        if appdata.strip() and candidate.is_absolute():
            return UserConfigPaths(candidate / APP_CONFIG_NAME)
    return UserConfigPaths(context.home / "AppData" / "Roaming" / APP_CONFIG_NAME)


def _fallback_paths(context: PlatformContext) -> UserConfigPaths:
    """Provide a predictable home-directory fallback for unsupported systems."""
    return UserConfigPaths(context.home / ".config" / APP_CONFIG_NAME)


_PATH_RESOLVERS: dict[PlatformKind, UserConfigPathResolver] = {
    PlatformKind.LINUX: _linux_paths,
    PlatformKind.MACOS: _macos_paths,
    PlatformKind.WINDOWS: _windows_paths,
    PlatformKind.OTHER: _fallback_paths,
}


def resolve_user_config_paths(context: PlatformContext) -> UserConfigPaths:
    """Resolve one canonical configuration location from captured platform facts."""
    resolver = _PATH_RESOLVERS[context.kind]
    return resolver(context)


def default_user_config_paths() -> UserConfigPaths:
    """Resolve the current process user's canonical configuration location."""
    return resolve_user_config_paths(create_platform_context())


__all__ = (
    "UserConfigPaths",
    "default_user_config_paths",
    "resolve_user_config_paths",
)
