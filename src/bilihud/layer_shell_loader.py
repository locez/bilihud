# -*- coding: utf-8 -*-
from pathlib import Path


LAYER_SHELL_LIBRARY_NAME = "libbili-layer.so"
LAYER_SHELL_LIBRARY_PREFIX = "libbili-layer."
LAYER_SHELL_LIBRARY_SUFFIX = ".so"


def should_disable_layer_shell(platform_name: str, current_desktop: str) -> bool:
    desktops = {part.strip().lower() for part in current_desktop.split(":")}
    return platform_name.startswith("wayland") and "gnome" in desktops


def gaming_mode_available(platform_name: str, has_layer_shell: bool, layer_shell_disabled: bool) -> bool:
    return has_layer_shell or not (platform_name.startswith("wayland") and layer_shell_disabled)


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
