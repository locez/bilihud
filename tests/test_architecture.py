import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "bilihud"
FEATURE_PACKAGE_NAMES: Final[tuple[str, ...]] = (
    "app",
    "auth",
    "config",
    "danmaku",
    "live",
    "mirror",
    "platform",
)
PURE_MODULE_PATHS: Final[tuple[str, ...]] = (
    "app/hud.py",
    "danmaku/messages.py",
    "live/audience.py",
    "live/emoticons.py",
    "live/models.py",
    "live/validation.py",
)
PRESENTATION_MODULE_PATHS: Final[tuple[str, ...]] = (
    "danmaku_widget.py",
    "live_control_dialog.py",
    "qr_login_dialog.py",
    "qt_window_host.py",
)
MESSAGE_CONSUMER_MODULE_PATHS: Final[tuple[str, ...]] = (
    "danmaku/format.py",
    "danmaku_widget.py",
    "mirror/state.py",
    "danmaku/mock.py",
)
APPLICATION_FORBIDDEN_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "PyQt5",
        "PyQt6",
        "qasync",
        "blivedm",
        "aiohttp",
        "bilihud.danmaku.client",
        "bilihud.live.api",
        "bilihud.live.obs",
        "bilihud.mirror.server",
        "bilihud.platform.window_platform",
    }
)


@dataclass(frozen=True)
class ImportRule:
    name: str
    files: tuple[Path, ...]
    forbidden_prefixes: frozenset[str]


PURE_FORBIDDEN_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "PyQt5",
        "PyQt6",
        "aiohttp",
        "blivedm",
        "keyring",
        "qasync",
        "bilihud.auth.service",
        "bilihud.danmaku.client",
        "bilihud.live.api",
        "bilihud.live.obs",
        "bilihud.mirror.server",
    }
)


def _path(relative: str) -> Path:
    """Return one production module path from its package-relative name."""
    return SOURCE_ROOT / relative


def _python_files(path: Path) -> tuple[Path, ...]:
    if path.is_file():
        return (path,)
    if path.is_dir():
        return tuple(sorted(path.rglob("*.py")))
    return ()


def _rule_files() -> tuple[ImportRule, ...]:
    pure_files = tuple(_path(relative) for relative in PURE_MODULE_PATHS)
    return (ImportRule("feature contracts", pure_files, PURE_FORBIDDEN_PREFIXES),)


def _module_name(path: Path) -> str:
    relative = path.relative_to(SOURCE_ROOT).with_suffix("")
    return ".".join(("bilihud", *relative.parts))


def _relative_module_name(path: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    current_package = _module_name(path).rsplit(".", 1)[0].split(".")
    base = current_package[: len(current_package) - node.level + 1]
    if node.module:
        return (".".join((*base, node.module)),)
    return tuple(".".join((*base, alias.name)) for alias in node.names)


def _imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                modules.extend(_relative_module_name(path, node))
            elif node.module:
                modules.append(node.module)
    return tuple(modules)


def _imported_names(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.extend(alias.name for alias in node.names)
    return tuple(names)


def _is_forbidden(module: str, prefixes: frozenset[str]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def test_feature_packages_have_explicit_ownership() -> None:
    """Keep the feature-first package boundary present for future migrations."""
    assert all((_path(name) / "__init__.py").is_file() for name in FEATURE_PACKAGE_NAMES)
    assert not (_path("domain") / "__init__.py").exists()
    assert not (_path("infrastructure") / "__init__.py").exists()


def test_import_rules_cover_current_feature_contracts() -> None:
    assert all(path.is_file() for rule in _rule_files() for path in rule.files)


def test_feature_contracts_reject_forbidden_dependencies() -> None:
    violations: list[str] = []
    for rule in _rule_files():
        for path in rule.files:
            for module in _imported_modules(path):
                if _is_forbidden(module, rule.forbidden_prefixes):
                    violations.append(f"{rule.name}: {path.relative_to(SOURCE_ROOT)} imports {module}")

    assert violations == []


def test_message_consumers_do_not_import_blivedm_models() -> None:
    """Keep third-party message parsing behind the danmaku adapter."""
    violations: list[str] = []
    for relative in MESSAGE_CONSUMER_MODULE_PATHS:
        path = _path(relative)
        for module in _imported_modules(path):
            if _is_forbidden(module, frozenset({"blivedm"})):
                violations.append(f"{relative} imports {module}")

    assert violations == []


def test_presentation_uses_configuration_and_authentication_boundaries() -> None:
    forbidden_modules = {
        "aiohttp",
        "keyring",
        "bilihud.danmaku.client",
        "bilihud.live.obs",
    }
    forbidden_names = {"AuthManager", "KeyringSessionStore", "load_config", "save_config"}
    violations: list[str] = []

    for relative in PRESENTATION_MODULE_PATHS:
        path = _path(relative)
        for module in _imported_modules(path):
            if _is_forbidden(module, frozenset(forbidden_modules)):
                violations.append(f"{relative} imports {module}")
        for name in _imported_names(path):
            if name in forbidden_names:
                violations.append(f"{relative} imports {name}")

    assert violations == []


def _assert_application_imports_allowed(relative_paths: tuple[str, ...]) -> None:
    """Assert that application workflows depend on capabilities, not adapters."""
    violations: list[str] = []
    for relative in relative_paths:
        path = _path(relative)
        for module in _imported_modules(path):
            if _is_forbidden(module, APPLICATION_FORBIDDEN_PREFIXES):
                violations.append(f"{relative} imports {module}")

    assert violations == []


def test_hud_application_keeps_concrete_network_and_presentation_outside_application() -> None:
    _assert_application_imports_allowed(("app/hud_controller.py", "app/hud_client.py"))


def test_live_control_application_keeps_concrete_network_and_presentation_outside_application() -> None:
    _assert_application_imports_allowed(
        (
            "app/live_control_service.py",
            "app/live_control_api.py",
            "app/obs_control.py",
            "app/credential_store.py",
            "app/verification.py",
        )
    )


def test_mirror_application_keeps_http_and_presentation_outside_application() -> None:
    _assert_application_imports_allowed(("app/mirror_coordinator.py", "app/mirror_server.py"))


def test_danmaku_widget_uses_hud_controller_instead_of_concrete_client() -> None:
    modules = _imported_modules(_path("danmaku_widget.py"))

    assert "bilihud.app.hud_controller" in modules
    assert "bilihud.danmaku.client" not in modules


def test_danmaku_widget_uses_overlay_contracts_instead_of_platform_implementation() -> None:
    modules = _imported_modules(_path("danmaku_widget.py"))

    assert "bilihud.platform.overlay_contracts" in modules
    assert "bilihud.platform.window_platform" not in modules
    assert "bilihud.platform.layer_shell_loader" not in modules
    assert "ctypes" not in modules
    assert "PyQt6.sip" not in modules


def test_overlay_contracts_do_not_import_toolkits_or_native_libraries() -> None:
    modules = _imported_modules(_path("platform/overlay_contracts.py"))

    assert all(module not in {"PyQt5", "PyQt6", "ctypes"} for module in modules)
