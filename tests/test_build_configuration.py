from __future__ import annotations

import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
CMAKE = shutil.which("cmake")


def _configure_cmake(
    build_dir: Path,
    *defines: str,
    source_dir: Path = PROJECT_ROOT,
) -> subprocess.CompletedProcess[str]:
    """Configure the native project with explicit dependency discovery controls."""
    command = [
        "cmake",
        "-S",
        str(source_dir),
        "-B",
        str(build_dir),
        *defines,
    ]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _installed_native_files(install_dir: Path) -> tuple[Path, ...]:
    """Return native bridge files emitted by a CMake install into a test prefix."""
    return tuple(
        path
        for path in install_dir.rglob("libbili-layer*")
        if path.is_file()
    )


@pytest.mark.skipif(CMAKE is None, reason="cmake is required for build configuration tests")
def test_cmake_auto_mode_falls_back_without_layer_shell_dependencies(tmp_path: Path) -> None:
    """A source build remains installable when Linux native dependencies are unavailable."""
    build_dir = tmp_path / "build"
    result = _configure_cmake(
        build_dir,
        "-DBILIHUD_LAYER_SHELL=AUTO",
        "-DCMAKE_DISABLE_FIND_PACKAGE_Qt6=TRUE",
        "-DCMAKE_DISABLE_FIND_PACKAGE_LayerShellQt=TRUE",
        "-DCMAKE_DISABLE_FIND_PACKAGE_PkgConfig=TRUE",
    )

    assert result.returncode == 0, result.stdout + result.stderr

    install_dir = tmp_path / "install"
    subprocess.run(
        ["cmake", "--install", str(build_dir), "--prefix", str(install_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert _installed_native_files(install_dir) == ()


@pytest.mark.skipif(CMAKE is None, reason="cmake is required for build configuration tests")
def test_cmake_native_install_uses_python_platlib_by_default(tmp_path: Path) -> None:
    """A direct CMake install places the bridge beside the installed Python package."""
    build_dir = tmp_path / "build"
    result = _configure_cmake(
        build_dir,
        "-DBILIHUD_LAYER_SHELL=ON",
        f"-DPython3_EXECUTABLE={sys.executable}",
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        if "dependencies are missing" in output or "only supported on Linux" in output:
            pytest.skip("native Layer Shell dependencies are unavailable")
        assert result.returncode == 0, output

    subprocess.run(
        ["cmake", "--build", str(build_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    install_dir = tmp_path / "install"
    subprocess.run(
        ["cmake", "--install", str(build_dir), "--prefix", str(install_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    platlib = Path(sysconfig.get_path("platlib", vars={"base": "", "platbase": ""}).lstrip("/"))
    assert (install_dir / platlib / "bilihud" / "libbili-layer.so").is_file()


@pytest.mark.skipif(CMAKE is None, reason="cmake is required for build configuration tests")
def test_cmake_disable_mode_does_not_install_a_stale_native_bridge(tmp_path: Path) -> None:
    """Disabling the bridge in a reused build directory removes its install entry."""
    build_dir = tmp_path / "build"
    native_result = _configure_cmake(build_dir, "-DBILIHUD_LAYER_SHELL=ON")
    native_output = native_result.stdout + native_result.stderr
    if native_result.returncode != 0:
        if "dependencies are missing" in native_output or "only supported on Linux" in native_output:
            pytest.skip("native Layer Shell dependencies are unavailable")
        assert native_result.returncode == 0, native_output

    subprocess.run(
        ["cmake", "--build", str(build_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    disabled_result = _configure_cmake(build_dir, "-DBILIHUD_LAYER_SHELL=OFF")
    assert disabled_result.returncode == 0, disabled_result.stdout + disabled_result.stderr

    install_dir = tmp_path / "install"
    subprocess.run(
        ["cmake", "--install", str(build_dir), "--prefix", str(install_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert _installed_native_files(install_dir) == ()


@pytest.mark.skipif(CMAKE is None, reason="cmake is required for build configuration tests")
def test_cmake_forced_layer_shell_mode_reports_missing_dependencies(tmp_path: Path) -> None:
    """A requested native bridge fails explicitly instead of silently producing a partial build."""
    result = _configure_cmake(
        tmp_path / "build",
        "-DBILIHUD_LAYER_SHELL=ON",
        "-DCMAKE_DISABLE_FIND_PACKAGE_Qt6=TRUE",
        "-DCMAKE_DISABLE_FIND_PACKAGE_LayerShellQt=TRUE",
        "-DCMAKE_DISABLE_FIND_PACKAGE_PkgConfig=TRUE",
    )

    assert result.returncode != 0
    assert "dependencies are missing" in result.stdout + result.stderr


@pytest.mark.skipif(CMAKE is None, reason="cmake is required for build configuration tests")
def test_cmake_off_mode_does_not_probe_native_dependencies(tmp_path: Path) -> None:
    """The explicit generic build path succeeds even when native discovery is disabled."""
    result = _configure_cmake(
        tmp_path / "build",
        "-DBILIHUD_LAYER_SHELL=OFF",
        "-DCMAKE_DISABLE_FIND_PACKAGE_Qt6=TRUE",
        "-DCMAKE_DISABLE_FIND_PACKAGE_LayerShellQt=TRUE",
        "-DCMAKE_DISABLE_FIND_PACKAGE_PkgConfig=TRUE",
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(CMAKE is None, reason="cmake is required for build configuration tests")
def test_cmake_auto_mode_skips_linux_bridge_for_non_linux_targets(tmp_path: Path) -> None:
    """A non-Linux target never enters the Linux-only compiler and dependency path."""
    result = _configure_cmake(
        tmp_path / "build",
        "-DBILIHUD_LAYER_SHELL=AUTO",
        "-DCMAKE_SYSTEM_NAME=Windows",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Layer Shell bridge skipped on Windows" in result.stdout
