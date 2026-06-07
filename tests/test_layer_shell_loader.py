from bilihud.layer_shell_loader import find_layer_shell_library, should_disable_layer_shell


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


def test_should_disable_layer_shell_on_gnome_wayland():
    assert should_disable_layer_shell("wayland", "ubuntu:GNOME") is True


def test_should_not_disable_layer_shell_on_kde_wayland():
    assert should_disable_layer_shell("wayland", "KDE") is False


def test_should_not_disable_layer_shell_on_x11():
    assert should_disable_layer_shell("xcb", "GNOME") is False
