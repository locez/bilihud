import bilihud.platform.layer_shell_loader as layer_shell_loader
from bilihud.platform.layer_shell_loader import (
    default_package_dir,
    find_layer_shell_library,
    should_disable_layer_shell,
)


def test_find_layer_shell_library_prefers_unsuffixed_name(tmp_path):
    suffixed = tmp_path / "libbili-layer.cpython-314-x86_64-linux-gnu.so"
    exact = tmp_path / "libbili-layer.so"
    suffixed.touch()
    exact.touch()

    assert find_layer_shell_library(tmp_path) == str(exact)


def test_find_layer_shell_library_accepts_debian_python_abi_suffix(tmp_path):
    suffixed = tmp_path / "libbili-layer.cpython-314-x86_64-linux-gnu.so"
    suffixed.touch()

    assert find_layer_shell_library(tmp_path) == str(suffixed)


def test_find_layer_shell_library_returns_none_when_missing(tmp_path):
    assert find_layer_shell_library(tmp_path) is None


def test_default_package_dir_prefers_installed_package_with_bridge(tmp_path, monkeypatch):
    source_package = tmp_path / "src" / "bilihud"
    installed_package = tmp_path / "venv" / "lib" / "python3.14" / "site-packages" / "bilihud"
    source_package.mkdir(parents=True)
    installed_package.mkdir(parents=True)
    (installed_package / "libbili-layer.so").touch()
    monkeypatch.setattr(
        layer_shell_loader.sysconfig,
        "get_path",
        lambda _name: str(installed_package.parent),
    )

    assert default_package_dir(source_package) == installed_package


def test_default_package_dir_falls_back_to_source_without_bridge(tmp_path, monkeypatch):
    source_package = tmp_path / "src" / "bilihud"
    installed_package = tmp_path / "venv" / "lib" / "python3.14" / "site-packages" / "bilihud"
    source_package.mkdir(parents=True)
    installed_package.mkdir(parents=True)
    monkeypatch.setattr(
        layer_shell_loader.sysconfig,
        "get_path",
        lambda _name: str(installed_package.parent),
    )

    assert default_package_dir(source_package) == source_package


def test_should_disable_layer_shell_on_gnome_wayland():
    assert should_disable_layer_shell("wayland", "ubuntu:GNOME") is True


def test_should_not_disable_layer_shell_on_kde_wayland():
    assert should_disable_layer_shell("wayland", "KDE") is False


def test_should_not_disable_layer_shell_on_x11():
    assert should_disable_layer_shell("xcb", "GNOME") is False
