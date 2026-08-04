import sysconfig
from pathlib import Path

LAYER_SHELL_LIBRARY_NAME = "libbili-layer.so"
LAYER_SHELL_LIBRARY_PREFIX = "libbili-layer."
LAYER_SHELL_LIBRARY_SUFFIX = ".so"


def should_disable_layer_shell(platform_name: str, current_desktop: str) -> bool:
    desktops = {part.strip().lower() for part in current_desktop.split(":")}
    return platform_name.startswith("wayland") and "gnome" in desktops


def find_layer_shell_library(package_dir: str | Path) -> str | None:
    package_path = Path(package_dir)
    exact_path = package_path / LAYER_SHELL_LIBRARY_NAME
    if exact_path.exists():
        return str(exact_path)

    candidates = sorted(
        path
        for path in package_path.glob(f"{LAYER_SHELL_LIBRARY_PREFIX}*{LAYER_SHELL_LIBRARY_SUFFIX}")
        if path.is_file()
    )
    if candidates:
        return str(candidates[0])

    return None


def default_package_dir(source_package_dir: str | Path) -> Path:
    """Prefer the installed package directory when it contains the native bridge."""
    source_path = Path(source_package_dir)
    installed_path = Path(sysconfig.get_path("platlib")) / source_path.name
    if find_layer_shell_library(installed_path) is not None:
        return installed_path
    return source_path
