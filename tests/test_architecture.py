import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "bilihud"
PURE_MODULE_NAMES: Final[tuple[str, ...]] = ("live_audience", "live_emoticons")
PRESENTATION_MODULE_NAMES: Final[tuple[str, ...]] = (
    "danmaku_widget",
    "live_control_dialog",
    "qr_login_dialog",
)


@dataclass(frozen=True)
class ImportRule:
    name: str
    files: tuple[Path, ...]
    forbidden_prefixes: frozenset[str]


DOMAIN_FORBIDDEN_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "PyQt5",
        "PyQt6",
        "aiohttp",
        "blivedm",
        "qasync",
        "bilihud.auth",
        "bilihud.danmaku_client",
        "bilihud.live_api",
        "bilihud.mirror_server",
        "bilihud.obs_api",
    }
)


def _python_files(path: Path) -> tuple[Path, ...]:
    if path.is_file():
        return (path,)
    if path.is_dir():
        return tuple(sorted(path.rglob("*.py")))
    return ()


def _rule_files() -> tuple[ImportRule, ...]:
    pure_files = tuple(SOURCE_ROOT / f"{name}.py" for name in PURE_MODULE_NAMES)
    domain_files = _python_files(SOURCE_ROOT / "domain")
    return (
        ImportRule("pure modules", pure_files, DOMAIN_FORBIDDEN_PREFIXES),
        ImportRule("domain package", domain_files, DOMAIN_FORBIDDEN_PREFIXES),
    )


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


def _is_forbidden(module: str, prefixes: frozenset[str]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def test_import_rules_cover_current_pure_modules() -> None:
    pure_files = tuple(SOURCE_ROOT / f"{name}.py" for name in PURE_MODULE_NAMES)

    assert all(path.is_file() for path in pure_files)


def test_layer_import_rules_reject_forbidden_dependencies() -> None:
    violations: list[str] = []
    for rule in _rule_files():
        for path in rule.files:
            for module in _imported_modules(path):
                if _is_forbidden(module, rule.forbidden_prefixes):
                    violations.append(f"{rule.name}: {path.relative_to(SOURCE_ROOT)} imports {module}")

    assert violations == []


def test_presentation_uses_configuration_and_authentication_boundaries() -> None:
    forbidden_modules = {"keyring"}
    forbidden_names = {"AuthManager", "KeyringSessionStore", "load_config", "save_config"}
    violations: list[str] = []

    for name in PRESENTATION_MODULE_NAMES:
        path = SOURCE_ROOT / f"{name}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_modules:
                        violations.append(f"{name} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in forbidden_names:
                        violations.append(f"{name} imports {alias.name}")

    assert violations == []
