"""Build the Windows executable or macOS disk image for BiliHUD."""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYINSTALLER_ENTRY_POINT = PROJECT_ROOT / "packaging" / "pyinstaller" / "entry_point.py"
PYINSTALLER_DIST = PROJECT_ROOT / "dist" / "pyinstaller"
PACKAGE_DIST = PROJECT_ROOT / "dist" / "packages"


@dataclass(frozen=True, slots=True)
class _BuildTarget:
    """Describe the artifact format supported by the current host platform."""

    platform_name: str
    architecture: str
    one_file: bool
    artifact_suffix: str

    @property
    def generated_application(self) -> Path:
        """Return the path PyInstaller is expected to create below its dist directory."""
        if self.one_file:
            return Path("bilihud.exe")
        return Path("bilihud.app")

    @property
    def executable(self) -> Path:
        """Return the executable path used to validate the generated application."""
        if self.one_file:
            return self.generated_application
        return self.generated_application / "Contents" / "MacOS" / "bilihud"

    def artifact_filename(self, version: str) -> str:
        """Return the stable release filename for this platform and architecture."""
        return f"bilihud-{version}-{self.platform_name}-{self.architecture}{self.artifact_suffix}"


def _detect_target() -> _BuildTarget:
    """Map the host operating system to a supported desktop artifact format."""
    system_name = platform.system()
    if system_name == "Windows":
        platform_name = "windows"
        one_file = True
        artifact_suffix = ".exe"
    elif system_name == "Darwin":
        platform_name = "macos"
        one_file = False
        artifact_suffix = ".dmg"
    else:
        raise RuntimeError(f"Unsupported desktop packaging platform: {system_name}")

    machine = platform.machine().lower()
    if not machine:
        machine = "unknown"
    architecture = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if architecture is None:
        architecture = machine.replace(" ", "-")

    return _BuildTarget(
        platform_name=platform_name,
        architecture=architecture,
        one_file=one_file,
        artifact_suffix=artifact_suffix,
    )


def _read_project_version(project_file: Path) -> str:
    """Read and validate the fallback version from the project metadata."""
    with project_file.open("rb") as handle:
        document = tomllib.load(handle)
    project = document.get("project")
    if not isinstance(project, dict):
        raise RuntimeError("pyproject.toml does not contain a project table")
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError("pyproject.toml does not contain a project version")
    return version


def _resolve_version() -> str:
    """Use the release tag version when running in GitHub Actions."""
    tag_prefix = "refs/tags/v"
    github_ref = os.environ.get("GITHUB_REF")
    if github_ref is not None and github_ref.startswith(tag_prefix):
        version = github_ref[len(tag_prefix) :]
        if version:
            return version
    return _read_project_version(PROJECT_ROOT / "pyproject.toml")


def _pyinstaller_arguments(target: _BuildTarget) -> list[str]:
    """Build the platform-independent PyInstaller analysis configuration."""
    arguments = [
        "--noconfirm",
        "--clean",
        "--windowed",
    ]
    if target.one_file:
        arguments.append("--onefile")
    arguments.extend(
        [
            "--name",
            "bilihud",
            "--distpath",
            str(PYINSTALLER_DIST),
            "--workpath",
            str(PYINSTALLER_DIST / "build"),
            "--specpath",
            str(PYINSTALLER_DIST / "spec"),
            "--paths",
            str(PROJECT_ROOT / "src"),
            "--paths",
            str(PROJECT_ROOT / "vendor" / "blivedm"),
        ]
    )
    for package_name in ("bilihud", "blivedm", "PyQt6", "keyring"):
        arguments.extend(("--collect-all", package_name))
    if target.platform_name == "macos":
        arguments.extend(("--collect-all", "certifi"))
    arguments.append(str(PYINSTALLER_ENTRY_POINT))
    return arguments


def _run_pyinstaller(target: _BuildTarget) -> None:
    """Run PyInstaller with the checked-in entry point and source paths."""
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", *_pyinstaller_arguments(target)],
        check=True,
    )


def _require_file(path: Path, description: str) -> None:
    """Fail the build when an expected executable was not emitted."""
    if not path.is_file():
        raise RuntimeError(f"PyInstaller did not create the {description}: {path}")


def _create_windows_artifact(target: _BuildTarget, version: str, executable: Path) -> Path:
    """Copy the single-file Windows executable to the upload directory."""
    artifact = PACKAGE_DIST / target.artifact_filename(version)
    shutil.copy2(executable, artifact)
    return artifact


def _create_macos_artifact(target: _BuildTarget, version: str, application: Path) -> Path:
    """Create a compressed macOS disk image containing the application bundle."""
    artifact = PACKAGE_DIST / target.artifact_filename(version)
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            "BiliHUD",
            "-srcfolder",
            str(application),
            "-ov",
            "-format",
            "UDZO",
            str(artifact),
        ],
        check=True,
    )
    return artifact


def build() -> Path:
    """Build and return the final desktop artifact for the current host."""
    target = _detect_target()
    version = _resolve_version()
    PACKAGE_DIST.mkdir(parents=True, exist_ok=True)
    PYINSTALLER_DIST.mkdir(parents=True, exist_ok=True)

    _run_pyinstaller(target)
    generated_root = PYINSTALLER_DIST / target.generated_application
    generated_executable = PYINSTALLER_DIST / target.executable
    _require_file(generated_executable, "application executable")

    if target.one_file:
        artifact = _create_windows_artifact(target, version, generated_executable)
    else:
        artifact = _create_macos_artifact(target, version, generated_root)
    LOGGER.info("Created desktop artifact: %s", artifact)
    return artifact


def main() -> None:
    """Configure build logging and create the platform-specific artifact."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build()


if __name__ == "__main__":
    main()
