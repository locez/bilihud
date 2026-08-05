from collections.abc import Mapping
from pathlib import Path

import bilihud.config.legacy as legacy_config
import bilihud.config.store as config_store
from bilihud.platform.paths import UserConfigPaths, resolve_user_config_paths
from bilihud.platform.system import PlatformKind, create_platform_context, platform_kind


class IdentityMigrator:
    """Keep the config-store path test independent from secure storage."""

    def migrate(self, raw: Mapping[str, object]) -> tuple[dict[str, object], bool]:
        """Return the supplied mapping without changing its values."""
        return dict(raw), False


def test_platform_kind_normalizes_supported_interpreter_names() -> None:
    assert platform_kind("linux") is PlatformKind.LINUX
    assert platform_kind("darwin") is PlatformKind.MACOS
    assert platform_kind("win32") is PlatformKind.WINDOWS
    assert platform_kind("freebsd") is PlatformKind.OTHER


def test_linux_paths_use_absolute_xdg_config_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    xdg_home = tmp_path / "xdg config"
    context = create_platform_context(
        "linux",
        environment={"XDG_CONFIG_HOME": str(xdg_home)},
        home=home,
    )

    paths = resolve_user_config_paths(context)

    assert paths.directory == xdg_home / "bilihud"
    assert paths.file == xdg_home / "bilihud" / "config.json"


def test_linux_paths_fall_back_when_xdg_config_home_is_missing_or_relative(tmp_path: Path) -> None:
    home = tmp_path / "home"

    missing = resolve_user_config_paths(create_platform_context("linux", home=home))
    relative = resolve_user_config_paths(
        create_platform_context("linux", environment={"XDG_CONFIG_HOME": "relative"}, home=home)
    )

    expected = home / ".config" / "bilihud"
    assert missing.directory == expected
    assert relative.directory == expected


def test_macos_paths_use_application_support_without_linux_legacy_lookup(tmp_path: Path) -> None:
    home = tmp_path / "home"
    context = create_platform_context("darwin", environment={}, home=home)

    paths = resolve_user_config_paths(context)

    assert paths.directory == home / "Library" / "Application Support" / "bilihud"
    assert not (home / ".config" / "bilihud" / "config.json").exists()


def test_windows_paths_prefer_appdata_and_have_a_non_dot_config_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    appdata = tmp_path / "AppData" / "Roaming"

    configured = resolve_user_config_paths(
        create_platform_context("win32", environment={"APPDATA": str(appdata)}, home=home)
    )
    fallback = resolve_user_config_paths(create_platform_context("win32", environment={}, home=home))

    assert configured.directory == appdata / "bilihud"
    assert fallback.directory == home / "AppData" / "Roaming" / "bilihud"
    assert fallback.directory != home / ".config" / "bilihud"


def test_config_store_and_legacy_facade_share_the_canonical_path(monkeypatch, tmp_path: Path) -> None:
    expected = UserConfigPaths(tmp_path / "Application Support" / "bilihud")
    monkeypatch.setattr(config_store, "default_user_config_paths", lambda: expected)

    assert config_store.default_config_path() == expected.file
    assert legacy_config.get_config_path() == expected.file
    assert config_store.JsonConfigStore(migrator=IdentityMigrator()).path == expected.file
