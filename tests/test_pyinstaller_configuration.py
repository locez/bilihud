import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).parents[1]
BUILD_MODULE_PATH = PROJECT_ROOT / "packaging" / "pyinstaller" / "build.py"


def _load_build_module() -> ModuleType:
    """Load the standalone PyInstaller build helper without invoking a build."""
    spec = importlib.util.spec_from_file_location("bilihud_pyinstaller_build", BUILD_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load build helper: {BUILD_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_entry_point_module() -> ModuleType:
    """Load the PyInstaller entry point without importing the Qt application."""
    entry_point_path = PROJECT_ROOT / "packaging" / "pyinstaller" / "entry_point.py"
    spec = importlib.util.spec_from_file_location("bilihud_pyinstaller_entry_point", entry_point_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load entry point: {entry_point_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pyinstaller_collects_certifi_only_for_macos() -> None:
    build_module = _load_build_module()
    macos_target = build_module._BuildTarget("macos", "arm64", False, ".dmg")
    windows_target = build_module._BuildTarget("windows", "x64", True, ".exe")

    macos_arguments = build_module._pyinstaller_arguments(macos_target)
    windows_arguments = build_module._pyinstaller_arguments(windows_target)

    assert any(
        macos_arguments[index : index + 2] == ["--collect-all", "certifi"]
        for index in range(len(macos_arguments) - 1)
    )
    assert "certifi" not in windows_arguments


@pytest.mark.parametrize(
    ("target", "expected_icon_name", "expected_format"),
    [
        ("windows", "icon.ico", "ICO"),
        ("macos", "icon.icns", "ICNS"),
    ],
)
def test_pyinstaller_uses_the_native_bilihud_icon(
    target: str,
    expected_icon_name: str,
    expected_format: str,
) -> None:
    build_module = _load_build_module()
    build_target = build_module._BuildTarget(
        target,
        "x64" if target == "windows" else "arm64",
        target == "windows",
        ".exe" if target == "windows" else ".dmg",
    )

    arguments = build_module._pyinstaller_arguments(build_target)
    icon_argument_index = arguments.index("--icon")
    icon_path = Path(arguments[icon_argument_index + 1])

    assert icon_path.name == expected_icon_name
    assert icon_path.is_file()
    with Image.open(icon_path) as icon:
        assert icon.format == expected_format


def test_pyinstaller_entry_point_configures_tls_before_application_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_point_module = _load_entry_point_module()
    events: list[tuple[str, str | None]] = []

    class FakeCertifiModule(ModuleType):
        """Expose the certifi API used by the packaging entry point."""

        def __init__(self) -> None:
            super().__init__("certifi")

        def where(self) -> str:
            return "/bundle/cacert.pem"

    class FakeApplicationModule(ModuleType):
        """Record when the application entry point is invoked."""

        def __init__(self) -> None:
            super().__init__("bilihud.main")

        def entry_point(self) -> None:
            events.append(("application", None))

    def record_configuration(*, ca_bundle_path: str | None) -> None:
        events.append(("configure", ca_bundle_path))

    monkeypatch.setattr(entry_point_module.sys, "platform", "darwin")
    monkeypatch.setattr(entry_point_module, "configure_macos_ca_bundle", record_configuration)
    monkeypatch.setitem(sys.modules, "certifi", FakeCertifiModule())
    monkeypatch.setitem(sys.modules, "bilihud.main", FakeApplicationModule())

    entry_point_module.main()

    assert events == [("configure", "/bundle/cacert.pem"), ("application", None)]
